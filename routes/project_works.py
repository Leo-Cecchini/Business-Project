# routes/project_works.py
from flask import Blueprint, jsonify, request
from mongoengine.connection import get_db


projworks_bp = Blueprint("project_works", __name__, url_prefix="/api/projects")

# Stati che consentono l'assegnazione (compat IT/EN)
ALLOWED_ASSIGN_STATES = {"Confermato", "In corso", "Attivo", "Active"}

def _load_project(db, pid):
    doc = db["projects"].find_one({"id": pid}) or db["projects"].find_one({"_id": pid})
    return doc

def _save_project_works(db, proj, works, replace=True):
    update = {"$set": {"works": works}} if replace else {"$push": {"works": {"$each": works}}}
    db["projects"].update_one({"_id": proj["_id"]}, update)

@projworks_bp.get("/<pid>/works")
def list_project_works(pid: str):
    db = get_db()
    proj = _load_project(db, pid)
    if not proj:
        return jsonify({"error": "Progetto non trovato"}), 404
    return jsonify({"ok": True, "items": proj.get("works") or []}), 200

@projworks_bp.post("/<pid>/works/add")
def add_project_work(pid: str):
    """
    Aggiunge un lavoro al progetto prendendo definizioni dal work_catalog.
    Body: { code: 'FLOOR_TILE', qty: 120, notes?: '...' }
    """
    db = get_db()
    proj = _load_project(db, pid)
    if not proj:
        return jsonify({"error": "Progetto non trovato"}), 404

    data = request.get_json(force=True) or {}
    code = (data.get("code") or "").strip().upper()
    try:
        qty = float(data.get("qty", 0) or 0)
    except Exception:
        qty = 0.0
    if not code or qty <= 0:
        return jsonify({"error": "code e qty (>0) sono obbligatori"}), 400

    cat = db["work_catalog"].find_one({"code": code})
    if not cat:
        return jsonify({"error": f"Work code non trovato in catalogo: {code}"}), 404

    item = {
        "work_code": code,
        "work_name": cat.get("name"),
        "qty": qty,
        "unit": cat.get("unit"),
        "primary_role": cat.get("primary_role"),
        "roles_allowed": cat.get("roles_allowed") or [],
        "status": "planned",
        "crew_size_planned": cat.get("min_crew", 1),
        "hours_estimated": None,             # verrà calcolato nel planner
        "start_date_planned": None,          # verrà calcolato nel planner
        "end_date_planned": None,            # verrà calcolato nel planner
        "notes": (data.get("notes") or "").strip() or None,
    }

    works = list(proj.get("works") or [])
    works.append(item)
    _save_project_works(db, proj, works, replace=True)
    return jsonify({"ok": True, "added": item, "total": len(works)}), 201

@projworks_bp.post("/<pid>/works/bulk")
def bulk_project_works(pid: str):
    """
    Aggiunge o sostituisce lavori in blocco.
    Body: { items: [{ code, qty, notes? }...], replace?: true|false }
    """
    db = get_db()
    proj = _load_project(db, pid)
    if not proj:
        return jsonify({"error": "Progetto non trovato"}), 404

    data = request.get_json(force=True) or {}
    raw_items = data.get("items") or []
    replace = bool(data.get("replace", True))

    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({"error": "items deve essere una lista non vuota"}), 400

    codes = [ (it.get("code") or "").strip().upper() for it in raw_items ]
    cat_docs = list(get_db()["work_catalog"].find({"code": {"$in": codes}}))
    cat_by_code = { c["code"]: c for c in cat_docs }

    prepared = []
    for it in raw_items:
        code = (it.get("code") or "").strip().upper()
        try:
            qty = float(it.get("qty", 0) or 0)
        except Exception:
            qty = 0.0
        if not code or qty <= 0:
            continue
        cat = cat_by_code.get(code)
        if not cat:
            continue
        prepared.append({
            "work_code": code,
            "work_name": cat.get("name"),
            "qty": qty,
            "unit": cat.get("unit"),
            "primary_role": cat.get("primary_role"),
            "roles_allowed": cat.get("roles_allowed") or [],
            "status": "planned",
            "crew_size_planned": cat.get("min_crew", 1),
            "hours_estimated": None,
            "start_date_planned": None,
            "end_date_planned": None,
            "notes": (it.get("notes") or "").strip() or None,
        })

    if not prepared:
        return jsonify({"error": "Nessun lavoro valido da importare"}), 400

    if replace:
        _save_project_works(db, proj, prepared, replace=True)
        total = len(prepared)
    else:
        current = list(proj.get("works") or [])
        current.extend(prepared)
        _save_project_works(db, proj, current, replace=True)
        total = len(current)

    return jsonify({"ok": True, "added": len(prepared), "total": total, "replace": replace}), 200

