from __future__ import annotations
from flask import Blueprint, request, jsonify
from io import StringIO
import csv

from models import db
from models.material import Material

materials_bp = Blueprint("materials", __name__)

# --------------------------------------------------------------------
# LISTA / FILTRI
# GET /api/materials?q=cemento&category=leganti&subcategory=portland&unit=kg&limit=50
# --------------------------------------------------------------------
@materials_bp.route("/", methods=["GET"])
def list_materials():
    q = Material.query

    txt = (request.args.get("q") or "").strip()
    cat = (request.args.get("category") or "").strip()
    sub = (request.args.get("subcategory") or "").strip()
    unit = (request.args.get("unit") or "").strip()
    limit = int(request.args.get("limit") or 50)
    limit = min(200, max(1, limit))

    if txt:
        like = f"%{txt}%"
        q = q.filter(Material.name.ilike(like))
    if cat:
        q = q.filter(Material.category.ilike(cat))
    if sub:
        q = q.filter(Material.subcategory.ilike(sub))
    if unit:
        q = q.filter(Material.unit.ilike(unit))

    q = q.order_by(Material.category.asc(), Material.name.asc())
    rows = q.limit(limit).all()
    return jsonify([r.to_dict() for r in rows])


# --------------------------------------------------------------------
# DETTAGLIO
# GET /api/materials/123
# --------------------------------------------------------------------
@materials_bp.route("/<int:material_id>", methods=["GET"])
def get_material(material_id: int):
    m = Material.query.get(material_id)
    if not m:
        return jsonify({"error": "not found"}), 404
    return jsonify(m.to_dict())


# --------------------------------------------------------------------
# CREAZIONE SINGOLO
# POST /api/materials
# JSON: { name, category?, subcategory?, unit, unit_price_eur_2025?, vat_rate?, ... }
# --------------------------------------------------------------------
@materials_bp.route("/", methods=["POST"])
def create_material():
    data = request.get_json(force=True)
    m = Material(
        name=data["name"],
        category=data.get("category"),
        subcategory=data.get("subcategory"),
        unit=data["unit"],
        unit_price_eur_2025=data.get("unit_price_eur_2025"),
        vat_rate=data.get("vat_rate", 22.0),
        supplier=data.get("supplier"),
        sku=data.get("sku"),
        stock_qty=data.get("stock_qty", 0.0),
        lead_time_days=data.get("lead_time_days", 0),
        notes=data.get("notes"),
    )
    db.session.add(m)
    db.session.commit()
    return jsonify({"id": m.id}), 201


# --------------------------------------------------------------------
# IMPORT CSV (UPSERT su (name, unit))
# POST /api/materials/import-csv  (multipart form con file=@...)
# Accetta sia 'unit_price_eur_2025' che 'price' come colonna prezzo.
# --------------------------------------------------------------------
@materials_bp.route("/import-csv", methods=["POST"])
def import_materials_csv():
    """
    CSV header esempio:
    name,category,subcategory,unit,unit_price_eur_2025,vat_rate,supplier,sku,stock_qty,lead_time_days,notes
    oppure con 'price' al posto di 'unit_price_eur_2025'
    """
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400

    f = request.files["file"]
    text = f.read().decode("utf-8-sig")  # gestisce eventuale BOM
    reader = csv.DictReader(StringIO(text))

    def _to_float(s):
        if s is None or s == "":
            return None
        return float(str(s).replace(",", ".").strip())

    created, updated, errors = 0, 0, []
    for i, row in enumerate(reader, start=1):
        try:
            name = (row.get("name") or "").strip()
            unit = (row.get("unit") or "").strip()
            if not name or not unit:
                errors.append(f"row {i}: name/unit mancanti")
                continue

            existing = Material.query.filter_by(name=name, unit=unit).first()
            target = existing or Material(name=name, unit=unit)

            target.category = (row.get("category") or None)
            target.subcategory = (row.get("subcategory") or None)

            # --- Punto 2: accetta unit_price_eur_2025 O price ---
            price_val = None
            if row.get("unit_price_eur_2025"):
                price_val = _to_float(row.get("unit_price_eur_2025"))
            elif row.get("price"):
                price_val = _to_float(row.get("price"))
            target.unit_price_eur_2025 = price_val

            vr = row.get("vat_rate")
            target.vat_rate = _to_float(vr) if vr not in (None, "") else 22.0

            target.supplier = (row.get("supplier") or None)
            target.sku = (row.get("sku") or None)

            sq = row.get("stock_qty")
            target.stock_qty = _to_float(sq) if sq not in (None, "") else 0.0

            ltd = row.get("lead_time_days")
            target.lead_time_days = int(float(ltd)) if ltd not in (None, "") else 0

            target.notes = (row.get("notes") or None)

            db.session.add(target)
            if existing:
                updated += 1
            else:
                created += 1
        except Exception as e:
            errors.append(f"row {i}: {e}")

    db.session.commit()
    return jsonify({"created": created, "updated": updated, "errors": errors})


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

    q = Material.query.filter(Material.name.ilike(f"%{name}%"))
    if unit:
        q = q.filter(Material.unit.ilike(unit))

    rows = q.order_by(Material.name.asc()).all()
    if not rows:
        return jsonify({"found": False, "matches": 0})

    # preferisci match esatto su name+unit (case insensitive)
    def _score(m: Material) -> int:
        score = 0
        if m.name.lower() == name.lower():
            score += 2
        if unit and m.unit.lower() == unit.lower():
            score += 1
        return score

    rows.sort(key=_score, reverse=True)
    best = rows[0]
    return jsonify({
        "found": True,
        "matches": len(rows),
        "material": best.to_dict(),
        "price": best.unit_price_eur_2025,
        "unit": best.unit
    })