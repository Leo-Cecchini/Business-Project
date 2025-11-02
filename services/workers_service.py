# services/workers_service.py
import uuid
from typing import Any
from models_mongo.worker import WorkerDoc
from utils.audit import audit_log
from utils.normalization import normalize_role, generate_role_aliases
from utils.intent_router import ROLE_ALIASES  # esiste già nel tuo progetto

class PermissionError(Exception): ...

def _require_admin(user: Any):
    if not user or not getattr(user, "is_admin", False):
        raise PermissionError("Operazione non autorizzata (richiesto admin).")

def create_worker_service(args: dict, user: Any) -> dict:
    _require_admin(user)
    name = args["name"].strip()
    role_canonical = normalize_role(args["role"], ROLE_ALIASES)

    w = WorkerDoc(
        id=str(uuid.uuid4()),
        name=name,
        role=role_canonical,
        aliases=sorted(generate_role_aliases(role_canonical, ROLE_ALIASES)),
        hourly_rate=args.get("hourly_rate"),
        home_city=args.get("home_city"),
        skills=args.get("skills") or [],
        certifications=args.get("certifications") or [],
        available=True,
    )
    # opzionale: prevenire duplicati “forti” per name+role+home_city (hai già un indice unique su questi 3)
    w.save()

    audit_log("create_worker", getattr(user, "id", None), {"worker_id": w.id, "role": w.role})
    return {"ok": True, "worker_id": w.id, "role": w.role}

def remove_worker_service(args: dict, user: Any) -> dict:
    _require_admin(user)
    if not args.get("confirm"):
        # la logica di conferma è gestita a livello tool: se confirm=False, blocca
        return {"ok": False, "error": "Conferma mancante. Impostare confirm=true per procedere."}

    wid = args["worker_id"]
    deleted = WorkerDoc.objects(id=wid).delete()
    if deleted == 0:
        return {"ok": False, "error": f"Worker {wid} non trovato."}

    audit_log("remove_worker", getattr(user, "id", None), {"worker_id": wid})
    return {"ok": True}