@projworks_bp.delete("/<pid>/works/clear")
def clear_project_works(pid: str):
    db = get_db()
    proj = _load_project(db, pid)
    if not proj:
        return jsonify({"error": "Progetto non trovato"}), 404
    _save_project_works(db, proj, [], replace=True)
    return jsonify({"ok": True, "total": 0}), 200

# === PLANNER: calcola start/end/durata dai dati del catalogo ===
from datetime import datetime, timedelta

def _to_date(s): return datetime.strptime(s, "%Y-%m-%d")
def _to_str(d): return d.strftime("%Y-%m-%d")

@projworks_bp.post("/<pid>/plan")
def plan_project(pid: str):
    """
    Pianifica i lavori esistenti nel progetto usando work_catalog:
    - calcola ore stimate da qty e produttività (per worker e crew)
    - impone precedenze (prerequisites) con ordinamento topologico
    - concatena i blocchi a partire da project.start_date_estimated (o oggi)
    Salva start_date_planned / end_date_planned / crew_size_planned / hours_estimated per ciascun work.
    """
    db = get_db()
    proj = db["projects"].find_one({"id": pid}) or db["projects"].find_one({"_id": pid})
    if not proj:
        return jsonify({"error": "Progetto non trovato"}), 404

    works = list(proj.get("works") or [])
    if not works:
        return jsonify({"error": "Nessun lavoro nel progetto"}), 400

    # data di partenza (stima) del progetto
    start0 = proj.get("start_date_estimated") \
        or ((proj.get("meta_extra") or {}).get("estimate") or {}).get("start") \
        or datetime.utcnow().date().isoformat()

    # carica catalogo
    codes = list({ w.get("work_code") for w in works if w.get("work_code") })
    cat_docs = list(db["work_catalog"].find({"code": {"$in": codes}}))
    cat = { c["code"]: c for c in cat_docs }

    # crea mappa con prerequisiti
    g = { w["work_code"]: set(cat.get(w["work_code"], {}).get("prerequisites", [])) for w in works if w.get("work_code") }

    # topological sort semplice
    ordered = []
    seen = set()
    def visit(code):
        if code in seen: return
        for dep in g.get(code, []):
            if dep in cat: visit(dep)
        seen.add(code); ordered.append(code)
    for w in works:
        code = w.get("work_code")
        if code: visit(code)

    # indice lavoro per code
    by_code = { w["work_code"]: w for w in works if w.get("work_code") }

    # timeline lineare (puoi sofisticare in futuro con parallelismo)
    cursor = _to_date(start0)
    planned = []
    for code in ordered:
        w = by_code.get(code)
        c = cat.get(code)
        if not (w and c):  # voce mancante dal catalogo
            continue
        qty = float(w.get("qty") or 0)
        crew = int(w.get("crew_size_planned") or c.get("min_crew", 1))
        prod = float(c.get("productivity_per_worker_per_hour") or 1.0)
        hours = 0 if qty <= 0 else qty / (prod * max(1, crew))
        days = 0 if hours == 0 else max(1, int((hours/8)+0.999))  # arrotonda a giorni (8h)
        start_d = cursor
        end_d = cursor + timedelta(days=max(0, days-1))
        cursor = end_d + timedelta(days=1)

        # aggiorna i campi del work
        w["primary_role"] = w.get("primary_role") or c.get("primary_role")
        w["roles_allowed"] = w.get("roles_allowed") or c.get("roles_allowed", [])
        w["hours_estimated"] = hours
        w["crew_size_planned"] = crew
        w["start_date_planned"] = _to_str(start_d)
        w["end_date_planned"] = _to_str(end_d)
        planned.append(w)

    # salva
    db["projects"].update_one({"_id": proj["_id"]}, {"$set": {"works": planned}})
    return jsonify({"ok": True, "items": planned, "start_from": start0}), 200

# === AUTO-ASSIGN CON CALENDARIO ===
def _overlaps(a_from, a_to, b_from, b_to):
    return not (a_to < b_from or b_to < a_from)

def _is_worker_free(w: dict, start: str, end: str) -> bool:
    bookings = list(w.get("bookings") or [])
    if not start or not end:
        return True
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end,   "%Y-%m-%d")
    for b in bookings:
        try:
            bs = datetime.strptime(b.get("from"), "%Y-%m-%d")
            be = datetime.strptime(b.get("to"),   "%Y-%m-%d")
            if _overlaps(s, e, bs, be):
                return False
        except Exception:
            continue
    return True

