# routes/projects.py
from flask import Blueprint, request, jsonify
from services import ProjectService
from services.schedule_service import ScheduleService
from services.work_service import WorkService
from bson import ObjectId
import traceback

projects_bp = Blueprint('projects', __name__, url_prefix='/api/projects')

def _serialize_project(p):
    """Converte ProjectDoc in dizionario JSON-safe usando to_dict() del modello."""
    result = p.to_dict()
    if hasattr(p.id, 'generation_time'):
        result['created_at'] = p.id.generation_time.isoformat()
    
    return result

# ============================================
# CRUD PROJECTS
# ============================================

@projects_bp.route('', methods=['GET'])
@projects_bp.route('/list', methods=['GET'])
def list_projects():
    """List projects with filters and pagination."""
    filters = {}
    if request.args.get("status"):
        filters["status"] = request.args.get("status")
    if request.args.get("city"):
        filters["city"] = request.args.get("city")
    
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    
    # Chiama il service aggiornato
    result = ProjectService.list_projects(filters, page=page, per_page=per_page)
    
    return jsonify({
        "items": [_serialize_project(p) for p in result["items"]],
        "total": result["total"],
        "page": page,
        "per_page": per_page
    })

@projects_bp.route('/stats', methods=['GET'])
def project_stats():
    """Project statistics."""
    try:
        stats = ProjectService.get_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@projects_bp.route('', methods=['POST'])
