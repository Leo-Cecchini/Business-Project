# routes/staff.py (MongoEngine version)
from __future__ import annotations

from flask import Blueprint, request, jsonify, abort
from io import StringIO
import csv
import uuid
from typing import Any, Dict, Optional

# MongoEngine models
from models_mongo.worker import WorkerDoc

staff_bp = Blueprint("staff", __name__)

# ---------------------- Helpers ----------------------

def _safe_float(v):
    try:
        return float(v)
    except Exception:
        return None


def _to_bool(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "si", "sì", "on"):  # valori "vero"
        return True
    if s in ("0", "false", "f", "no", "n", "off"):  # valori "falso"
        return False
    try:
        return bool(int(s))
    except Exception:
        return None


def _norm_role(s: str | None) -> str | None:
    if not s:
        return None
    return s.strip() or None


def _doc_to_dict(w: WorkerDoc) -> Dict[str, Any]:
    return {
        "id": str(getattr(w, "id", None)),
        "name": getattr(w, "name", None),
        "role": getattr(w, "role", None),
        "available": getattr(w, "available", None),
        "hourly_rate": getattr(w, "hourly_rate", None),
        "home_city": getattr(w, "home_city", None),
        "skills": getattr(w, "skills", None),
        "certifications": getattr(w, "certifications", None),
        "notes": getattr(w, "notes", None),
    }


def _skills_from_csv_cell(cell: str | None):
    if not cell:
        return None
    names = [s.strip() for s in str(cell).replace(";", ",").split(",") if s.strip()]
    if not names:
        return None
    # dedup case-insensitive mantenendo ordine
    seen = set()
    out = []
    for n in names:
        key = n.lower()
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out


# ---------------------- API --------------------------
@staff_bp.get("/ping")
def staff_ping():
    return jsonify({"ok": True, "who": "staff"}), 200


@staff_bp.route("/", methods=["GET"])
def list_workers():
    """
    Lista dei lavoratori con filtri, ordinamento e paginazione.
    Query params:
      q           : filtro testo su nome/ruolo (icontains)
      role        : filtro ruolo (icontains)
      city        : filtro città (icontains)
      skill       : cerca nel campo skills (icontains su elementi lista)
      available   : 1|0|true|false|si|no
      free_only   : legacy boolean (1/true) equivalente a available=true
      sort        : uno di [name, role, hourly_rate, home_city] (default: role,name)
      order       : asc|desc (default: asc)
      page        : numero pagina (>=1, default 1)
      per_page    : elementi per pagina (1..200, default 25)
    """
    qs = WorkerDoc.objects

    # --- filtri ---
    txt = (request.args.get("q") or "").strip()
    role = (request.args.get("role") or "").strip()
    city = (request.args.get("city") or "").strip()
    skill = (request.args.get("skill") or "").strip()

    available_param = request.args.get("available")
    free_only = (request.args.get("free_only") or "").strip().lower() in ("1", "true", "t", "yes", "y", "si", "sì")

    if available_param is not None:
        b = _to_bool(available_param)
        if b is not None:
            qs = qs.filter(available=b)
    elif free_only:
        qs = qs.filter(available=True)

    if txt:
        qs = qs.filter(__raw__={
            "$or": [
                {"name": {"$regex": txt, "$options": "i"}},
                {"role": {"$regex": txt, "$options": "i"}},
            ]
        })
    if role:
        qs = qs.filter(role__icontains=role)
    if city:
        qs = qs.filter(home_city__icontains=city)
    if skill:
        # skills è una lista di stringhe → regex su elementi
        qs = qs.filter(__raw__={"skills": {"$regex": skill, "$options": "i"}})

    # --- ordinamento ---
    sort = (request.args.get("sort") or "").strip().lower()
    order = (request.args.get("order") or "asc").strip().lower()
    order_desc = (order == "desc")
    sort_map = {
        "name": "name",
        "role": "role",
        "hourly_rate": "hourly_rate",
        "home_city": "home_city",
    }
    if sort in sort_map:
        key = ("-" if order_desc else "") + sort_map[sort]
        qs = qs.order_by(key)
    else:
        # default: role ASC, name ASC
        qs = qs.order_by("role", "name")

    # --- paginazione ---
    try:
        page = int(request.args.get("page") or 1)
    except Exception:
        page = 1
    try:
        per_page = int(request.args.get("per_page") or 25)
    except Exception:
        per_page = 25
    page = max(1, page)
    per_page = max(1, min(200, per_page))

    total = qs.count()
    rows = qs.skip((page - 1) * per_page).limit(per_page)
    items = [_doc_to_dict(w) for w in rows]

    return jsonify({
        "items": items,
        "count": len(items),
        "page": page,
        "per_page": per_page,
        "total": int(total),
        "has_next": (page * per_page) < total,
        "has_prev": page > 1,
    }), 200


