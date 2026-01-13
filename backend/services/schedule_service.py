# services/schedule_service.py
from datetime import datetime, timedelta
from collections import defaultdict, deque
from uuid import uuid4
import math
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
        filt = {"available": True, "role": {"$regex": f"^{role}$", "$options": "i"}}
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

        # Worker pools: role -> list[worker_id]
        worker_pools: dict[str, list[str]] = {}
        for w in db["workers"].find({}, {"_id": 1, "role": 1}):
            wid = str(w.get("_id"))
            role = (w.get("role") or "").strip().lower()
            if not wid or not role:
                continue
            worker_pools.setdefault(role, []).append(wid)

        def pool_for_role(role: str) -> list[str]:
            r = (role or "").strip().lower()
            if not r:
                return []
            # simple contains matching (e.g. "elettricista senior" still counts)
            out = []
            for k, ids in worker_pools.items():
                if r in k:
                    out.extend(ids)
            return out or worker_pools.get(r, [])

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
    @staticmethod
    def commit_plan(project_id: str, plan_data: List[dict], site_id: str = None, assign: bool = False) -> Dict[str, Any]:
        """
        Salva il piano nel progetto come WorkItems.
        
        Args:
            project_id: ObjectId string del progetto
            plan_data: Output di generate_plan
            site_id: Opzionale, non usato (legacy)
            assign: Se True, popola workers array con IDs assegnati
        
        Returns:
            Dict con statistiche operazione
        """
        db = get_db()
        
        # ✅ Converti project_id in ObjectId
        try:
            oid = ObjectId(project_id)
        except Exception:
            raise ValueError(f"project_id invalido: {project_id}")
        
        # Verifica che il progetto esista
        project = db["projects"].find_one({"_id": oid}, {"_id": 1})
        if not project:
            raise ValueError(f"Progetto {project_id} non trovato")
        
        # ✅ Converti plan_data in formato WorkItem
        works_to_save = []
        total_assigned = 0
        
        for it in plan_data:
            if it.get("status") != "planned": 
                continue
            
            # Parse date
            start_dt = ScheduleService._parse_date(it.get("start"))
            end_dt = ScheduleService._parse_date(it.get("end"))
            
            if not start_dt or not end_dt:
                continue
            
            # Calcola ore stimate (duration_days * 8 ore)
            duration_days = it.get("duration_days", 1)
            duration_hours = duration_days * 8.0
            
            # Calcola numero workers (somma crew_roles)
            crew_roles = it.get("crew_roles", {})
            num_workers = sum(crew_roles.values()) if crew_roles else 1
            
            # ✅ Raccogli worker IDs se assign=True
            worker_ids = []
            if assign and it.get("assigned"):
                # assigned = {"muratore": ["id1", "id2"], "elettricista": ["id3"]}
                for role, ids in it["assigned"].items():
                    worker_ids.extend(ids)
                # Rimuovi duplicati mantenendo ordine
                worker_ids = list(dict.fromkeys(worker_ids))
                total_assigned += len(worker_ids)
            
            # ✅ Crea WorkItem secondo il modello
            work_item = {
                "work_name": it.get("work_code"),  # work_code diventa work_name
                "status": "planned",
                "start_date_planned": start_dt,
                "end_date_planned": end_dt,
                "duration_estimated_hours": duration_hours,
                "number_of_workers": float(num_workers),
                "workers": worker_ids  # Array di worker ObjectId strings
            }
            
            works_to_save.append(work_item)
        
        if not works_to_save:
            raise ValueError("Nessun work pianificato da salvare")
        
        # ✅ Salva in works usando $push
        res = db["projects"].update_one(
            {"_id": oid},
            {"$push": {"works": {"$each": works_to_save}}}
        )
        
        if res.matched_count == 0:
            raise ValueError(f"Progetto {project_id} non trovato durante update")
        
        return {
            "ok": True,
            "project_id": project_id,
            "works_added": len(works_to_save),
            "workers_assigned": total_assigned if assign else 0
        }
        
        # ============================================

    @staticmethod
    def assign_worker_to_work(project_id: str, work_name: str, worker_id: str) -> Dict[str, Any]:
        """
        Assegna un worker a un work specifico.
        
        Args:
            project_id: ObjectId string del progetto
            work_name: Nome del work (work_name field)
            worker_id: ObjectId string del worker
            
        Returns:
            Dict con risultato operazione
            
        Raises:
            ValueError: Se parametri invalidi o progetto/work non trovato
        """
        from bson import ObjectId
        from mongoengine.connection import get_db
        
        # Validazione input
        if not work_name or not worker_id:
            raise ValueError("work_name e worker_id sono richiesti")
        
        # Converti project_id in ObjectId
        try:
            oid = ObjectId(project_id)
        except Exception:
            raise ValueError(f"project_id invalido: {project_id}")
        
        # Verifica che worker_id sia valido ObjectId
        try:
            ObjectId(worker_id)
        except Exception:
            raise ValueError(f"worker_id invalido: {worker_id}")
        
        db = get_db()
        
        # Verifica che il worker esista ed è disponibile
        worker = db["workers"].find_one(
            {"_id": ObjectId(worker_id)},
            {"_id": 1, "available": 1, "name": 1}
        )
        
        if not worker:
            raise ValueError(f"Worker {worker_id} non trovato")
        
        # Aggiungi worker all'array (addToSet evita duplicati)
        result = db["projects"].update_one(
            {
                "_id": oid,
                "works.work_name": work_name
            },
            {
                "$addToSet": {"works.$.workers": worker_id}
            }
        )
        
        if result.matched_count == 0:
            raise ValueError(f"Progetto {project_id} o work '{work_name}' non trovato")
        
        if result.modified_count == 0:
            # Worker già assegnato (addToSet non ha modificato)
            return {
                "success": True,
                "message": "Worker già assegnato a questo work",
                "already_assigned": True
            }
        
        return {
            "success": True,
            "message": f"Worker {worker.get('name', worker_id)} assegnato a {work_name}",
            "already_assigned": False
        }

    @staticmethod
    def unassign_worker_from_work(project_id: str, work_name: str, worker_id: str) -> Dict[str, Any]:
        """
        Rimuove un worker da un work specifico.
        
        Args:
            project_id: ObjectId string del progetto
            work_name: Nome del work
            worker_id: ObjectId string del worker
            
        Returns:
            Dict con risultato operazione
            
        Raises:
            ValueError: Se parametri invalidi o progetto/work non trovato
        """
        from bson import ObjectId
        from mongoengine.connection import get_db
        
        # Validazione input
        if not work_name or not worker_id:
            raise ValueError("work_name e worker_id sono richiesti")
        
        # Converti project_id in ObjectId
        try:
            oid = ObjectId(project_id)
        except Exception:
            raise ValueError(f"project_id invalido: {project_id}")
        
        db = get_db()
        
        # Rimuovi worker dall'array
        result = db["projects"].update_one(
            {
                "_id": oid,
                "works.work_name": work_name
            },
            {
                "$pull": {"works.$.workers": worker_id}
            }
        )
        
        if result.matched_count == 0:
            raise ValueError(f"Progetto {project_id} o work '{work_name}' non trovato")
        
        if result.modified_count == 0:
            return {
                "success": True,
                "message": "Worker non era assegnato a questo work",
                "was_assigned": False
            }
        
        return {
            "success": True,
            "message": f"Worker rimosso da {work_name}",
            "was_assigned": True
        }

    @staticmethod
    def update_work_status(project_id: str, work_name: str, status: str) -> Dict[str, Any]:
        """
        Aggiorna lo status di un work.
        
        Args:
            project_id: ObjectId string del progetto
            work_name: Nome del work
            status: Nuovo status ("planned", "in_progress", "completed", "blocked")
            
        Returns:
            Dict con risultato operazione
            
        Raises:
            ValueError: Se parametri invalidi o status non valido
        """
        from bson import ObjectId
        from mongoengine.connection import get_db
        from datetime import datetime
        
        # Validazione input
        if not work_name or not status:
            raise ValueError("work_name e status sono richiesti")
        
        # Valida status
        valid_statuses = ["planned", "in_progress", "completed", "blocked", "cancelled"]
        if status not in valid_statuses:
            raise ValueError(f"Status invalido. Valori ammessi: {', '.join(valid_statuses)}")
        
        # Converti project_id in ObjectId
        try:
            oid = ObjectId(project_id)
        except Exception:
            raise ValueError(f"project_id invalido: {project_id}")
        
        db = get_db()
        
        # Prepara update
        update_data = {"works.$.status": status}
        
        # Gestione date automatiche
        if status == "in_progress":
            # Quando inizia, setta start_date_actual se non già presente
            update_data["works.$.start_date_actual"] = datetime.now()
        
        elif status == "completed":
            # Quando completa, setta end_date_actual
            update_data["works.$.end_date_actual"] = datetime.now()
        
        # Esegui update
        result = db["projects"].update_one(
            {
                "_id": oid,
                "works.work_name": work_name
            },
            {"$set": update_data}
        )
        
        if result.matched_count == 0:
            raise ValueError(f"Progetto {project_id} o work '{work_name}' non trovato")
        
        return {
            "success": True,
            "message": f"Status di '{work_name}' aggiornato a '{status}'",
            "status": status
        }

    @staticmethod
    def get_work_details(project_id: str, work_name: str) -> Dict[str, Any]:
        """
        Recupera i dettagli di un work specifico.
        
        Args:
            project_id: ObjectId string del progetto
            work_name: Nome del work
            
        Returns:
            Dict con dettagli del work o None se non trovato
        """
        from bson import ObjectId
        from mongoengine.connection import get_db
        
        try:
            oid = ObjectId(project_id)
        except Exception:
            raise ValueError(f"project_id invalido: {project_id}")
        
        db = get_db()
        
        project = db["projects"].find_one(
            {"_id": oid},
            {"works": 1}
        )
        
        if not project:
            raise ValueError(f"Progetto {project_id} non trovato")
        
        # Cerca il work specifico
        for work in project.get("works", []):
            if work.get("work_name") == work_name:
                return {
                    "found": True,
                    "work": work
                }
        
        return {"found": False}

    @staticmethod
    def list_project_workers(project_id: str) -> Dict[str, Any]:
        """
        Lista tutti i workers assegnati a qualsiasi work del progetto.
        
        Args:
            project_id: ObjectId string del progetto
            
        Returns:
            Dict con lista worker IDs unici e dettagli
        """
        from bson import ObjectId
        from mongoengine.connection import get_db
        
        try:
            oid = ObjectId(project_id)
        except Exception:
            raise ValueError(f"project_id invalido: {project_id}")
        
        db = get_db()
        
        project = db["projects"].find_one(
            {"_id": oid},
            {"works": 1}
        )
        
        if not project:
            raise ValueError(f"Progetto {project_id} non trovato")
        
        # Raccogli tutti i worker IDs (set per unicità)
        worker_ids = set()
        for work in project.get("works", []):
            worker_ids.update(work.get("workers", []))
        
        worker_ids = list(worker_ids)
        
        # Opzionale: recupera dettagli workers
        workers_details = []
        if worker_ids:
            workers = db["workers"].find(
                {"_id": {"$in": [ObjectId(wid) for wid in worker_ids]}},
                {"_id": 1, "name": 1, "role": 1, "available": 1}
            )
            workers_details = [
                {
                    "id": str(w["_id"]),
                    "name": w.get("name"),
                    "role": w.get("role"),
                    "available": w.get("available")
                }
                for w in workers
            ]
        
        return {
            "project_id": project_id,
            "total_workers": len(worker_ids),
            "worker_ids": worker_ids,
            "workers": workers_details
        }