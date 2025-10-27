# routes/staff.py
from __future__ import annotations
from flask import Blueprint, request, jsonify
from io import StringIO
import csv

from sqlalchemy import func, or_
from models import db
from models.worker import Worker, Skill

staff_bp = Blueprint("staff", __name__)

# ---------------------- Helpers ----------------------
def _safe_float(v):
    try:
        return float(v)
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
    Lista dei lavoratori filtrabile.
    Query params:
      q: filtro testo su nome
      role: filtro ruolo (contains, case-insensitive)
      free_only: 1|true per solo 'disponibili'
      free_hours_threshold: soglia ore carico per considerarli disponibili (default 20.0)
      limit: max righe (default 25, max 200)
    """
    q = Worker.query
    txt = (request.args.get("q") or "").strip()
    role = (request.args.get("role") or "").strip()
    free_only = (request.args.get("free_only") or "").strip().lower() in ("1", "true", "t", "yes", "y", "si", "sì")
    try:
        fht = float(request.args.get("free_hours_threshold") or 20.0)
    except Exception:
        fht = 20.0
    try:
        limit = int(request.args.get("limit") or 25)
    except Exception:
        limit = 25
    limit = max(1, min(200, limit))

    if txt:
        like = f"%{txt}%"
        q = q.filter(Worker.name.ilike(like))
    if role:
        q = q.filter(Worker.role.ilike(f"%{role}%"))
    if free_only:
        q = q.filter(
            or_(Worker.availability.is_(None), Worker.availability != "OUT")
        ).filter(
            or_(Worker.current_load.is_(None), Worker.current_load < fht)
        )

    q = q.order_by(Worker.role.asc(), Worker.name.asc())
    rows = q.limit(limit).all()
    return jsonify([w.to_dict() for w in rows])


@staff_bp.route("/roles", methods=["GET"])
def list_roles():
    """
    Restituisce i ruoli unici con conteggi.
    """
    rows = (
        db.session.query(Worker.role, func.count(Worker.id))
        .group_by(Worker.role)
        .order_by(Worker.role.asc())
        .all()
    )
    data = [{"role": r or "Senza ruolo", "count": c} for r, c in rows]
    return jsonify({"roles": data})


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
      - availability
      - current_load
      - skills  (CSV: "muratura, pavimenti")

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
            w.availability   = (row.get("availability") or "").strip() or w.availability

            if row.get("current_load") not in (None, ""):
                val = _safe_float(row.get("current_load"))
                if val is None:
                    errors.append(f"row {i}: current_load non numerico")
                else:
                    w.current_load = val

            # skills CSV libero
            if (row.get("skills") or "").strip():
                names = [s.strip() for s in row["skills"].split(",") if s.strip()]
                skill_objs = []
                for sname in names:
                    sk = Skill.query.filter_by(name=sname).first()
                    if not sk:
                        sk = Skill(name=sname)
                        db.session.add(sk)
                    skill_objs.append(sk)
                w.skills = skill_objs

            if is_new:
                created += 1
            else:
                updated += 1

        except Exception as e:
            errors.append(f"row {i}: {e}")

    db.session.commit()
    return jsonify({"created": created, "updated": updated, "errors": errors})