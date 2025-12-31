# services/work_service.py
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from mongoengine.connection import get_db

class WorkService:
    """Gestisce la logica dei lavori: aggiunta, pianificazione, assegnazione."""
    
    ALLOWED_ASSIGN_STATES = {"Confermato", "In corso", "Attivo", "Active"}

    @staticmethod
    def _load_project_dict(pid: str):
        db = get_db()
        # Cerca sia per id stringa custom (P-XXX) che ObjectId
        return db["projects"].find_one({"id": pid}) or db["projects"].find_one({"_id": pid})

    @staticmethod
    def _save_works(proj_id, works: list):
        db = get_db()
        db["projects"].update_one({"$or": [{"id": proj_id}, {"_id": proj_id}]}, {"$set": {"works": works}})

    @staticmethod
    def add_work_item(pid: str, code: str, qty: float, notes: str = None) -> Dict[str, Any]:
        """Aggiunge un singolo lavoro al progetto."""
        db = get_db()
        proj = WorkService._load_project_dict(pid)
        if not proj: return {"ok": False, "error": "Progetto non trovato"}

        code = (code or "").strip().upper()
        if not code or qty <= 0: return {"ok": False, "error": "Dati invalidi"}

        cat = db["work_catalog"].find_one({"code": code})
        if not cat: return {"ok": False, "error": f"Codice {code} non trovato in catalogo"}

        item = {
            "work_code": code,
            "work_name": cat.get("name"),
            "qty": qty,
            "unit": cat.get("unit"),
            "primary_role": cat.get("primary_role"),
            "roles_allowed": cat.get("roles_allowed") or [],
            "status": "planned",
            "crew_size_planned": cat.get("min_crew", 1),
            "hours_estimated": None,
            "start_date_planned": None,
            "end_date_planned": None,
            "notes": (notes or "").strip() or None,
        }
        
        works = list(proj.get("works") or [])
        works.append(item)
        WorkService._save_works(pid, works)
        return {"ok": True, "added": item, "total": len(works)}

    @staticmethod
    def plan_project(pid: str) -> Dict[str, Any]:
        """Ricalcola le date pianificate (Plan)."""
        db = get_db()
        proj = WorkService._load_project_dict(pid)
        if not proj: return {"ok": False, "error": "Progetto non trovato"}
        
        works = list(proj.get("works") or [])
        if not works: return {"ok": False, "error": "Nessun lavoro da pianificare"}

        start0_str = proj.get("start_date_estimated") \
            or ((proj.get("meta_extra") or {}).get("estimate") or {}).get("start") \
            or datetime.utcnow().date().isoformat()
        
        # Carica catalogo
        codes = list({ w.get("work_code") for w in works if w.get("work_code") })
        cat_docs = list(db["work_catalog"].find({"code": {"$in": codes}}))
        cat = { c["code"]: c for c in cat_docs }
        
        # Topological Sort (semplificato)
        g = { w["work_code"]: set(cat.get(w["work_code"], {}).get("prerequisites", [])) for w in works if w.get("work_code") }
        ordered = []
        seen = set()
        def visit(code):
            if code in seen: return
            for dep in g.get(code, []):
                if dep in cat: visit(dep)
            seen.add(code); ordered.append(code)
        
        for w in works:
            if w.get("work_code"): visit(w["work_code"])
            
        by_code = { w["work_code"]: w for w in works if w.get("work_code") }
        
        # Calcolo date
        try:
            cursor = datetime.strptime(start0_str, "%Y-%m-%d")
        except ValueError:
            cursor = datetime.utcnow()

        planned = []
        
        for code in ordered:
            w = by_code.get(code)
            c = cat.get(code)
            if not (w and c): continue
            
            qty = float(w.get("qty") or 0)
            crew = int(w.get("crew_size_planned") or c.get("min_crew", 1))
            prod = float(c.get("productivity_per_worker_per_hour") or 1.0)
            
            hours = 0 if qty <= 0 else qty / (prod * max(1, crew))
            days = 0 if hours == 0 else max(1, int((hours/8)+0.999))
            
            start_d = cursor
            end_d = cursor + timedelta(days=max(0, days-1))
            cursor = end_d + timedelta(days=1)
            
            w.update({
                "primary_role": w.get("primary_role") or c.get("primary_role"),
                "roles_allowed": w.get("roles_allowed") or c.get("roles_allowed", []),
                "hours_estimated": hours,
                "crew_size_planned": crew,
                "start_date_planned": start_d.strftime("%Y-%m-%d"),
                "end_date_planned": end_d.strftime("%Y-%m-%d")
            })
            planned.append(w)
            
        WorkService._save_works(pid, planned)
        return {"ok": True, "items": planned}

    @staticmethod
    def auto_assign(pid: str) -> Dict[str, Any]:
        """Assegna operai ai lavori pianificati."""
        db = get_db()
        proj = WorkService._load_project_dict(pid)
        if not proj: return {"ok": False, "error": "Progetto non trovato"}
        
        status = str(proj.get("status") or "").strip()
        status_norm = "Attivo" if status == "Active" else status
        if status_norm not in WorkService.ALLOWED_ASSIGN_STATES:
             return {"ok": False, "error": f"Stato {status} non valido per assegnazione"}
             
        works = [w for w in (proj.get("works") or []) if w.get("start_date_planned")]
        works.sort(key=lambda x: (x.get("start_date_planned"), x.get("end_date_planned")))
        
        workers = list(db["workers"].find({}))
        by_role = {}
        for w in workers:
            by_role.setdefault((w.get("role") or "").strip().lower(), []).append(w)
            
        assignments = []
        
        def _overlaps(s1, e1, s2, e2):
            return not (e1 < s2 or e2 < s1)
            
        def _is_free(w, s_str, e_str):
            try:
                s, e = datetime.strptime(s_str, "%Y-%m-%d"), datetime.strptime(e_str, "%Y-%m-%d")
            except ValueError:
                return False
                
            for b in w.get("bookings", []):
                try:
                    bs, be = datetime.strptime(b["from"], "%Y-%m-%d"), datetime.strptime(b["to"], "%Y-%m-%d")
                    if _overlaps(s, e, bs, be): return False
                except: continue
            return True

        for w in works:
            need = int(w.get("crew_size_planned") or 1)
            roles = [r.strip().lower() for r in (w.get("roles_allowed") or [])]
            primary = (w.get("primary_role") or "").strip().lower()
            if primary and primary not in roles: roles.insert(0, primary)
            if not roles: roles = ["operaio edile"]
            
            taken = 0
            start, end = w["start_date_planned"], w["end_date_planned"]
            
            for r in roles:
                pool = sorted(by_role.get(r, []), key=lambda x: len(x.get("bookings") or []))
                for cand in pool:
                    if taken >= need: break
                    if _is_free(cand, start, end):
                        # Assegna (Aggiorna DB worker)
                        booking = {"project_id": pid, "work_name": w.get("work_name"), "from": start, "to": end}
                        db["workers"].update_one({"_id": cand["_id"]}, {"$push": {"bookings": booking}})
                        
                        assignments.append({
                            "worker_id": str(cand.get("id") or cand.get("_id")),
                            "worker_name": cand.get("name"),
                            "role": r,
                            "work_name": w.get("work_name"),
                            "start": start, "end": end
                        })
                        taken += 1
                if taken >= need: break
        
        # Salva su progetto
        me = proj.get("meta_extra") or {}
        old = me.get("assignments") or []
        me["assignments"] = old + assignments
        db["projects"].update_one({"$or": [{"id": pid}, {"_id": pid}]}, {"$set": {"meta_extra": me}})
        
        return {"ok": True, "assigned": len(assignments), "items": assignments}