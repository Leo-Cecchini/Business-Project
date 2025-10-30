# routes/workers.py
from __future__ import annotations
from flask import Blueprint, request, jsonify, abort
from uuid import uuid4

# Mongo model
from models_mongo.worker import WorkerDoc

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


# Helpers per conversione CSV <-> lista

def _split_csv(txt: str | None) -> list[str]:
    if not txt:
        return []
    return [p.strip() for p in txt.replace(";", ",").split(",") if p.strip()]


def _doc_to_dict(doc: WorkerDoc) -> dict:
    # Ricostruisce l'output compatibile con l'attuale UI (skills/certifications come CSV)
    skills_csv = ", ".join(doc.skills or []) if isinstance(doc.skills, list) else (doc.skills or "")
    certs_csv = ", ".join(doc.certifications or []) if isinstance(doc.certifications, list) else (doc.certifications or "")
    return {
        "id": doc.id,
        "name": doc.name,
        "role": getattr(doc, "role", None),
        "hourly_rate": getattr(doc, "hourly_rate", None),
        "home_city": getattr(doc, "home_city", None),
        "certifications": certs_csv or None,
        "available": True if doc.available is None else bool(doc.available),
        "skills": skills_csv or None,
    }


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
    qs = WorkerDoc.objects

    name = (request.args.get("name") or "").strip()
    role = (request.args.get("role") or "").strip()
    city = (request.args.get("city") or "").strip()
    available_param = request.args.get("available")  # 1/0, true/false
    skill = (request.args.get("skill") or "").strip()

    if name:
        qs = qs.filter(name__icontains=name)
    if role:
        qs = qs.filter(role__icontains=role)
    if city:
        qs = qs.filter(home_city__icontains=city)
    if available_param is not None:
        b = _to_bool(available_param)
        if b is not None:
            qs = qs.filter(available=b)
    if skill:
        qs = qs.filter(skills__icontains=skill) | qs.filter(skills__in=[skill])

    # sorting
    sort = (request.args.get("sort") or "").strip().lower()
    order = (request.args.get("order") or "asc").strip().lower()
    order_desc = (order == "desc")
    sort_map = {
        "name": "name",
        "role": "role",
        "hourly_rate": "hourly_rate",
        "home_city": "home_city",
        "id": "id",
    }
    if sort in sort_map:
        field = sort_map[sort]
        qs = qs.order_by(("-" if order_desc else "") + field)
    else:
        qs = qs.order_by("role", "name")

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

    total = qs.count()
    rows = qs.skip((page - 1) * per_page).limit(per_page)
    items = [_doc_to_dict(w) for w in rows]

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
    try:
        w = WorkerDoc.objects.get(id=wid)
    except Exception:
        abort(404)
    return jsonify(_doc_to_dict(w))


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

    # available
    available = True
    if "available" in data:
        b = _to_bool(data.get("available"))
        if b is not None:
            available = b

    # skills: accetta lista o CSV; salva come lista
    skills_csv_norm = None
    skills_list = []
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
            skills_csv_norm = _normalize_skills_text(", ".join(names))
            skills_list = names
        else:
            skills_csv_norm = _normalize_skills_text(val)
            skills_list = _split_csv(skills_csv_norm)

    # certifications: accetta stringa CSV o lista
    certs_val = data.get("certifications")
    if isinstance(certs_val, list):
        certifications_list = [str(c).strip() for c in certs_val if str(c).strip()]
        certs_csv = ", ".join(certifications_list)
    else:
        certs_csv = (str(certs_val).strip() if certs_val else None)
        certifications_list = _split_csv(certs_csv)

    WorkerDoc.objects(id=wid).update_one(
        set__name=name,
        set__role=(data.get("role") or "").strip() or None,
        set__hourly_rate=float(data.get("hourly_rate")) if data.get("hourly_rate") not in (None, "") else None,
        set__home_city=(data.get("home_city") or "").strip() or None,
        set__certifications=certifications_list,
        set__available=available,
        set__skills=skills_list,
        upsert=True,
    )

    w = WorkerDoc.objects.get(id=wid)
    payload = _doc_to_dict(w)
    # se abbiamo normalizzato skills, sovrascriviamo il CSV nell'output
    if skills_csv_norm is not None:
        payload["skills"] = skills_csv_norm or None
    if certs_csv is not None:
        payload["certifications"] = certs_csv or None

    return jsonify({
        "worker": payload,
        "overview": _overview_dict()
    }), 201


