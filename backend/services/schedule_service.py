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
    from utils.telemetry import log_assignment_attempt
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
    def _simple_topo_order(db, items: List[dict]) -> List[int]:
        """Ordina lavorazioni per dipendenze (prerequisites)."""
        code_map = defaultdict(list)
        for i, it in enumerate(items):
            if it.get("work_code"): code_map[it["work_code"].upper()].append(i)
            
        N = len(items)
        indeg = [0]*N
        adj = [[] for _ in range(N)]
        
        for i, it in enumerate(items):
            wc = (it.get("work_code") or "").strip()
            if not wc: continue
            
            cat = db["work_catalog"].find_one({"code": {"$regex": f"^{wc}$", "$options": "i"}})
            pres = (cat or {}).get("prerequisites", [])
            
            for p in pres:
                for j in code_map.get(p.upper(), []):
                    adj[j].append(i)
                    indeg[i] += 1
                    
        q = deque([i for i in range(N) if indeg[i] == 0])
        out = []
        while q:
            u = q.popleft()
            out.append(u)
            for v in adj[u]:
                indeg[v] -= 1
                if indeg[v] == 0: q.append(v)
                
        return out if len(out) == N else list(range(N))

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
    def generate_plan(items: List[dict], start_date: str, **kwargs) -> Dict[str, Any]:
        """Genera piano (Auto-Plan)."""
        db = get_db()
        try:
            cur_day = ScheduleService._parse_date(start_date)
            if not cur_day: raise ValueError
        except:
            raise ValueError("Start date invalida")

        region = kwargs.get("region")
        city = kwargs.get("city")
        
        # FIX: Gestione robusta dei valori None passati esplicitamente
        daily_hours = int(kwargs.get("daily_hours") or 8)
        
        rf_val = kwargs.get("require_foreman")
        req_foreman = True if rf_val is None else bool(rf_val)

        # 1. Arricchimento dati
        enriched = []
        for it in items:
            wc = (it.get("work_code") or "").strip()
            if not wc: continue
            
            crew = ScheduleService._crew_from_catalog(db, wc)
            roles = crew.get("crew_roles") or {}
            prod, unit = ScheduleService._get_productivity(db, wc)
            
            enriched.append({
                "work_code": wc,
                "qty": float(it.get("qty") or 0),
                "unit": it.get("unit") or unit,
                "crew_roles": roles,
                "prod": prod
            })

        # 2. Ordinamento
        order_idxs = ScheduleService._simple_topo_order(db, enriched)
        
        # 3. Pianificazione
        plan = []
        warnings = []
        local_busy = defaultdict(lambda: defaultdict(set))

        for idx in order_idxs:
            it = enriched[idx]
            roles = dict(it["crew_roles"])
            if req_foreman: 
                roles["capo cantiere"] = max(1, roles.get("capo cantiere", 0))
            
            crew_size = sum(v for k,v in roles.items() if k != "capo cantiere") or 1
            duration = ScheduleService._estimate_duration_days(it["qty"], it["prod"], crew_size, daily_hours)
            
            found_start = None
            assigned_map = defaultdict(list)
            
            check_day = cur_day
            attempts = 0
            while attempts < 365:
                slot_valid = True
                temp_assigned = defaultdict(list)
                
                for d_off in range(duration):
                    day_dt = check_day + timedelta(days=d_off)
                    day_str = day_dt.strftime("%Y-%m-%d")
                    
                    for role, needed in roles.items():
                        candidates = ScheduleService._find_free_ids_for_role(db, role, region, city)
                        
                        global_busy_map = ScheduleService._busy_workers_in_range(db, day_dt, day_dt)
                        global_busy = global_busy_map.get("_any", set())
                        local_busy_set = local_busy[day_str][role]
                        
                        free = [x for x in candidates if x not in global_busy and x not in local_busy_set]
                        
                        if len(free) < needed:
                            slot_valid = False
                            break
                        
                        temp_assigned[role].extend(free[:needed])
                        
                    if not slot_valid: break
                
                if slot_valid:
                    found_start = check_day
                    for d_off in range(duration):
                        day_str = (found_start + timedelta(days=d_off)).strftime("%Y-%m-%d")
                        for r, ids in roles.items():
                            unique_ids = list(set(temp_assigned[r]))[:roles[r]]
                            for wid in unique_ids:
                                local_busy[day_str][r].add(wid)
                                if wid not in assigned_map[r]: assigned_map[r].append(wid)
                    break
                
                check_day += timedelta(days=1)
                attempts += 1
            
            if found_start:
                end_dt = found_start + timedelta(days=duration-1)
                plan.append({
                    "work_code": it["work_code"],
                    "qty": it["qty"],
                    "unit": it["unit"],
                    "status": "planned",
                    "start": found_start.strftime("%Y-%m-%d"),
                    "end": end_dt.strftime("%Y-%m-%d"),
                    "duration_days": duration,
                    "crew_roles": roles,
                    "assigned": dict(assigned_map)
                })
                cur_day = end_dt + timedelta(days=1)
            else:
                warnings.append(f"Impossibile pianificare {it['work_code']} (capacità insufficiente)")
                plan.append({
                    "work_code": it["work_code"],
                    "status": "unscheduled",
                    "reason": "no_capacity"
                })

        return {"plan": plan, "warnings": warnings}

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