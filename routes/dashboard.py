# routes/dashboard.py
from flask import Blueprint, request, jsonify
from mongoengine import DoesNotExist, ValidationError
from models_mongo.worker import WorkerDoc
from models_mongo.project import ProjectDoc

bp = Blueprint("dashboard", __name__, url_prefix="/api")

@bp.get("/dashboard/summary")
def dashboard_summary():
    """Ritorna conteggi reali dal DB per i KPI della dashboard."""
    operai = WorkerDoc.objects.count()
    operai_attivi = WorkerDoc.objects(available=True).count()
    cantieri = ProjectDoc.objects.count()
    # Consideriamo "attivi" i progetti con status "Confermato"
    cantieri_attivi = ProjectDoc.objects(status__iexact="Confermato").count()
    return jsonify({
        "operai": int(operai),
        "operai_attivi": int(operai_attivi),
        "cantieri": int(cantieri),
        "cantieri_attivi": int(cantieri_attivi),
        "documenti_azienda": 0  # aggiorna se esiste una collection documenti
    })

# ---- Workers ----
@bp.get("/workers")
def list_workers():
    limit = max(1, min(int(request.args.get("limit", 20)), 100))
    page = max(1, int(request.args.get("page", 1)))
    qs = WorkerDoc.objects.order_by("-created_at").skip((page-1)*limit).limit(limit)
    items = [{
        "id": str(w.id),
        "name": w.name,
        "role": getattr(w, "role", "operaio"),
        "is_active": bool(getattr(w, "available", True))  # mappiamo available -> is_active per la UI
    } for w in qs]
    return jsonify({"items": items, "page": page, "limit": limit})

@bp.post("/workers")
def create_worker():
    data = request.get_json(force=True) or {}
    name = data.get("name")
    if not name:
        return jsonify({"ok": False, "error": "name è obbligatorio"}), 400
    try:
        w = WorkerDoc(
            name=name,
            role=data.get("role", "operaio"),
            available=bool(data.get("is_active", True))
        ).save()
        return jsonify({"ok": True, "id": str(w.id)})
    except ValidationError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@bp.delete("/workers/<worker_id>")
def delete_worker(worker_id):
    try:
        WorkerDoc.objects.get(id=worker_id).delete()
        return jsonify({"ok": True})
    except DoesNotExist:
        return jsonify({"ok": False, "error": "Operaio non trovato"}), 404

# ---- Projects ----
@bp.get("/projects")
def list_projects():
    limit = max(1, min(int(request.args.get("limit", 20)), 100))
    page = max(1, int(request.args.get("page", 1)))
    qs = ProjectDoc.objects.order_by("-created_at").skip((page-1)*limit).limit(limit)
    items = [{
        "id": str(p.id),
        "name": p.name,
        "status": getattr(p, "status", "Preventivo"),
        # per compatibilità UI: is_active dedotto dallo status
        "is_active": (getattr(p, "status", "").lower() == "confermato")
    } for p in qs]
    return jsonify({"items": items, "page": page, "limit": limit})

@bp.post("/projects")
def create_project():
    data = request.get_json(force=True) or {}
    name = data.get("name")
    if not name:
        return jsonify({"ok": False, "error": "name è obbligatorio"}), 400
    try:
        p = ProjectDoc(
            name=name,
            status=data.get("status", "Preventivo")
        ).save()
        return jsonify({"ok": True, "id": str(p.id)})
    except ValidationError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

@bp.delete("/projects/<project_id>")
def delete_project(project_id):
    try:
        ProjectDoc.objects.get(id=project_id).delete()
        return jsonify({"ok": True})
    except DoesNotExist:
        return jsonify({"ok": False, "error": "Cantiere non trovato"}), 404