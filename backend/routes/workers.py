# routes/workers.py
from flask import Blueprint, request, jsonify
from services.workers_service import WorkerService
from routes.company import company_overview
import csv
import io

workers_bp = Blueprint('workers', __name__, url_prefix='/api/workers')

def _to_bool(v):
    if isinstance(v, bool): return v
    s = str(v or "").strip().lower()
    return s in {"1", "true", "si", "sì", "yes", "y"}

def _serialize_worker(w):
    """
    Serializza un WorkerDoc convertendo l'ObjectId in stringa.
    Sostituisce il vecchio w.to_dict().
    """
    return {
        "id": str(w.pk),  # pk è l'alias sicuro per _id (ObjectId)
        "name": w.name,
        "role": w.role,
        "available": w.available,
        "home_city": getattr(w, "home_city", None),
        "hourly_rate": getattr(w, "hourly_rate", None),
        "skills": getattr(w, "skills", []) or [],
        "certifications": getattr(w, "certifications", []) or [],
        "aliases": getattr(w, "aliases", []) or []
    }

# ============================================
# CRUD ENDPOINTS
# ============================================

@workers_bp.route('', methods=['GET'])
def list_workers():
    filters = {}
    if request.args.get('role'):
        filters['role'] = request.args.get('role')
    if request.args.get('available'):
        filters['available'] = _to_bool(request.args.get('available'))
    if request.args.get('city'):
        filters['city'] = request.args.get('city')
    
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    
    # Chiama il service aggiornato
    result = WorkerService.list_workers(filters, page=page, per_page=per_page)
    
    return jsonify({
        "items": [_serialize_worker(w) for w in result["items"]],
        "total": result["total"],
        "page": page,
        "per_page": per_page,
    })

@workers_bp.route('/<worker_id>', methods=['GET'])
def get_worker(worker_id):
    worker = WorkerService.get_worker(worker_id)
    if not worker:
        return jsonify({"error": "Worker non trovato"}), 404
    return jsonify({"worker": _serialize_worker(worker)})

@workers_bp.route('', methods=['POST'])
def create_worker():
    data = request.get_json() or {}
    try:
        worker = WorkerService.create_worker(data, user=None)
        
        # Gestione sicura overview (se fallisce non blocca la creazione)
        overview = {}
        try:
            ov_resp = company_overview()
            if hasattr(ov_resp, 'get_json'):
                overview = ov_resp.get_json()
        except Exception:
            pass

        return jsonify({
            "worker": _serialize_worker(worker),
            "company_overview": overview
        }), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@workers_bp.route('/<worker_id>', methods=['PUT'])
def update_worker(worker_id):
    data = request.get_json() or {}
    try:
        worker = WorkerService.update_worker(worker_id, data, user=None)
        if not worker:
            return jsonify({"error": "Worker non trovato"}), 404
        
        overview = {}
        try:
            overview = company_overview().get_json()
        except: pass

        return jsonify({
            "worker": _serialize_worker(worker),
            "company_overview": overview
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@workers_bp.route('/<worker_id>/availability', methods=['PATCH'])
def toggle_availability(worker_id):
    # toggle_availability ritorna un dict semplice, non un Doc, ma controlliamo
    res = WorkerService.toggle_availability(worker_id, user=None)
    if not res:
        return jsonify({"error": "Worker non trovato"}), 404
    
    # Se il service ritorna un dict, lo usiamo direttamente
    # Se ritornasse un oggetto Doc, useremmo _serialize_worker
    worker_data = res
    if hasattr(res, 'pk'): 
        worker_data = _serialize_worker(res)

    overview = {}
    try:
        overview = company_overview().get_json()
    except: pass
    
    return jsonify({
        "worker": worker_data,
        "company_overview": overview
    })

@workers_bp.route('/<worker_id>', methods=['DELETE'])
def delete_worker(worker_id):
    confirm = request.args.get('confirm', 'false').lower() == 'true'
    try:
        deleted = WorkerService.delete_worker(worker_id, user=None, confirm=confirm)
        if not deleted:
            return jsonify({"error": "Worker non trovato"}), 404
        
        overview = {}
        try:
            overview = company_overview().get_json()
        except: pass
        
        return jsonify({
            "success": True,
            "company_overview": overview
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================
# STATS & AGGREGATIONS
# ============================================

@workers_bp.route('/stats', methods=['GET'])
def workers_stats():
    try:
        stats = WorkerService.get_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@workers_bp.route('/roles', methods=['GET'])
def list_roles():
    try:
        roles = WorkerService.get_roles_list()
        return jsonify({"roles": roles})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================
# CSV IMPORT
# ============================================

@workers_bp.route('/import-csv', methods=['POST'])
def import_csv():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400
    
    if not file.filename.endswith('.csv'):
        return jsonify({"error": "File must be CSV"}), 400
    
    try:
        stream = io.StringIO(file.stream.read().decode("UTF-8"), newline=None)
        csv_reader = csv.DictReader(stream)
        rows = list(csv_reader)
        
        result = WorkerService.bulk_import_data(rows)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": f"CSV processing failed: {str(e)}"}), 500