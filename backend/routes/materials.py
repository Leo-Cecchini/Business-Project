# routes/materials.py
from __future__ import annotations
from flask import Blueprint, request, jsonify, current_app
from services.material_service import MaterialService

materials_bp = Blueprint("materials", __name__, url_prefix="/api/materials")

def _serialize_material(m):
    """Converte MaterialDoc in dict JSON-safe."""
    if not m: return None
    return {
        "id": str(m.id),
        "name": m.name,
        "category": getattr(m, "category", None),
        "subcategory": getattr(m, "subcategory", None),
        "unit": getattr(m, "unit", None),
        "unit_price_eur_2025": getattr(m, "unit_price_eur_2025", None),
        "vat_rate": getattr(m, "vat_rate", None),
        "supplier": getattr(m, "supplier", None),
        "sku": getattr(m, "sku", None),
        "stock_qty": getattr(m, "stock_qty", None),
        "lead_time_days": getattr(m, "lead_time_days", None),
        "notes": getattr(m, "notes", None),
    }

# --------------------------------------------------------------------
# LISTA / FILTRI
# --------------------------------------------------------------------
@materials_bp.route("/", methods=["GET"])
def list_materials():
    # Parsing argomenti (Controller)
    txt = (request.args.get("q") or "").strip()
    filters = {
        "category": (request.args.get("category") or "").strip(),
        "subcategory": (request.args.get("subcategory") or "").strip(),
        "unit": (request.args.get("unit") or "").strip()
    }
    limit = min(200, max(1, int(request.args.get("limit") or 50)))

    # Recupero dipendenza opzionale Vector Store
    vector_store = None
    try:
        vector_store = current_app.extensions.get("deps", {}).get("vector_store")
    except Exception:
        pass

    # Chiamata al Service
    results = MaterialService.list_materials_full(
        filters=filters, 
        query_text=txt, 
        limit=limit, 
        vector_store=vector_store
    )
    
    return jsonify([_serialize_material(m) for m in results])

# --------------------------------------------------------------------
# DETTAGLIO
# --------------------------------------------------------------------
@materials_bp.route("/<material_id>", methods=["GET"])
def get_material(material_id: str):
    m = MaterialService.get_by_id(material_id)
    if not m:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize_material(m))

# --------------------------------------------------------------------
# CREAZIONE / UPSERT
# --------------------------------------------------------------------
@materials_bp.route("/", methods=["POST"])
def create_material():
    data = request.get_json(force=True) or {}
    try:
        m = MaterialService.upsert_material(data)
        return jsonify({"id": str(m.id)}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --------------------------------------------------------------------
# LOOKUP (Ranking specifico)
# --------------------------------------------------------------------
@materials_bp.route("/lookup", methods=["GET"])
def lookup_material():
    name = (request.args.get("name") or "").strip()
    unit = (request.args.get("unit") or "").strip()

    if not name:
        return jsonify({"error": "param 'name' richiesto"}), 400

    result = MaterialService.lookup_best_match(name, unit)
    
    if not result.get("found"):
        return jsonify({"found": False, "matches": 0})
    
    # Serializza il documento trovato
    mat_doc = result.pop("material_doc", None)
    result["material"] = _serialize_material(mat_doc)
    
    return jsonify(result)