# services/workers_service.py
"""
Business logic per gestione operai.
Unisce CRUD completo + audit logging + permission checks.
"""
from typing import Optional, List, Dict, Any
from models_mongo.worker import WorkerDoc
from utils.audit import audit_log
from utils.normalization import normalize_role, generate_role_aliases
from utils.intent_router import ROLE_ALIASES

class PermissionError(Exception):
    pass


class WorkerService:
    """Service completo per operazioni sui workers."""
    
    @staticmethod
    def _require_admin(user: Any):
        """Check admin permission (optional)."""
        if user and hasattr(user, "is_admin") and not user.is_admin:
            raise PermissionError("Operazione richiede permessi admin")
    
    @staticmethod
    def create_worker(data: Dict[str, Any], user: Any = None) -> WorkerDoc:
        """
        Crea nuovo operaio con validazione + audit.
        
        Args:
            data: Dict con campi worker
            user: User object (optional, per audit + permission check)
            
        Returns:
            WorkerDoc creato
            
        Raises:
            ValueError: Validazione fallita
            PermissionError: Permessi insufficienti
        """
        # Permission check (se user fornito)
        if user:
            WorkerService._require_admin(user)
        
        # Validazione base
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("name è obbligatorio")
        
        role = (data.get("role") or "operaio").strip()
        
        # Role normalization
        role_canonical = normalize_role(role, ROLE_ALIASES)
        
        # ✅ RIMOSSO generate_worker_id() - MongoDB genera ObjectId automaticamente
        
        # Normalizza hourly_rate
        hourly_rate = data.get("hourly_rate")
        try:
            hourly_rate = float(hourly_rate) if hourly_rate is not None else None
        except (ValueError, TypeError):
            hourly_rate = None
        
        # Normalizza liste (skills, certifications)
        def _as_list(v):
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            if isinstance(v, str):
                return [s.strip() for s in v.split(',') if s.strip()]
            return []
        
        skills = _as_list(data.get("skills"))
        certs = _as_list(data.get("certifications"))
        
        # Genera aliases per ricerca
        aliases = sorted(generate_role_aliases(role_canonical, ROLE_ALIASES))
        
        # Crea documento (senza settare 'id' - MongoDB lo genera automaticamente)
        worker = WorkerDoc(
            # id=worker_id,  # ← RIMOSSO! MongoDB genera _id automaticamente
            name=name,
            role=role_canonical,
            aliases=aliases,
            available=bool(data.get("available", True)),
            home_city=data.get("home_city"),
            hourly_rate=hourly_rate,
            skills=skills if skills else None,
            certifications=certs if certs else None,
        )
        
        worker.save()
        
        # Audit log
        if user:
            audit_log("create_worker", getattr(user, "id", None), {
                "worker_id": str(worker.id),  # ← Converti ObjectId a string
                "role": worker.role
            })
        
        return worker
    
    @staticmethod
    def get_worker(worker_id: str) -> Optional[WorkerDoc]:
        """Recupera operaio per ID (ora accetta ObjectId string)."""
        return WorkerDoc.objects(id=worker_id).first()
    
    @staticmethod
    def list_workers(filters: Optional[Dict[str, Any]] = None) -> List[WorkerDoc]:
        """
        Lista operai con filtri opzionali.
        
        Args:
            filters: Dict con filtri (role, available, city, etc.)
            
        Returns:
            List[WorkerDoc]
        """
        query = WorkerDoc.objects
        
        if filters:
            if "role" in filters:
                query = query.filter(role__iexact=filters["role"])
            
            if "available" in filters:
                query = query.filter(available=bool(filters["available"]))
            
            if "city" in filters:
                query = query.filter(home_city__icontains=filters["city"])
        
        return list(query)
    
    @staticmethod
    def update_worker(worker_id: str, data: Dict[str, Any], user: Any = None) -> Optional[WorkerDoc]:
        """
        Aggiorna campi operaio (patch) con audit.
        
        Args:
            worker_id: ID operaio (ObjectId string)
            data: Dict con campi da aggiornare
            user: User object (optional)
            
        Returns:
            WorkerDoc aggiornato o None se non trovato
        """
        worker = WorkerDoc.objects(id=worker_id).first()
        if not worker:
            return None
        
        # Campi safe da aggiornare
        if "name" in data:
            worker.name = data["name"]
        
        if "role" in data:
            role_canonical = normalize_role(data["role"], ROLE_ALIASES)
            worker.role = role_canonical
            worker.aliases = sorted(generate_role_aliases(role_canonical, ROLE_ALIASES))
        
        if "available" in data:
            worker.available = bool(data["available"])
        
        if "home_city" in data:
            worker.home_city = data["home_city"]
        
        if "hourly_rate" in data:
            try:
                worker.hourly_rate = float(data["hourly_rate"]) if data["hourly_rate"] is not None else None
            except (ValueError, TypeError):
                pass
        
        if "skills" in data:
            def _as_list(v):
                if isinstance(v, list):
                    return [str(x).strip() for x in v if str(x).strip()]
                if isinstance(v, str):
                    return [s.strip() for s in v.split(',') if s.strip()]
                return []
            skills = _as_list(data["skills"])
            worker.skills = skills if skills else None
        
        if "certifications" in data:
            def _as_list(v):
                if isinstance(v, list):
                    return [str(x).strip() for x in v if str(x).strip()]
                if isinstance(v, str):
                    return [s.strip() for s in v.split(',') if s.strip()]
                return []
            certs = _as_list(data["certifications"])
            worker.certifications = certs if certs else None
        
        worker.save()
        
        # Audit log
        if user:
            audit_log("update_worker", getattr(user, "id", None), {
                "worker_id": worker_id,
                "fields": list(data.keys())
            })
        
        return worker
    
    @staticmethod
    def delete_worker(worker_id: str, user: Any = None, confirm: bool = False) -> bool:
        """
        Elimina operaio con conferma obbligatoria.
        
        Args:
            worker_id: ID operaio (ObjectId string)
            user: User object (optional)
            confirm: Deve essere True per procedere
            
        Returns:
            bool: True se eliminato, False se non trovato
            
        Raises:
            ValueError: Se confirm=False
            PermissionError: Permessi insufficienti
        """
        # Permission check
        if user:
            WorkerService._require_admin(user)
        
        # Conferma obbligatoria
        if not confirm:
            raise ValueError("confirm=True obbligatorio per eliminazione")
        
        result = WorkerDoc.objects(id=worker_id).delete()
        
        # Audit log
        if user and result > 0:
            audit_log("delete_worker", getattr(user, "id", None), {
                "worker_id": worker_id
            })
        
        return result > 0
    
    @staticmethod
    def toggle_availability(worker_id: str, user: Any = None) -> Optional[Dict[str, Any]]:
        """
        Inverti disponibilità operaio.
        
        Args:
            worker_id: ID operaio (ObjectId string)
            user: User object (optional)
            
        Returns:
            Dict con nuovo stato o None se non trovato
        """
        worker = WorkerDoc.objects(id=worker_id).first()
        if not worker:
            return None
        
        current = bool(getattr(worker, "available", True))
        worker.available = not current
        worker.save()
        
        # Audit log
        if user:
            audit_log("toggle_availability", getattr(user, "id", None), {
                "worker_id": worker_id,
                "new_available": worker.available
            })
        
        return {
            "id": str(worker.id),  # ← Converti ObjectId a string
            "available": worker.available
        }
        
        # In services/workers_service.py

    # ... metodi esistenti (create, get, update, delete, toggle) ...

    @staticmethod
    def list_workers(filters: Optional[Dict[str, Any]] = None, page: int = None, per_page: int = None) -> Dict[str, Any]:
        """
        Lista operai con filtri e paginazione nativa DB.
        Ritorna {items: list, total: int}
        """
        query = WorkerDoc.objects
        
        if filters:
            if "role" in filters:
                query = query.filter(role__iexact=filters["role"])
            if "available" in filters:
                query = query.filter(available=bool(filters["available"]))
            if "city" in filters:
                query = query.filter(home_city__icontains=filters["city"])
        
        total = query.count()
        
        # Paginazione DB-side
        if page is not None and per_page is not None:
            skip = (page - 1) * per_page
            items = list(query.skip(skip).limit(per_page))
        else:
            items = list(query)
            
        return {"items": items, "total": total}

    @staticmethod
    def get_stats() -> Dict[str, Any]:
        """Calcola statistiche aggregate (ex workers_stats)."""
        from mongoengine.connection import get_db
        db = get_db()
        pipeline = [
            {"$group": {
                "_id": "$role",
                "total": {"$sum": 1},
                "available": {"$sum": {"$cond": [{"$eq": ["$available", True]}, 1, 0]}}
            }},
            {"$sort": {"total": -1}}
        ]
        results = list(db["workers"].aggregate(pipeline))
        
        return {
            "by_role": [
                {"role": r["_id"], "total": r["total"], "available": r["available"]}
                for r in results
            ],
            "total_workers": sum(r["total"] for r in results),
            "total_available": sum(r["available"] for r in results)
        }

    @staticmethod
    def get_roles_list() -> List[Dict[str, Any]]:
        """Lista ruoli unici con conteggi (ex list_roles)."""
        from mongoengine.connection import get_db
        db = get_db()
        pipeline = [
            {"$group": {"_id": "$role", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        results = list(db["workers"].aggregate(pipeline))
        return [{"role": r["_id"], "count": r["count"]} for r in results if r.get("_id")]

    @staticmethod
    def bulk_import_data(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Logica di business per l'import massivo.
        Controlla duplicati per (name, role, city) e fa upsert.
        """
        created = 0
        updated = 0
        errors = []
        
        for i, row in enumerate(rows):
            try:
                name = (row.get("name") or "").strip()
                role = (row.get("role") or "").strip()
                home_city = (row.get("home_city") or "").strip()
                
                if not name or not role:
                    errors.append(f"Row {i}: name/role mancanti")
                    continue
                
                # Check esistenza
                existing = WorkerDoc.objects(name=name, role=role, home_city=home_city).first()
                
                # Preparazione dati
                raw_avail = str(row.get("available", "")).lower()
                is_avail = raw_avail in ("1", "true", "si", "sì", "yes", "y")
                
                # Parsing skills
                skills_raw = row.get("skills", "")
                skills_list = [s.strip() for s in skills_raw.split(",") if s.strip()] if isinstance(skills_raw, str) else []
                
                hourly_rate = None
                try:
                    if row.get("hourly_rate"): hourly_rate = float(row["hourly_rate"])
                except: pass

                data = {
                    "name": name,
                    "role": role,
                    "home_city": home_city,
                    "hourly_rate": hourly_rate,
                    "available": is_avail,
                    "skills": skills_list
                }

                if existing:
                    WorkerService.update_worker(existing.id, data)
                    updated += 1
                else:
                    WorkerService.create_worker(data)
                    created += 1
                    
            except Exception as e:
                errors.append(f"Row {i} error: {str(e)}")
                
        return {"success": True, "created": created, "updated": updated, "errors": errors}


# Funzioni helper per backward compatibility con vecchio workers_service.py
def create_worker_service(args: dict, user: Any) -> dict:
    """Backward compatible wrapper."""
    try:
        worker = WorkerService.create_worker(args, user)
        return {"ok": True, "worker_id": str(worker.id), "role": worker.role}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def remove_worker_service(args: dict, user: Any) -> dict:
    """Backward compatible wrapper."""
    try:
        confirm = args.get("confirm", False)
        worker_id = args.get("worker_id")
        
        if not worker_id:
            return {"ok": False, "error": "worker_id mancante"}
        
        deleted = WorkerService.delete_worker(worker_id, user, confirm)
        
        if not deleted:
            return {"ok": False, "error": f"Worker {worker_id} non trovato"}
        
        return {"ok": True}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except PermissionError as e:
        return {"ok": False, "error": str(e)}