def create_project():
    data = request.get_json()
    try:
        project = ProjectService.create_project(data)
        return jsonify({"project": _serialize_project(project)}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@projects_bp.route('/<project_id>', methods=['GET'])
def get_project(project_id):
    project = ProjectService.get_project(project_id)
    if not project:
        return jsonify({"error": "Progetto non trovato"}), 404
    return jsonify({"project": _serialize_project(project)})

@projects_bp.route('/<project_id>', methods=['DELETE'])
def delete_project(project_id):
    deleted = ProjectService.delete_project(project_id)
    if not deleted:
        return jsonify({"error": "Progetto non trovato"}), 404
    return jsonify({"success": True})

@projects_bp.route('/<project_id>/status', methods=['POST'])
def toggle_status(project_id):
    project = ProjectService.toggle_status(project_id)
    if not project:
        return jsonify({"error": "Progetto non trovato"}), 404
    return jsonify({"project": _serialize_project(project)})

# ============================================
# DOCUMENTS (Refactored)
# ============================================

@projects_bp.route('/<project_id>/documents', methods=['GET'])
@projects_bp.route('/<project_id>/summary', methods=['GET']) # Alias legacy
def list_documents(project_id):
    """Delegates filesystem listing to Service."""
    project = ProjectService.get_project(project_id)
    if not project:
        return jsonify({"error": "Progetto non trovato"}), 404
    
    files = ProjectService.list_documents(project_id)
    
    return jsonify({
        "documents": files,
        "project": _serialize_project(project)
    })

@projects_bp.route('/<project_id>/documents', methods=['POST'])
def upload_document(project_id):
    """Delegates upload and indexing to Service."""
    project = ProjectService.get_project(project_id)
    if not project:
        return jsonify({"error": "Progetto non trovato"}), 404
    
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    
    try:
        # Passiamo l'oggetto FileStorage direttamente al service
        result = ProjectService.upload_document(project_id, file)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500
    

# ============================================
# PLANNING & SCHEDULING
# ============================================

@projects_bp.route('/<project_id>/plan', methods=['POST'])
def auto_plan_project(project_id):
    """
    Genera piano lavori automatico per il progetto.
    Era: POST /api/schedule/auto_plan
    """
    # Do not use force=True here: when the body is empty or invalid JSON, Flask
    # can raise a BadRequest before we reach our error handling.
    data = request.get_json(silent=True) or {}
    
    # Valida ObjectId
    try:
        ObjectId(project_id)
    except Exception:
        return jsonify({"ok": False, "error": "project_id invalido"}), 400
    
    # Frontend contract (SiteHeader.jsx):
    #   POST /api/projects/<id>/plan  body: { start_from: 'auto' | 'YYYY-MM-DD', replace: true }
    # Planning in questo progetto è gestita dal WorkService (calcola start/end e numero operai per work).
    try:
        start_from = data.get("start_from") or data.get("start")
        res = WorkService.plan_project(project_id, start_from=start_from)
        status = 200 if res.get("ok") else 422
        return jsonify(res), status
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@projects_bp.route('/<project_id>/schedule/assign', methods=['POST'])
def commit_plan_project(project_id):
    """
    Salva e assegna il piano generato.
    Era: POST /api/schedule/commit_plan
    """
    # Do not use force=True here: when the body is empty or invalid JSON, Flask
    # can raise a BadRequest before we reach our error handling.
    data = request.get_json(silent=True) or {}
    print(f"DEBUG /schedule/assign project_id={project_id} body={data}", flush=True)
    
    # Frontend contract (SiteHeader.jsx):
    #   POST /api/projects/<id>/schedule/assign body: {}
    # Deve assegnare automaticamente operai in base a date/ruoli e garantire 1 capo cantiere.
    try:
        res = WorkService.auto_assign(project_id)
        status = 200 if res.get("ok") else 422
        return jsonify(res), status
    except Exception as e:
        print("SCHEDULE ASSIGN ROUTE ERROR:\n" + traceback.format_exc(), flush=True)
        return jsonify({"ok": False, "error": str(e)}), 500
    
# ============================================
# WORKS MANAGEMENT
# ============================================

@projects_bp.route('/<project_id>/works/assign', methods=['POST'])
def assign_worker_to_work(project_id):
    """
    Assegna un worker a un work specifico.
    Frontend: useAssignWorkerToWork()
    """
    # Do not use force=True here: when the body is empty or invalid JSON, Flask
    # can raise a BadRequest before we reach our error handling.
    data = request.get_json(silent=True) or {}
    work_name = data.get('work_name')
    worker_id = data.get('worker_id')
    
    try:
        result = ScheduleService.assign_worker_to_work(
            project_id=project_id,
            work_name=work_name,
            worker_id=worker_id
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@projects_bp.route('/<project_id>/works/unassign', methods=['POST'])
def unassign_worker_from_work(project_id):
    """
    Rimuove un worker da un work specifico.
    Frontend: useRemoveWorkerFromWork()
    """
    # Avoid force=True: empty/invalid bodies would raise BadRequest and become 500.
    data = request.get_json(silent=True) or {}
    work_name = data.get('work_name')
    worker_id = data.get('worker_id')
    
    try:
        result = ScheduleService.unassign_worker_from_work(
            project_id=project_id,
            work_name=work_name,
            worker_id=worker_id
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@projects_bp.route('/<project_id>/works/status', methods=['PATCH'])
def update_work_status(project_id):
    """
    Aggiorna lo status di un work.
    Frontend: useUpdateWorkStatus()
    Status validi: "planned", "in_progress", "completed", "blocked", "cancelled"
    """
    # Avoid force=True: empty/invalid bodies would raise BadRequest and become 500.
    data = request.get_json(silent=True) or {}
    work_name = data.get('work_name')
    status = data.get('status')
    
    try:
        result = ScheduleService.update_work_status(
            project_id=project_id,
            work_name=work_name,
            status=status
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@projects_bp.route('/<project_id>/works/<work_name>', methods=['GET'])
def get_work_details(project_id, work_name):
    """
    Recupera dettagli di un work specifico.
    Opzionale - per debugging o frontend avanzato.
    """
    try:
        result = ScheduleService.get_work_details(
            project_id=project_id,
            work_name=work_name
        )
        
        if not result.get("found"):
            return jsonify({"error": f"Work '{work_name}' non trovato"}), 404
        
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@projects_bp.route('/<project_id>/workers', methods=['GET'])
def list_project_workers(project_id):
    """
    Lista tutti i workers assegnati al progetto.
    Opzionale - utile per overview progetto.
    """
    try:
        result = ScheduleService.list_project_workers(project_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================
# PROJECT UPDATE (PATCH)
# ============================================

@projects_bp.route('/<project_id>', methods=['PATCH'])
def update_project(project_id):
    """
    Aggiorna campi del progetto.
    Frontend: useUpdateProject()
    """
    data = request.get_json(silent=True) or {}
    
    if not data:
        return jsonify({"error": "Nessun dato da aggiornare"}), 400
    
    try:
        project = ProjectService.update_project(project_id, data)
        if not project:
            return jsonify({"error": "Progetto non trovato"}), 404
        return jsonify({"project": _serialize_project(project)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