# ---------------------------
# PUT /api/workers/<wid>
# Aggiorna campi + skills
# Ritorna { "worker": {...}, "overview": {...} }
# ---------------------------
@workers_bp.put("/<wid>")
def update_worker(wid: str):
    try:
        w = WorkerDoc.objects.get(id=wid)
    except Exception:
        abort(404)
    data = request.get_json(force=True) or {}

    updates = {}
    for field in ("name", "role", "home_city"):
        if field in data:
            val = (data.get(field) or "").strip() or None
            updates[f"set__{field}"] = val

    if "certifications" in data:
        certs_val = data.get("certifications")
        if isinstance(certs_val, list):
            certifications_list = [str(c).strip() for c in certs_val if str(c).strip()]
        else:
            certifications_list = _split_csv(certs_val)
        updates["set__certifications"] = certifications_list

    if "hourly_rate" in data:
        try:
            updates["set__hourly_rate"] = float(data.get("hourly_rate")) if data.get("hourly_rate") not in (None, "") else None
        except ValueError:
            pass

    if "available" in data:
        b = _to_bool(data.get("available"))
        if b is not None:
            updates["set__available"] = b

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
            skills_csv_norm = _normalize_skills_text(", ".join(names))
            updates["set__skills"] = names
        else:
            skills_csv_norm = _normalize_skills_text(val)
            updates["set__skills"] = _split_csv(skills_csv_norm)
    else:
        skills_csv_norm = None

    if updates:
        WorkerDoc.objects(id=wid).update_one(**updates)
        w = WorkerDoc.objects.get(id=wid)
    else:
        w = w

    payload = _doc_to_dict(w)
    if skills_csv_norm is not None:
        payload["skills"] = skills_csv_norm or None

    return jsonify({
        "worker": payload,
        "overview": _overview_dict()
    })


# ---------------------------
# PATCH /api/workers/<wid>/availability
# Body: {"available": true} oppure {"available": false}
# ---------------------------
@workers_bp.patch("/<wid>/availability")
def patch_availability(wid: str):
    try:
        WorkerDoc.objects.get(id=wid)
    except Exception:
        abort(404)
    data = request.get_json(force=True) or {}
    b = _to_bool(data.get("available"))
    if b is None:
        return jsonify({"error": "Campo 'available' mancante o non valido"}), 422
    WorkerDoc.objects(id=wid).update_one(set__available=b)
    w = WorkerDoc.objects.get(id=wid)
    return jsonify({
        "worker": _doc_to_dict(w),
        "overview": _overview_dict()
    })


# ---------------------------
# DELETE /api/workers/<wid>
# Hard delete
# Ritorna solo overview per aggiornare KPI rapidamente.
# ---------------------------
@workers_bp.delete("/<wid>")
def delete_worker(wid: str):
    try:
        WorkerDoc.objects.get(id=wid)
    except Exception:
        abort(404)
    WorkerDoc.objects(id=wid).delete()
    return jsonify({"ok": True, "overview": _overview_dict()})


# ---------------------------
# GET /api/workers/stats
# KPI di base per dashboard
# ---------------------------
@workers_bp.get("/stats")
def workers_stats():
    total = WorkerDoc.objects.count()

    # by_role
    pipeline_role = [{"$group": {"_id": {"$ifNull": ["$role", "—"]}, "c": {"$sum": 1}}}]
    by_role_res = {d["_id"]: d["c"] for d in WorkerDoc.objects.aggregate(*pipeline_role)}

    # by_city
    pipeline_city = [{"$group": {"_id": {"$ifNull": ["$home_city", "—"]}, "c": {"$sum": 1}}}]
    by_city_res = {d["_id"]: d["c"] for d in WorkerDoc.objects.aggregate(*pipeline_city)}

    # by_available
    pipeline_av = [{"$group": {"_id": {"$ifNull": ["$available", None]}, "c": {"$sum": 1}}}]
    raw_av = {d["_id"]: d["c"] for d in WorkerDoc.objects.aggregate(*pipeline_av)}
    by_available_out = {
        ("available" if k else "not_available") if k is not None else "—": v
        for k, v in raw_av.items()
    }

    return jsonify({
        "total": int(total or 0),
        "by_role": by_role_res,
        "by_city": by_city_res,
        "by_available": by_available_out,
    })