@projworks_bp.post("/<pid>/schedule/assign")
def schedule_auto_assign(pid: str):
    """
    Assegna operai ai lavori pianificati (usa crew_size_planned, roles_allowed/primary_role).
    - Cerca solo operai liberi nell'intervallo [start_date_planned, end_date_planned].
    - Scrive bookings sul worker; opzionale: marca available=False se booking include 'oggi'.
    - Salva assegnazioni in project.meta_extra.assignments (append).
    """
    db = get_db()
    proj = db["projects"].find_one({"id": pid}) or db["projects"].find_one({"_id": pid})
    if not proj:
        return jsonify({"error": "Progetto non trovato"}), 404
    raw_state = str(proj.get("status") or proj.get("stato") or "").strip()
    # alias semplice: se arriva "Active" lo consideriamo equivalente ad "Attivo"
    alias = "Attivo" if raw_state == "Active" else raw_state
    if alias not in ALLOWED_ASSIGN_STATES:
        return jsonify({
            "error": f"Stato non consentito per l'assegnazione: {raw_state or 'N/D'}",
            "allowed": sorted(ALLOWED_ASSIGN_STATES),
        }), 409

    works = [w for w in (proj.get("works") or []) if w.get("start_date_planned") and w.get("end_date_planned")]
    if not works:
        return jsonify({"error": "Nessun lavoro pianificato (serve /plan)"}), 400

    # ordina temporalmente
    works.sort(key=lambda x: (x.get("start_date_planned"), x.get("end_date_planned")))

    # leggi tutti i worker
    workers = list(db["workers"].find({}))  # non solo available: guardiamo bookings
    by_role = {}
    for w in workers:
        role = (w.get("role") or "").strip().lower()
        by_role.setdefault(role, []).append(w)

    today = datetime.utcnow().date()

    assignments = []
    updated_workers = []
    for w in works:
        need = int(w.get("crew_size_planned") or 1)
        roles_allowed = [r.strip().lower() for r in (w.get("roles_allowed") or [])]
        primary = (w.get("primary_role") or "").strip().lower()
        if primary and primary not in roles_allowed:
            roles_allowed = [primary] + roles_allowed

        start = w.get("start_date_planned"); end = w.get("end_date_planned")
        taken = 0

        for role_needed in roles_allowed or ["operaio edile"]:
            pool = list(by_role.get(role_needed, []))
            # preferisci chi ha meno bookings
            pool.sort(key=lambda ww: len(ww.get("bookings") or []))
            for cand in pool:
                if taken >= need: break
                if _is_worker_free(cand, start, end):
                    # assegna
                    book = {
                        "project_id": str(proj.get("id") or proj.get("_id")),
                        "work_name": w.get("work_name"),
                        "from": start,
                        "to": end
                    }
                    new_bookings = list(cand.get("bookings") or [])
                    new_bookings.append(book)
                    db["workers"].update_one({"_id": cand["_id"]}, {"$set": {"bookings": new_bookings}})

                    # opzionale: se il periodo include oggi, marca non disponibile
                    try:
                        if datetime.strptime(start, "%Y-%m-%d").date() <= today <= datetime.strptime(end, "%Y-%m-%d").date():
                            db["workers"].update_one({"_id": cand["_id"]}, {"$set": {"available": False}})
                    except Exception:
                        pass

                    assignments.append({
                        "worker_id": cand.get("id") or str(cand.get("_id")),
                        "worker_name": cand.get("name"),
                        "role": role_needed,
                        "work_name": w.get("work_name"),
                        "start": start,
                        "end": end
                    })
                    taken += 1

            if taken >= need:
                break

    # salva su progetto
    me = dict(proj.get("meta_extra") or {})
    curr = list(me.get("assignments") or [])
    curr.extend(assignments)
    me["assignments"] = curr
    db["projects"].update_one({"_id": proj["_id"]}, {"$set": {"meta_extra": me}})

    # Calcola i deficits: lavori non completamente coperti
    deficits = []
    # indicizza assegnazioni per (work_code, work_name)
    def _key_for(a):
        return (a.get("work_code") or None, a.get("work_name") or None)

    assigned_map = {}
    for a in assignments:
        k = _key_for(a)
        assigned_map[k] = assigned_map.get(k, 0) + 1

    for w in works:
        need = int(w.get("crew_size_planned") or 1)
        wc = w.get("work_code")
        wn = w.get("work_name")
        k = (wc, wn)
        found = int(assigned_map.get(k, 0))
        if found < need:
            deficits.append({
                "work_code": wc,
                "work_name": wn,
                "needed": need,
                "found": found,
                "missing": need - found,
                "roles_allowed": w.get("roles_allowed") or [],
                "window": {
                    "start": w.get("start_date_planned"),
                    "end": w.get("end_date_planned"),
                },
            })

    return jsonify({
        "ok": True,
        "assigned": len(assignments),
        "items": assignments,
        "deficits": deficits,
    }), 200