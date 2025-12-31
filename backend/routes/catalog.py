# routes/work_catalog.py
from flask import Blueprint, jsonify, request
from services.catalog_service import CatalogService

workcat_bp = Blueprint("work_catalog", __name__, url_prefix="/api/catalog/works")

# --- CATALOGO LAVORI ---

@workcat_bp.get("/")
def list_work_catalog():
    """Lista tutte le voci del catalogo."""
    items = CatalogService.list_items()
    return jsonify({"ok": True, "items": items}), 200

@workcat_bp.get("/<code>")
def get_work_item(code: str):
    """Dettaglio singola voce."""
    doc = CatalogService.get_item_by_code(code)
    if not doc:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "item": doc}), 200

@workcat_bp.get("/search")
def search_work_catalog():
    """Ricerca voci."""
    q = (request.args.get("q") or "").strip()
    role = (request.args.get("role") or "").strip().lower()
    unit = (request.args.get("unit") or "").strip().lower()
    limit = int(request.args.get("limit") or 50)

    res = CatalogService.search_items(q, role, unit, limit)
    return jsonify({"ok": True, **res}), 200

@workcat_bp.get("/crew/<code>")
def get_work_crew_requirements(code: str):
    """Recupera requisiti squadra (per Scheduler)."""
    doc = CatalogService.get_crew_requirements(code)
    if not doc:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "crew": doc}), 200

@workcat_bp.post("/")
def upsert_work_catalog_item():
    """Crea o aggiorna manualmente una voce."""
    data = request.get_json(force=True) or {}
    try:
        code = CatalogService.upsert_item(data)
        return jsonify({"ok": True, "code": code}), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- LISTINI PREZZI (Pricelist) ---

@workcat_bp.get("/pricelist")
def get_pricelist():
    """Ritorna il listino per regione/città."""
    region = (request.args.get("region") or request.args.get("regione") or "").strip()
    city = (request.args.get("city") or request.args.get("citta") or request.args.get("città") or "").strip()
    
    if not region and not city:
        return jsonify({"error": "region or city required"}), 400

    doc = CatalogService.get_pricelist(region, city)
    # Se non trova nulla, ritorna ok con pricelist null (il frontend gestirà i default)
    return jsonify({"ok": True, "pricelist": doc}), 200

@workcat_bp.post("/pricelist/upsert_codes")
def upsert_pricelist_codes():
    """Aggiorna puntualmente prezzi nel listino."""
    data = request.get_json(force=True) or {}
    region = (data.get("region") or data.get("regione") or "").strip()
    city = (data.get("city") or data.get("citta") or data.get("città") or "").strip()

    try:
        res = CatalogService.upsert_pricelist_codes(region, city, data)
        return jsonify({"ok": True, **res}), 200
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 422
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500