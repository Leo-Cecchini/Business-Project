from __future__ import annotations
from flask import Blueprint, request, jsonify, abort

# Mongo modell
from models_mongo.material import MaterialDoc

materials_bp = Blueprint("materials", __name__, url_prefix="/api/materials")

# ------------------------------
# Helpers
# ------------------------------

def _to_float(s):
    if s is None or s == "":
        return None
    try:
        return float(str(s).replace(",", ".").strip())
    except Exception:
        return None


def _doc_to_dict(doc: MaterialDoc) -> dict:
    return {
        "id": doc.id,
        "name": doc.name,
        "category": getattr(doc, "category", None),
        "subcategory": getattr(doc, "subcategory", None),
        "unit": getattr(doc, "unit", None),
        "unit_price_eur_2025": getattr(doc, "unit_price_eur_2025", None),
        "vat_rate": getattr(doc, "vat_rate", None),
        "supplier": getattr(doc, "supplier", None),
        "sku": getattr(doc, "sku", None),
        "stock_qty": getattr(doc, "stock_qty", None),
        "lead_time_days": getattr(doc, "lead_time_days", None),
        "notes": getattr(doc, "notes", None),
    }


# --------------------------------------------------------------------
# LISTA / FILTRI
# GET /api/materials?q=cemento&category=leganti&subcategory=portland&unit=kg&limit=50
# --------------------------------------------------------------------
@materials_bp.route("/", methods=["GET"])
def list_materials():
    from mongoengine.queryset.visitor import Q
    import re

    base = MaterialDoc.objects

    # --- query params ---
    txt = (request.args.get("q") or "").strip()
    cat = (request.args.get("category") or "").strip()
    sub = (request.args.get("subcategory") or "").strip()
    unit = (request.args.get("unit") or "").strip()
    sku = (request.args.get("sku") or "").strip().upper()
    fuzzy = int(request.args.get("fuzzy") or 0)

    limit = int(request.args.get("limit") or 50)
    limit = min(200, max(1, limit))

    # --- filtri strutturali a monte (sempre applicati) ---
    if cat:
        base = base.filter(category__icontains=cat)
    if sub:
        base = base.filter(subcategory__icontains=sub)
    if unit:
        base = base.filter(unit__iexact=unit)

    # ---- 0) SKU first (match diretto) ----
    if sku:
        m = base.filter(sku=sku).first()
        if m:
            return jsonify([_doc_to_dict(m)]), 200

    # ---- 1..4) pipeline di fallback sul testo ----
    hits = []
    if txt:
        # 1) aliases
        hits = list(base.filter(aliases__icontains=txt).limit(limit))

        # 2) name
        if not hits:
            hits = list(base.filter(name__icontains=txt).limit(limit))

        # 3) text index (richiede indice testuale su materials)
        if not hits:
            try:
                hits = list(
                    base.search_text(txt)
                        .order_by("$text_score")
                        .limit(limit)
                )
            except Exception:
                hits = []

        # 4) fuzzy (regex semplice tollerante su spazi)
        if not hits and fuzzy:
            pattern = ".*".join(map(re.escape, txt.split()))
            hits = list(
                base.filter(
                    Q(name__iregex=pattern) | Q(aliases__iregex=pattern)
                ).limit(limit)
            )

        rows = hits
    else:
        # nessuna query testuale: elenco filtrato e ordinato
        rows = list(base.order_by("category", "name").limit(limit))

    return jsonify([_doc_to_dict(r) for r in rows])


# --------------------------------------------------------------------
# DETTAGLIO
# GET /api/materials/123
# --------------------------------------------------------------------
@materials_bp.route("/<material_id>", methods=["GET"])
def get_material(material_id: str):
    try:
        m = MaterialDoc.objects.get(id=str(material_id))
    except Exception:
        return jsonify({"error": "not found"}), 404
    return jsonify(_doc_to_dict(m))


# --------------------------------------------------------------------
# CREAZIONE SINGOLO
# POST /api/materials
# JSON: { name, category?, subcategory?, unit, unit_price_eur_2025?, vat_rate?, ... }
# --------------------------------------------------------------------
@materials_bp.route("/", methods=["POST"])
def create_material():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    unit = (data.get("unit") or "").strip().lower()
    sku = (data.get("sku") or "").strip().upper()
    if not name or not unit or not sku:
        return jsonify({"error": "name, unit e sku sono obbligatori"}), 422

    # chiave stabile basata su (sku, unit)
    _id = (data.get("id") or f"{sku}|{unit}")

    MaterialDoc.objects(id=_id).update_one(
        set__name=name,
        set__category=(data.get("category") or None),
        set__subcategory=(data.get("subcategory") or None),
        set__unit=unit,
        set__unit_price_eur_2025=(data.get("unit_price_eur_2025") if data.get("unit_price_eur_2025") not in (None, "") else data.get("price")),
        set__vat_rate=_to_float(data.get("vat_rate")) if data.get("vat_rate") not in (None, "") else 22.0,
        set__supplier=(data.get("supplier") or None),
        set__sku=sku,
        set__stock_qty=_to_float(data.get("stock_qty")) if data.get("stock_qty") not in (None, "") else 0.0,
        set__lead_time_days=int(_to_float(data.get("lead_time_days")) or 0),
        set__notes=(data.get("notes") or None),
        upsert=True,
    )
    m = MaterialDoc.objects.get(id=_id)
    return jsonify({"id": m.id}), 201


# --------------------------------------------------------------------
# LOOKUP per nome/unità (per domande tipo: "quanto costa il cemento 32.5 (€/kg)?")
# GET /api/materials/lookup?name=cemento%2032.5&unit=kg
# --------------------------------------------------------------------
@materials_bp.route("/lookup", methods=["GET"])
def lookup_material():
    name = (request.args.get("name") or "").strip()
    unit = (request.args.get("unit") or "").strip()

    if not name:
        return jsonify({"error": "param 'name' richiesto"}), 400

    qs = MaterialDoc.objects(name__icontains=name)
    if unit:
        qs = qs.filter(unit__iexact=unit)

    rows = list(qs.order_by("name"))
    if not rows:
        return jsonify({"found": False, "matches": 0})

    def _score(m: MaterialDoc) -> int:
        score = 0
        if (m.name or "").lower() == name.lower():
            score += 2
        if unit and (m.unit or "").lower() == unit.lower():
            score += 1
        return score

    rows.sort(key=_score, reverse=True)
    best = rows[0]
    return jsonify({
        "found": True,
        "matches": len(rows),
        "material": _doc_to_dict(best),
        "price": best.unit_price_eur_2025,
        "unit": best.unit
    })