@staff_bp.route("/roles", methods=["GET"])
def list_roles():
    """Restituisce i ruoli unici con conteggi totali e disponibili."""
    try:
        col = WorkerDoc._get_collection()
        rows_total = list(col.aggregate([
            {"$group": {"_id": "$role", "count": {"$sum": 1}}}
        ]))
        rows_av = list(col.aggregate([
            {"$match": {"available": True}},
            {"$group": {"_id": "$role", "count": {"$sum": 1}}}
        ]))

        total_map = {r.get("_id") or None: int(r.get("count", 0)) for r in rows_total}
        av_map = {r.get("_id") or None: int(r.get("count", 0)) for r in rows_av}

        roles = sorted(set(total_map.keys()) | set(av_map.keys()), key=lambda x: (x or ""))
        data = [
            {
                "role": r or "Senza ruolo",
                "total": int(total_map.get(r, 0) or 0),
                "available": int(av_map.get(r, 0) or 0),
            }
            for r in roles
        ]
        return jsonify({"roles": data, "count": len(data)}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@staff_bp.route("/import-csv", methods=["POST"])
def import_workers_csv():
    """
    Importa/aggiorna operai/dipendenti da CSV.
    Upsert per chiave logica: (name, role, home_city).
    Colonne supportate (tutte opzionali eccetto 'name'):
      - name (obbligatoria)
      - role
      - hourly_rate
      - home_city
      - certifications
      - available       (0/1, true/false, yes/no)
      - skills          (CSV: "muratura, pavimenti")

    Colonne extra vengono ignorate senza errore.
    """
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400

    f = request.files["file"]
    if not f.filename.lower().endswith(".csv"):
        return jsonify({"error": "Il file deve essere un CSV"}), 400

    text = f.read().decode("utf-8-sig")
    reader = csv.DictReader(StringIO(text))

    created, updated, errors = 0, 0, []

    for i, row in enumerate(reader, start=1):
        try:
            name = (row.get("name") or "").strip()
            if not name:
                errors.append(f"row {i}: name mancante")
                continue

            role = _norm_role(row.get("role"))
            home_city = (row.get("home_city") or "").strip() or None

            # cerca esistente per (name, role, home_city)
            w = WorkerDoc.objects(name=name, role=role, home_city=home_city).first()
            is_new = False
            if not w:
                # genera un id
                wid = f"W-{uuid.uuid4().hex[:8]}"
                w = WorkerDoc(id=wid, name=name, role=role, home_city=home_city)
                is_new = True

            # aggiorna campi noti
            if row.get("hourly_rate") not in (None, ""):
                val = _safe_float(row.get("hourly_rate"))
                if val is None:
                    errors.append(f"row {i}: hourly_rate non numerico")
                else:
                    w.hourly_rate = val

            if (row.get("certifications") or "").strip():
                w.certifications = _skills_from_csv_cell(row.get("certifications"))

            # available: accetta 0/1, true/false, yes/no, si/sì
            b = _to_bool(row.get("available"))
            if b is not None:
                w.available = b

            # skills CSV libero -> salva come lista (deduplicata)
            if (row.get("skills") or "").strip():
                w.skills = _skills_from_csv_cell(row.get("skills"))

            w.save()
            if is_new:
                created += 1
            else:
                updated += 1

        except Exception as e:
            errors.append(f"row {i}: {e}")

    return jsonify({"created": created, "updated": updated, "errors": errors}), 200


@staff_bp.patch("/<string:wid>/available")
def patch_available(wid: str):
    """Aggiorna il flag 'available' (true/false) di un operaio.
    Body JSON: {"available": true|false}
    """
    w = WorkerDoc.objects(id=str(wid)).first()
    if not w:
        abort(404)
    data = request.get_json(silent=True) or {}
    b = _to_bool(data.get("available"))
    if b is None:
        return jsonify({"error": "Campo 'available' mancante o non valido"}), 422
    w.update(set__available=b)
    w.reload()
    return jsonify({"worker": _doc_to_dict(w)})