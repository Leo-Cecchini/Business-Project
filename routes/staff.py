# routes/staff.py
from __future__ import annotations
from flask import Blueprint, request, jsonify
from io import StringIO
import csv

from sqlalchemy import func
from models import db
from models.worker import Worker

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
    return s.strip().lower() or None

# ---------------------- API --------------------------
@staff_bp.route("/", methods=["GET"])
def list_workers():
    """
    Lista dei lavoratori con filtri, ordinamento e paginazione.
    Query params:
      q           : filtro testo su nome (icontains)
      role        : filtro ruolo (icontains)
      city        : filtro città (icontains)
      skill       : cerca nel campo skills (icontains)
      available   : 1|0|true|false|si|no (se presente, ignora free_only)
      free_only   : legacy boolean (1/true) equivalente a available=true
      sort        : uno di [name, role, hourly_rate, home_city] (default: role,name)
      order       : asc|desc (default: asc)
      page        : numero pagina (>=1, default 1)
      per_page    : elementi per pagina (1..200, default 25)
    Output:
      {
        items: [ ... ],
        count: <len(items)>,
        page, per_page,
        total: <totale risultati per i filtri (senza paginazione)>,
        has_next, has_prev
      }
    """
    q = Worker.query

    # --- filtri ---
    txt = (request.args.get("q") or "").strip()
    role = (request.args.get("role") or "").strip()
    city = (request.args.get("city") or "").strip()
    skill = (request.args.get("skill") or "").strip()

    # available: priorità assoluta se passato; altrimenti compatibilità free_only
    available_param = request.args.get("available")
    free_only = (request.args.get("free_only") or "").strip().lower() in ("1", "true", "t", "yes", "y", "si", "sì")
    if available_param is not None:
        b = _to_bool(available_param)
        if b is not None:
            q = q.filter(Worker.available.is_(True if b else False))
    elif free_only:
        q = q.filter(Worker.available.is_(True))

    if txt:
        q = q.filter(Worker.name.ilike(f"%{txt}%"))
    if role:
        q = q.filter(Worker.role.ilike(f"%{role}%"))
    if city:
        q = q.filter(Worker.home_city.ilike(f"%{city}%"))
    if skill:
        q = q.filter(Worker.skills.isnot(None)).filter(Worker.skills.ilike(f"%{skill}%"))

    # --- ordinamento ---
    sort = (request.args.get("sort") or "").strip().lower()
    order = (request.args.get("order") or "asc").strip().lower()
    order_desc = (order == "desc")
    sort_map = {
        "name": Worker.name,
        "role": Worker.role,
        "hourly_rate": Worker.hourly_rate,
        "home_city": Worker.home_city,
    }
    if sort in sort_map:
        col = sort_map[sort]
        q = q.order_by(col.desc() if order_desc else col.asc())
    else:
        # default ordinamento stabile: role ASC, name ASC
        q = q.order_by(Worker.role.asc(), Worker.name.asc())

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

    # totale (senza paginazione)
    total = q.count()

    rows = q.offset((page - 1) * per_page).limit(per_page).all()
    items = [w.to_dict() for w in rows]

    return jsonify({
        "items": items,
        "count": len(items),
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_next": (page * per_page) < total,
        "has_prev": page > 1,
    })


@staff_bp.route("/roles", methods=["GET"])
def list_roles():
    """Restituisce i ruoli unici con conteggi totali e disponibili."""
    # conteggio totale per ruolo
    rows_total = (
        db.session.query(Worker.role, func.count(Worker.id))
        .group_by(Worker.role)
        .all()
    )
    total_map = {r: c for r, c in rows_total}

    # conteggio disponibili per ruolo
    rows_av = (
        db.session.query(Worker.role, func.count(Worker.id))
        .filter(Worker.available.is_(True))
        .group_by(Worker.role)
        .all()
    )
    av_map = {r: c for r, c in rows_av}

    roles = sorted(set(total_map.keys()) | set(av_map.keys()), key=lambda x: (x or ""))
    data = [
        {
            "role": r or "Senza ruolo",
            "total": int(total_map.get(r, 0) or 0),
            "available": int(av_map.get(r, 0) or 0),
        }
        for r in roles
    ]
    return jsonify({"roles": data, "count": len(data)})


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

    Colonne extra (es. phone/email) vengono ignorate senza errore.
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
            w = Worker.query.filter_by(name=name, role=role, home_city=home_city).first()
            is_new = False
            if not w:
                w = Worker(name=name, role=role, home_city=home_city)
                db.session.add(w)
                is_new = True

            # aggiorna campi noti
            if row.get("hourly_rate") not in (None, ""):
                val = _safe_float(row.get("hourly_rate"))
                if val is None:
                    errors.append(f"row {i}: hourly_rate non numerico")
                else:
                    w.hourly_rate = val

            w.certifications = (row.get("certifications") or "").strip() or w.certifications

            # available: accetta 0/1, true/false, yes/no, si/sì
            b = _to_bool(row.get("available"))
            if b is not None:
                w.available = b

            # skills CSV libero -> salva come testo normalizzato e deduplicato
            if (row.get("skills") or "").strip():
                names = [s.strip() for s in row["skills"].replace(";", ",").split(",") if s.strip()]
                seen = set()
                normalized = []
                for n in names:
                    key = n.lower()
                    if key not in seen:
                        seen.add(key)
                        normalized.append(n)
                w.skills = ", ".join(normalized)

            if is_new:
                created += 1
            else:
                updated += 1

        except Exception as e:
            errors.append(f"row {i}: {e}")

    db.session.commit()
    return jsonify({"created": created, "updated": updated, "errors": errors})
@staff_bp.patch("/<id>/available")
def patch_available(id: str):
    """Aggiorna il flag 'available' (true/false) di un operaio.
    Body JSON: {"available": true|false}
    """
    w = Worker.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    b = _to_bool(data.get("available"))
    if b is None:
        return jsonify({"error": "Campo 'available' mancante o non valido"}), 422
    w.available = b
    db.session.commit()
    return jsonify({"worker": w.to_dict()})