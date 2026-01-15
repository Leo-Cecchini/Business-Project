# services/schedule_service.py
from datetime import datetime, timedelta
from collections import defaultdict, deque
from uuid import uuid4
import math
import re
import traceback
from typing import List, Dict, Any, Optional
from bson import ObjectId
from mongoengine.connection import get_db

# Telemetria opzionale
try:
    from backend.utils.telemetry import log_assignment_attempt
except ImportError:
    def log_assignment_attempt(*args, **kwargs): pass

class ScheduleService:
    """
    Gestisce la pianificazione (Gantt), la verifica capacità (Capacity) 
    e l'assegnazione risorse (Assignments).
    """

    # --- HELPERS STATICI (Date & Utils) ---

    @staticmethod
    def _parse_date(s: Any) -> Optional[datetime]:
        if not s: return None
        if isinstance(s, datetime): return s
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d")
        except ValueError:
            return None

    @staticmethod
    def _norm_role(s: Any) -> str:
        """Normalize role strings (e.g. 'capo cantiere', 'capo_cantiere', 'capocantiere')."""
        return "".join(ch for ch in str(s or "").lower().strip() if ch.isalnum())

    @staticmethod
    def _role_regex(role: Any) -> str:
        """Build a tolerant regex for role matching (spaces/underscores/hyphens treated as optional)."""
        r = str(role or "").strip().lower()
        if not r:
            return ""
        esc = re.escape(r)
        # make separators flexible
        esc = esc.replace("\\ ", r"[\\s_-]*")
        esc = esc.replace("\\_", r"[\\s_-]*")
        esc = esc.replace("\\-", r"[\\s_-]*")
        return esc

    @staticmethod
    def _daterange(d0: datetime, d1: datetime):
        cur = d0
        while cur <= d1:
            yield cur
            cur += timedelta(days=1)

    @staticmethod
    def _overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
        return not (a_end < b_start or b_end < a_start)

    # --- QUERY HELPERS (Database Raw) ---

    @staticmethod
    def _crew_from_catalog(db, work_code: str):
        if not work_code: return {}
        doc = db["work_catalog"].find_one(
            {"code": {"$regex": f"^{work_code}$", "$options": "i"}}, 
            {"_id": 0, "min_crew": 1, "crew_roles": 1}
        )
        if not doc: return {}
        out = {}
        if doc.get("crew_roles"):
            out["crew_roles"] = {str(k).lower(): int(v) for k, v in doc["crew_roles"].items() if isinstance(v, (int, float))}
        if doc.get("min_crew"):
            out["min_crew"] = int(doc["min_crew"])
        return out

    @staticmethod
    def _find_free_ids_for_role(db, role: str, region: str = None, city: str = None) -> List[str]:
        # tolerant role matching (handles 'capo cantiere' vs 'capocantiere' vs 'capo_cantiere', and 'senior' variants)
        role_rx = ScheduleService._role_regex(role)
        filt = {"available": True, "role": {"$regex": role_rx, "$options": "i"}}
        if region: filt["home_region"] = {"$regex": f"^{region}$", "$options": "i"}
        if city: filt["home_city"] = {"$regex": f"^{city}$", "$options": "i"}
        
        # ✅ FIX: Recupera _id (ObjectId) e convertilo in string
        cur = db["workers"].find(filt, {"_id": 1})
        return [str(w["_id"]) for w in cur if "_id" in w]

    @staticmethod
    def _busy_workers_in_range(db, start: datetime, end: datetime) -> Dict[str, set]:
        """Map role -> set(worker_ids) occupati nel range."""
        out = defaultdict(set)
        
        # ✅ Cerca nei works di tutti i progetti attivi
        projects = db["projects"].find(
            {"status": {"$in": ["Confermato", "In Corso"]}},
            {"_id": 0, "works": 1}
        )
        
        for proj in projects:
            for work in proj.get("works", []):
                s = ScheduleService._parse_date(work.get("start_date_planned"))
                e = ScheduleService._parse_date(work.get("end_date_planned"))
                if not s or not e: continue
                
                if ScheduleService._overlap(s, e, start, end):
                    # I workers in questo work sono occupati
                    for wid in work.get("workers", []):
                        # Qui non abbiamo il role specifico, assumiamo occupato per tutti i ruoli
                        # Alternativa: potresti fare lookup su workers collection
                        out["_any"].add(wid)
        
        return out

    @staticmethod
    def _get_productivity(db, work_code: str):
        if not work_code: return None, None
        doc = db["work_catalog"].find_one(
            {"code": {"$regex": f"^{work_code}$", "$options": "i"}},
            {"_id":0, "productivity_per_worker_per_hour":1, "unit":1}
        )
        if not doc: return None, None
        return doc.get("productivity_per_worker_per_hour"), doc.get("unit")

    @staticmethod
    def _estimate_duration_days(qty: float, prod: float, crew_size: int, daily_hours: int) -> int:
        try:
            qty = float(qty or 0)
            crew = max(1, int(crew_size or 1))
            hours = max(1, int(daily_hours or 8))
            if not prod or prod <= 0: return 1
            tot_hours = qty / (prod * crew)
            return max(1, math.ceil(tot_hours / hours))
        except Exception:
            return 1

    @staticmethod
    def _simple_topo_order(db, items):
        """Topological order of work items based on prerequisites.

        Supports:
          - prerequisites_all (AND)     -> all are required
          - prerequisites (legacy AND) -> treated like prerequisites_all
          - prerequisites_any (OR)     -> list of lists; each inner list is an OR-group.
            For planning we pick, for each OR-group, the first prerequisite that is
            present among the selected works. If none are present, the OR-group is
            ignored (the work remains schedulable).

        Side-effect:
          - stores the effective prerequisites list in each item as '_deps_effective'
        """
        codes = [it.get("code") for it in items]
        codes_set = {c for c in codes if c}

        eff_deps: dict[str, list[str]] = {}
        for it in items:
            c = it.get("code")
            if not c:
                continue

            deps_all = it.get("prerequisites_all")
            if deps_all is None:
                deps_all = it.get("prerequisites") or []
            if isinstance(deps_all, str):
                deps_all = [deps_all]
            deps_all = [str(x).strip() for x in (deps_all or []) if x and str(x).strip()]

            deps_any = it.get("prerequisites_any") or []
            # tolerate legacy: list[str] => one OR group
            if isinstance(deps_any, list) and deps_any and all(isinstance(x, str) for x in deps_any):
                deps_any = [deps_any]
            if isinstance(deps_any, str):
                deps_any = [[deps_any]]

            chosen_any: list[str] = []
            if isinstance(deps_any, list):
                for grp in deps_any:
                    if not grp:
                        continue
                    grp_list = grp if isinstance(grp, list) else [grp]
                    grp_list = [str(x).strip() for x in grp_list if x and str(x).strip()]
                    pick = next((p for p in grp_list if p in codes_set), None)
                    if pick:
                        chosen_any.append(pick)

            eff = deps_all + chosen_any
            eff_deps[c] = eff
            it["_deps_effective"] = eff

        graph = {c: set(eff_deps.get(c, [])) for c in codes_set}
        indeg = {c: 0 for c in graph}
        for c, deps in graph.items():
            for p in deps:
                if p in graph:
                    indeg[c] += 1

        q = [c for c, d in indeg.items() if d == 0]
        out: list[str] = []
        while q:
            n = q.pop(0)
            out.append(n)
            for m in graph:
                if n in graph[m]:
                    indeg[m] -= 1
                    if indeg[m] == 0:
                        q.append(m)

        # append leftovers (cycles/unknown refs) in stable order
        if len(out) < len(codes_set):
            for c in codes:
                if c in codes_set and c not in out:
                    out.append(c)

        i2idx = {it.get("code"): i for i, it in enumerate(items) if it.get("code")}
        return [i2idx[c] for c in out if c in i2idx]
    # --- PUBLIC METHODS ---

    @staticmethod
    def check_capacity(start_str: str, end_str: str, **kwargs) -> Dict[str, Any]:
        """Verifica disponibilità risorse per un periodo."""
        db = get_db()
        try:
            start = ScheduleService._parse_date(start_str)
            end = ScheduleService._parse_date(end_str)
            if not start or not end: raise ValueError("Date invalide")
        except Exception:
            raise ValueError("Formato data invalido (YYYY-MM-DD)")

        region = kwargs.get("region")
        city = kwargs.get("city")
        work_code = kwargs.get("work_code")
        crew_roles = {} 

        if work_code:
            cat = ScheduleService._crew_from_catalog(db, work_code)
            if cat.get("crew_roles"): crew_roles.update(cat["crew_roles"])
            elif cat.get("min_crew") and kwargs.get("role"):
                crew_roles[str(kwargs.get("role")).lower()] = int(cat["min_crew"])
        
        if kwargs.get("crew_roles_input"):
            for k,v in kwargs.get("crew_roles_input").items():
                crew_roles[str(k).lower()] = int(v)
                
        if not crew_roles and kwargs.get("role"):
            crew_roles[str(kwargs.get("role")).lower()] = int(kwargs.get("crew_min") or 1)
            
        # Fix robustezza booleani e valori nulli
        rf_val = kwargs.get("require_foreman")
        req_foreman = True if rf_val is None else bool(rf_val)
        if req_foreman:
            crew_roles["capo cantiere"] = max(1, int(crew_roles.get("capo cantiere", 0)))

        if not crew_roles:
            raise ValueError("Specifica ruoli o work_code")

        role_pool = {r: ScheduleService._find_free_ids_for_role(db, r, region, city) for r in crew_roles}
        busy_map = ScheduleService._busy_workers_in_range(db, start, end)

        shortage_days = []
        for day in ScheduleService._daterange(start, end):
            day_ok = True
            report = []
            for role, needed in crew_roles.items():
                pool = role_pool.get(role, [])
                # Filtra workers occupati (controllo generico)
                available_count = len([x for x in pool if x not in busy_map.get("_any", set())])
                
                ok = available_count >= int(needed)
                report.append({"role": role, "free": available_count, "needed": needed, "ok": ok})
                if not ok: day_ok = False
            
            if not day_ok:
                shortage_days.append({"day": day.strftime("%Y-%m-%d"), "roles": report})

        suggestions = {"date_alternatives": []}
        if shortage_days:
            alt_start = start + timedelta(days=7)
            alt_end = end + timedelta(days=7)
            suggestions["date_alternatives"].append({
                "start": alt_start.strftime("%Y-%m-%d"),
                "end": alt_end.strftime("%Y-%m-%d"),
                "reason": "Settimana successiva (stima)"
            })

        return {
            "ok": len(shortage_days) == 0,
            "crew_roles": crew_roles,
            "shortage_days": shortage_days,
            "suggestions": suggestions
        }

    @staticmethod
    def generate_plan(db, items: list[dict], start_date: str | None = None, max_days: int = 365, project_id: str | None = None) -> dict:
        """Generate a day-based plan (works can run in parallel).

        Constraints (MVP):
          - prerequisites_all / prerequisites (AND)
          - prerequisites_any (OR-groups): for each group we choose the first prereq present in `items`
          - a worker can work on at most ONE work per day (within the plan)
          - a worker is also blocked if busy in other projects (via schedule_assignments)
          - keep the same crew for the whole duration of a work (if possible)
        """
        if not isinstance(items, list) or not items:
            return {"start_day": start_date, "plan": [], "notes": ["No items."]}

        start_dt = ScheduleService._parse_date(start_date) if start_date else ScheduleService._today()
        start_s = ScheduleService._fmt_date(start_dt)

        # Enrich works from catalog
        codes = [it.get("code") for it in items if isinstance(it, dict) and it.get("code")]
        cat_docs = {}
        if codes:
            for d in db["work_catalog"].find({"code": {"$in": codes}}, {"_id": 0}):
                cat_docs[d["code"]] = d

        work_items = []
        for it in items:
            if not isinstance(it, dict) or not it.get("code"):
                continue
            code = it["code"]
            wc = cat_docs.get(code, {})
            merged = {**wc, **it}  # user fields override catalog if present
            merged["qty"] = float(merged.get("qty") or 1.0)
            merged["unit"] = merged.get("unit") or wc.get("unit") or "pz"
            work_items.append(merged)

        # Topological order (also writes _deps_effective)
        order_idx = ScheduleService._simple_topo_order(db, work_items)
        ordered = [work_items[i] for i in order_idx]

        # Worker pools: normalized_role -> list[worker_id] (only available workers)
        worker_pools: dict[str, list[str]] = {}
        for w in db["workers"].find({"available": True}, {"_id": 1, "role": 1, "available": 1}):
            wid = str(w.get("_id"))
            role_norm = ScheduleService._norm_role(w.get("role") or "")
            if not wid or not role_norm:
                continue
            worker_pools.setdefault(role_norm, []).append(wid)

        def pool_for_role(role: str) -> list[str]:
            r_norm = ScheduleService._norm_role(role)
            if not r_norm:
                return []
            # contains matching (e.g. request "elettricista" matches stored "elettricistasenior")
            out: list[str] = []
            for k_norm, ids in worker_pools.items():
                if r_norm in k_norm:
                    out.extend(ids)
            return out or worker_pools.get(r_norm, [])

        # Busy caches
        global_busy_cache: dict[str, set[str]] = {}

        def global_busy_any(day_s: str) -> set[str]:
            if day_s not in global_busy_cache:
                dt = ScheduleService._parse_date(day_s)
                busy = ScheduleService._busy_workers_in_range(db, dt, dt)
                global_busy_cache[day_s] = set(busy.get("_any") or set())
            return global_busy_cache[day_s]

        local_busy_any: dict[str, set[str]] = {}

        def is_free(wid: str, day_s: str) -> bool:
            if wid in global_busy_any(day_s):
                return False
            if wid in local_busy_any.get(day_s, set()):
                return False
            return True

        def choose_crew(day0: str, duration: int, crew_roles: dict[str, int]) -> dict[str, list[str]] | None:
            # list of days in span
            days = []
            cur = ScheduleService._parse_date(day0)
            for _ in range(max(duration, 1)):
                days.append(ScheduleService._fmt_date(cur))
                cur = ScheduleService._add_days(cur, 1)

            assigned: dict[str, list[str]] = {}
            used = set()

            for role, needed in (crew_roles or {}).items():
                if not role or not isinstance(needed, int) or needed <= 0:
                    continue
                picked: list[str] = []
                for wid in pool_for_role(role):
                    if wid in used:
                        continue
                    if all(is_free(wid, d) for d in days):
                        picked.append(wid)
                        used.add(wid)
                        if len(picked) >= needed:
                            break
                if len(picked) < needed:
                    return None
                assigned[role] = picked

            return assigned

        def mark_busy(day0: str, duration: int, assigned: dict[str, list[str]]):
            cur = ScheduleService._parse_date(day0)
            for _ in range(max(duration, 1)):
                d = ScheduleService._fmt_date(cur)
                s = local_busy_any.setdefault(d, set())
                for ids in assigned.values():
                    for wid in ids:
                        s.add(wid)
                cur = ScheduleService._add_days(cur, 1)

        # schedule
        end_by_code: dict[str, str] = {}
        plan = []
        notes = []

        for w in ordered:
            code = w.get("code")
            deps = w.get("_deps_effective") or []
            # earliest start based on deps
            earliest = start_dt
            for dep in deps:
                dep_end = end_by_code.get(dep)
                if dep_end:
                    e = ScheduleService._add_days(ScheduleService._parse_date(dep_end), 1)
                    if e > earliest:
                        earliest = e

            dur = ScheduleService._work_duration_days(w)
            crew_roles = w.get("crew_roles") if isinstance(w.get("crew_roles"), dict) else {}
            if not crew_roles:
                pr = (w.get("primary_role") or "").strip()
                mc = int(w.get("min_crew") or 1)
                if pr:
                    crew_roles = {pr: mc}

            # search for first feasible start day (bounded)
            try_dt = earliest
            assigned = None
            for _ in range(max_days):
                day0 = ScheduleService._fmt_date(try_dt)
                assigned = choose_crew(day0, dur, crew_roles)
                if assigned is not None:
                    break
                try_dt = ScheduleService._add_days(try_dt, 1)

            if assigned is None:
                notes.append(f"No crew available for {code}")
                continue

            mark_busy(ScheduleService._fmt_date(try_dt), dur, assigned)

            start2 = ScheduleService._fmt_date(try_dt)
            end_dt = ScheduleService._add_days(try_dt, dur - 1)
            end2 = ScheduleService._fmt_date(end_dt)
            end_by_code[code] = end2

            plan.append({
                "code": code,
                "label": w.get("label") or w.get("name") or code,
                "start_day": start2,
                "end_day": end2,
                "duration_days": dur,
                "deps": deps,
                "crew_roles": crew_roles,
                "assigned_workers": assigned,
            })

        return {
            "start_day": start_s,
            "plan": plan,
            "notes": notes,
        }

    # --- SAVE/ASSIGN/UPDATE WORKS (used by projects routes) ---

    @staticmethod
    def commit_plan(project_id: str, plan_data: List[dict], site_id: str = None, assign: bool = False) -> Dict[str, Any]:
        """Salva il piano nel progetto come WorkItems.

        Chiamata da:
        - POST /api/schedule/commit_plan
        - POST /api/projects/<project_id>/schedule/assign

        Supporta formati:
        - generate_plan: code/label, start_day/end_day, duration_days, crew_roles, assigned_workers
        - legacy: work_code/work_name, start/end

        Se `assign=True`, salva anche i worker_ids nei singoli works.
        """
        db = get_db()
        try:
            # project_id -> ObjectId
            try:
                oid = ObjectId(str(project_id))
            except Exception:
                raise ValueError(f"project_id invalido: {project_id}")

            project = db["projects"].find_one({"_id": oid}, {"_id": 1})
            if not project:
                raise ValueError("Progetto non trovato")

            # If frontend calls /schedule/assign with an empty body, try to reuse an existing plan.
            if not isinstance(plan_data, list) or not plan_data:
                # Prefer a previously generated plan in meta_extra.plan, otherwise fallback to existing works
                proj_full = db["projects"].find_one(
                    {"_id": oid},
                    {"works": 1, "meta_extra": 1}
                ) or {}

                meta_extra = proj_full.get("meta_extra") or {}
                fallback_plan = meta_extra.get("plan")

                if isinstance(fallback_plan, list) and fallback_plan:
                    plan_data = fallback_plan
                else:
                    fallback_works = proj_full.get("works")
                    if isinstance(fallback_works, list) and fallback_works:
                        plan_data = fallback_works

            if not isinstance(plan_data, list) or not plan_data:
                raise ValueError("Piano vuoto: nessun item da salvare")

            works_to_save: list[dict] = []
            total_assigned = 0

            for it in plan_data:
                if not isinstance(it, dict):
                    continue

                # accetta start_day/end_day oppure start/end
                # + supporta WorkItem già salvati (start_date_planned/end_date_planned, start_date_actual/end_date_actual)
                start_s = (
                    it.get("start")
                    or it.get("start_day")
                    or it.get("start_date")
                    or it.get("from")
                    or it.get("start_date_planned")
                    or it.get("start_date_actual")
                )
                end_s = (
                    it.get("end")
                    or it.get("end_day")
                    or it.get("end_date")
                    or it.get("to")
                    or it.get("end_date_planned")
                    or it.get("end_date_actual")
                )

                start_dt = ScheduleService._parse_date(start_s)
                end_dt = ScheduleService._parse_date(end_s)
                if not start_dt or not end_dt:
                    continue

                # Work code / label
                code = it.get("work_code") or it.get("code") or it.get("work_name") or "WORK"
                label = it.get("label") or it.get("name") or it.get("title") or code

                # duration
                duration_days = it.get("duration_days") or it.get("duration") or 1
                try:
                    duration_days = int(duration_days)
                except Exception:
                    duration_days = 1
                duration_days = max(1, duration_days)
                duration_hours = float(duration_days) * 8.0

                # crew size
                crew_roles = it.get("crew_roles") if isinstance(it.get("crew_roles"), dict) else {}
                num_workers = sum(int(v) for v in crew_roles.values()) if crew_roles else None

                # assigned workers mapping
                assigned_map = it.get("assigned") or it.get("assigned_workers") or it.get("assignedWorkers")
                if assigned_map is None:
                    assigned_map = it.get("assigned_workers")

                worker_ids: list[str] = []
                if assign and isinstance(assigned_map, dict):
                    for _, ids in assigned_map.items():
                        if isinstance(ids, list):
                            worker_ids.extend([str(x) for x in ids if x])
                    # de-dup preserving order
                    worker_ids = list(dict.fromkeys(worker_ids))
                    total_assigned += len(worker_ids)

                if num_workers is None:
                    num_workers = float(len(worker_ids) or 1)
                else:
                    num_workers = float(num_workers or 1)

                # WorkItem (ProjectDoc è strict=False, quindi possiamo includere work_code)
                work_item = {
                    "work_name": str(label),
                    "status": "planned",
                    # Mongo/PyMongo can store datetime, but not datetime.date
                    "start_date_planned": start_dt,
                    "end_date_planned": end_dt,
                    "duration_estimated_hours": duration_hours,
                    "number_of_workers": num_workers,
                    "workers": worker_ids,
                    "work_code": str(code),
                }
                works_to_save.append(work_item)

            if not works_to_save:
                raise ValueError("Nessun work pianificato da salvare (controlla start/end o start_day/end_day)")

            # overwrite works
            res = db["projects"].update_one({"_id": oid}, {"$set": {"works": works_to_save}})
            if res.matched_count == 0:
                raise ValueError("Progetto non trovato")

            # If we are assigning workers, also ensure a foreman (capo cantiere) is set for the project.
            if assign:
                try:
                    capo_norm = ScheduleService._norm_role("capo cantiere")

                    # Prefer a capo cantiere among the roles present in assigned_map
                    foreman_id: str | None = None
                    if isinstance(assigned_map, dict):
                        for role_k, ids in assigned_map.items():
                            if ScheduleService._norm_role(role_k) == capo_norm and isinstance(ids, list) and ids:
                                foreman_id = str(ids[0])
                                break

                    # Fallback: pick any available capo cantiere
                    if not foreman_id:
                        w = db["workers"].find_one(
                            {"available": True, "role": {"$regex": ScheduleService._role_regex("capo cantiere"), "$options": "i"}},
                            {"_id": 1, "role": 1}
                        )
                        if w and ScheduleService._norm_role(w.get("role") or "") == capo_norm:
                            foreman_id = str(w.get("_id"))

                    if foreman_id:
                        # Write multiple keys for backward/forward compatibility
                        db["projects"].update_one(
                            {"_id": oid},
                            {"$set": {
                                "meta_extra.foreman_id": foreman_id,
                                "meta_extra.capo_cantiere_id": foreman_id,
                                "foreman_id": foreman_id,
                                "capo_cantiere_id": foreman_id,
                            }}
                        )
                except Exception:
                    # Never fail the commit because of foreman persistence
                    print("FOREMAN ASSIGN ERROR:\n" + traceback.format_exc(), flush=True)

            return {
                "ok": True,
                "project_id": str(project_id),
                "works_saved": len(works_to_save),
                "workers_assigned": total_assigned if assign else 0,
                "overwritten": True,
            }
        except Exception:
            print("SCHEDULE SERVICE commit_plan ERROR:\n" + traceback.format_exc(), flush=True)
            raise

    @staticmethod
    def assign_worker_to_work(project_id: str, work_name: str, worker_id: str) -> Dict[str, Any]:
        """Assegna un worker a un work specifico (addToSet)."""
        if not project_id or not work_name or not worker_id:
            raise ValueError("project_id, work_name e worker_id sono richiesti")

        db = get_db()
        try:
            oid = ObjectId(str(project_id))
        except Exception:
            raise ValueError(f"project_id invalido: {project_id}")

        try:
            wid_oid = ObjectId(str(worker_id))
        except Exception:
            raise ValueError(f"worker_id invalido: {worker_id}")

        worker = db["workers"].find_one({"_id": wid_oid}, {"_id": 1, "name": 1})
        if not worker:
            raise ValueError("Worker non trovato")

        result = db["projects"].update_one(
            {"_id": oid, "works.work_name": work_name},
            {"$addToSet": {"works.$.workers": str(worker_id)}},
        )

        if result.matched_count == 0:
            raise ValueError("Progetto o work non trovato")

        return {
            "success": True,
            "message": f"Worker {worker.get('name', str(worker_id))} assegnato a {work_name}",
            "already_assigned": result.modified_count == 0,
        }

    @staticmethod
    def unassign_worker_from_work(project_id: str, work_name: str, worker_id: str) -> Dict[str, Any]:
        """Rimuove un worker da un work e pulisce eventuale booking del worker."""
        if not project_id or not work_name or not worker_id:
            raise ValueError("project_id, work_name e worker_id sono richiesti")

        db = get_db()
        try:
            oid = ObjectId(str(project_id))
        except Exception:
            raise ValueError(f"project_id invalido: {project_id}")

        # 1) pull dal work
        result = db["projects"].update_one(
            {"_id": oid, "works.work_name": work_name},
            {"$pull": {"works.$.workers": str(worker_id)}},
        )

        if result.matched_count == 0:
            raise ValueError("Progetto o work non trovato")

        # 2) rimuovi anche assignment in meta_extra (se presente)
        db["projects"].update_one(
            {"_id": oid},
            {"$pull": {"meta_extra.assignments": {"work_name": work_name, "worker_id": str(worker_id)}}},
        )

        # 3) rimuovi booking dal worker (se esiste)
        try:
            db["workers"].update_one(
                {"_id": ObjectId(str(worker_id))},
                {"$pull": {"bookings": {"project_id": str(project_id), "work_name": work_name}}},
            )
        except Exception:
            pass

        return {
            "success": True,
            "message": f"Worker rimosso da {work_name}",
            "was_assigned": result.modified_count > 0,
        }

    @staticmethod
    def update_work_status(project_id: str, work_name: str, status: str) -> Dict[str, Any]:
        """Aggiorna lo status di un work (planned/in_progress/completed/blocked/cancelled)."""
        if not project_id or not work_name or not status:
            raise ValueError("project_id, work_name e status sono richiesti")

        valid_statuses = {"planned", "in_progress", "completed", "blocked", "cancelled"}
        if status not in valid_statuses:
            raise ValueError(f"Status invalido. Valori ammessi: {', '.join(sorted(valid_statuses))}")

        db = get_db()
        try:
            oid = ObjectId(str(project_id))
        except Exception:
            raise ValueError(f"project_id invalido: {project_id}")

        update_data: dict[str, Any] = {"works.$.status": status}
        now_dt = datetime.utcnow()

        if status == "in_progress":
            update_data["works.$.start_date_actual"] = now_dt
        elif status == "completed":
            update_data["works.$.end_date_actual"] = now_dt

        result = db["projects"].update_one(
            {"_id": oid, "works.work_name": work_name},
            {"$set": update_data},
        )

        if result.matched_count == 0:
            raise ValueError("Progetto o work non trovato")

        return {
            "success": True,
            "message": f"Status di '{work_name}' aggiornato a '{status}'",
            "status": status,
        }

    @staticmethod
    def get_work_details(project_id: str, work_name: str) -> Dict[str, Any]:
        """Recupera i dettagli di un work specifico."""
        db = get_db()
        try:
            oid = ObjectId(str(project_id))
        except Exception:
            raise ValueError(f"project_id invalido: {project_id}")

        project = db["projects"].find_one({"_id": oid}, {"works": 1})
        if not project:
            raise ValueError("Progetto non trovato")

        for work in project.get("works", []) or []:
            if work.get("work_name") == work_name:
                return {"found": True, "work": work}

        return {"found": False}

    @staticmethod
    def list_project_workers(project_id: str) -> Dict[str, Any]:
        """Lista tutti i workers assegnati (unici) nel progetto."""
        db = get_db()
        try:
            oid = ObjectId(str(project_id))
        except Exception:
            raise ValueError(f"project_id invalido: {project_id}")

        project = db["projects"].find_one({"_id": oid}, {"works": 1})
        if not project:
            raise ValueError("Progetto non trovato")

        worker_ids: set[str] = set()
        for work in project.get("works", []) or []:
            for wid in (work.get("workers") or []):
                if wid:
                    worker_ids.add(str(wid))

        ids_list = sorted(worker_ids)

        workers_details: list[dict] = []
        if ids_list:
            try:
                oid_list = [ObjectId(x) for x in ids_list]
                cur = db["workers"].find({"_id": {"$in": oid_list}}, {"_id": 1, "name": 1, "role": 1, "available": 1})
                workers_details = [
                    {
                        "id": str(w.get("_id")),
                        "name": w.get("name"),
                        "role": w.get("role"),
                        "available": w.get("available"),
                    }
                    for w in cur
                ]
            except Exception:
                workers_details = []

        return {
            "project_id": str(project_id),
            "total_workers": len(ids_list),
            "worker_ids": ids_list,
            "workers": workers_details,
        }