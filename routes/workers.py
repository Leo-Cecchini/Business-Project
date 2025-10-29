# routes/workers.py
from __future__ import annotations
from flask import Blueprint, request, jsonify
from sqlalchemy import func
from models import db
from models.worker import Worker
from uuid import uuid4
from sqlalchemy.exc import IntegrityError

# opzionale: per restituire KPI aggiornati dopo create/update/delete
try:
    from routes.company import company_overview as _company_overview
except Exception:
    _company_overview = None  # se non disponibile, va comunque tutto

workers_bp = Blueprint("workers", __name__, url_prefix="/api/workers")


# ---------------------------
# Helpers
# ---------------------------
# Helpers per gestire skills come testo e booleani dal payload
def _parse_skills(txt: str | None) -> list[str]:
    if not txt:
        return []
    # supporta separatori "," o ";"
    parts = [p.strip() for p in txt.replace(";", ",").split(",")]
    return [p for p in parts if p]

def _normalize_skills_text(txt: str | None) -> str:
    items = _parse_skills(txt)
    seen = set()
    out: list[str] = []
    for s in items:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return ", ".join(out)

def _to_bool(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "si", "sì", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    try:
        return bool(int(s))
    except Exception:
        return None


def _overview_dict() -> dict | None:
    """Richiama company_overview() e restituisce il dict JSON, se disponibile."""
    if not _company_overview:
        return None
    resp = _company_overview()
    try:
        return resp.get_json()
    except Exception:
        return None


# ---------------------------
# GET /api/workers
# Filtri: ?name=&role=&city=&available=1|0&skill=cartongesso
# ---------------------------
@workers_bp.get("")
def list_workers():
    q = Worker.query

    name = (request.args.get("name") or "").strip()
    role = (request.args.get("role") or "").strip()
    city = (request.args.get("city") or "").strip()
    available_param = request.args.get("available")  # 1/0, true/false
    skill = (request.args.get("skill") or "").strip()

    if name:
        q = q.filter(Worker.name.ilike(f"%{name}%"))
    if role:
        q = q.filter(Worker.role.ilike(f"%{role}%"))
    if city:
        q = q.filter(Worker.home_city.ilike(f"%{city}%"))
    if available_param is not None:
        b = _to_bool(available_param)
        if b is not None:
            q = q.filter(Worker.available.is_(True if b else False))
    if skill:
        q = q.filter(Worker.skills.isnot(None)).filter(Worker.skills.ilike(f"%{skill}%"))

    # sorting
    sort = (request.args.get("sort") or "").strip().lower()
    order = (request.args.get("order") or "asc").strip().lower()
    order_desc = (order == "desc")
    sort_map = {
        "name": Worker.name,
        "role": Worker.role,
        "hourly_rate": Worker.hourly_rate,
        "home_city": Worker.home_city,
        "id": Worker.id,
    }
    if sort in sort_map:
        col = sort_map[sort]
        q = q.order_by(col.desc() if order_desc else col.asc())
    else:
        q = q.order_by(Worker.role.asc(), Worker.name.asc())

    # pagination
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


# ---------------------------
# GET /api/workers/<wid>
# ---------------------------
@workers_bp.get("/<wid>")
def get_worker(wid: str):
    w = Worker.query.get_or_404(wid)
    return jsonify(w.to_dict())


# ---------------------------
# POST /api/workers
# Body JSON esempio:
# {
#   "name":"Mario Rossi","role":"Muratore","hourly_rate":18.5,"home_city":"Napoli",
#   "certifications":"PONTEGGI, DPI III","available":true,
#   "skills":["muratura","cartongesso"]
# }
# Ritorna { "worker": {...}, "overview": {...} }
# ---------------------------
@workers_bp.post("")
def create_worker():
    data = request.get_json(force=True) or {}
    wid = (data.get("id") or "").strip() or f"W-{uuid4().hex[:8].upper()}"
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome obbligatorio"}), 422

    w = Worker(
        id=wid,
        name=name,
        role=(data.get("role") or "").strip() or None,
        hourly_rate=float(data.get("hourly_rate")) if data.get("hourly_rate") not in (None, "") else None,
        home_city=(data.get("home_city") or "").strip() or None,
        certifications=(data.get("certifications") or "").strip() or None,
        available=True,  # default
        skills=None,
    )

    if "available" in data:
        b = _to_bool(data.get("available"))
        if b is not None:
            w.available = b

    # skills: può arrivare come lista di stringhe/oggetti o come testo CSV
    if "skills" in data:
        val = data.get("skills")
        if isinstance(val, list):
            # estrai i nomi e normalizza
            names = []
            for s in val:
                if isinstance(s, str):
                    s = s.strip()
                    if s:
                        names.append(s)
                elif isinstance(s, dict) and s.get("name"):
                    n = str(s["name"]).strip()
                    if n:
                        names.append(n)
            w.skills = _normalize_skills_text(", ".join(names))
        else:
            w.skills = _normalize_skills_text(val)

    db.session.add(w)
    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()
        return jsonify({"error": "ID già esistente o vincolo violato", "details": str(e)}), 409

    return jsonify({
        "worker": w.to_dict(),
        "overview": _overview_dict()
    }), 201


# ---------------------------
# PUT /api/workers/<wid>
# Aggiorna campi + skills
# Ritorna { "worker": {...}, "overview": {...} }
# ---------------------------
@workers_bp.put("/<wid>")
def update_worker(wid: str):
    w = Worker.query.get_or_404(wid)
    data = request.get_json(force=True) or {}

    for field in ("name", "role", "home_city", "certifications"):
        if field in data:
            setattr(w, field, (data.get(field) or "").strip() or None)

    if "hourly_rate" in data:
        try:
            w.hourly_rate = float(data.get("hourly_rate")) if data.get("hourly_rate") not in (None, "") else None
        except ValueError:
            pass

    if "available" in data:
        b = _to_bool(data.get("available"))
        if b is not None:
            w.available = b

    if "skills" in data:
        val = data.get("skills")
        if isinstance(val, list):
            names = []
            for s in val:
                if isinstance(s, str):
                    s = s.strip()
                    if s:
                        names.append(s)
                elif isinstance(s, dict) and s.get("name"):
                    n = str(s["name"]).strip()
                    if n:
                        names.append(n)
            w.skills = _normalize_skills_text(", ".join(names))
        else:
            w.skills = _normalize_skills_text(val)

    db.session.commit()
    return jsonify({
        "worker": w.to_dict(),
        "overview": _overview_dict()
    })


# ---------------------------
# PATCH /api/workers/<wid>/availability
# Body: {"available": true} oppure {"available": false}
# ---------------------------
@workers_bp.patch("/<wid>/availability")
def patch_availability(wid: str):
    w = Worker.query.get_or_404(wid)
    data = request.get_json(force=True) or {}
    b = _to_bool(data.get("available"))
    if b is None:
        return jsonify({"error": "Campo 'available' mancante o non valido"}), 422
    w.available = b
    db.session.commit()
    return jsonify({
        "worker": w.to_dict(),
        "overview": _overview_dict()
    })


# ---------------------------
# DELETE /api/workers/<wid>
# Hard delete
# Ritorna solo overview per aggiornare KPI rapidamente.
# ---------------------------
@workers_bp.delete("/<wid>")
def delete_worker(wid: str):
    w = Worker.query.get_or_404(wid)
    db.session.delete(w)
    db.session.commit()
    return jsonify({"ok": True, "overview": _overview_dict()})


# ---------------------------
# GET /api/workers/stats
# KPI di base per dashboard
# ---------------------------
@workers_bp.get("/stats")
def workers_stats():
    total = db.session.query(func.count(Worker.id)).scalar() or 0
    by_role = dict(db.session.query(Worker.role, func.count(Worker.id)).group_by(Worker.role).all())
    by_city = dict(db.session.query(Worker.home_city, func.count(Worker.id)).group_by(Worker.home_city).all())
    by_available = dict(db.session.query(Worker.available, func.count(Worker.id)).group_by(Worker.available).all())

    # normalizza chiavi per output JSON leggibile
    by_available_out = {("available" if k else "not_available") if k is not None else "—": v for k, v in by_available.items()}

    return jsonify({
        "total": total,
        "by_role": {k or "—": v for k, v in by_role.items()},
        "by_city": {k or "—": v for k, v in by_city.items()},
        "by_available": by_available_out,
    })