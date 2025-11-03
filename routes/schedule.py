from flask import Blueprint, request, jsonify
from mongoengine.connection import get_db
from datetime import datetime, timedelta
import math
from collections import defaultdict, deque
from uuid import uuid4

# Manteniamo la telemetria esistente
try:
    from services.telemetry import log_assignment_attempt
except Exception:  # fallback soft
    def log_assignment_attempt(*args, **kwargs):
        return None

schedule_bp = Blueprint("schedule", __name__, url_prefix="/api/schedule")

# ----------------------
# Helpers
# ----------------------

def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def _daterange(d0: datetime, d1: datetime):
    cur = d0
    while cur <= d1:
        yield cur
        cur += timedelta(days=1)


def _crew_from_catalog(db, work_code: str):
    """Recupera min_crew/crew_roles dal work_catalog (case-insensitive)."""
    if not work_code:
        return {}
    proj = {"_id": 0, "min_crew": 1, "crew_roles": 1}
    doc = db["work_catalog"].find_one({"code": {"$regex": f"^{work_code}$", "$options": "i"}}, proj)
    if not doc:
        return {}
    out = {}
    if isinstance(doc.get("crew_roles"), dict) and doc["crew_roles"]:
        out["crew_roles"] = {str(k).lower(): int(v) for k, v in doc["crew_roles"].items() if isinstance(v, (int, float))}
    if isinstance(doc.get("min_crew"), (int, float)):
        out["min_crew"] = int(doc["min_crew"])
    return out


def _find_free_ids_for_role(db, role: str, region: str | None, city: str | None):
    """Ritorna lista di id worker disponibili per ruolo/geo (proxy: available==True)."""
    filt = {"available": True, "role": {"$regex": f"^{role}$", "$options": "i"}}
    if region:
        filt["home_region"] = {"$regex": f"^{region}$", "$options": "i"}
    if city:
        filt["home_city"] = {"$regex": f"^{city}$", "$options": "i"}
    cur = db["workers"].find(filt, {"_id": 0, "id": 1})
    return [w.get("id") for w in cur if w.get("id")]

# ----------------------
# Assignments helpers
# ----------------------

def _overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return not (a_end < b_start or b_end < a_start)


def _parse_date_any(s):
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except Exception:
        return None


def _busy_workers_in_range(db, start: datetime, end: datetime):
    """Ritorna set di worker_id occupati per ruolo nel range [start,end] secondo la collezione assignments."""
    out = defaultdict(set)  # role -> {worker_id}
    cur = db["assignments"].find({}, {"_id":0, "worker_id":1, "role":1, "start":1, "end":1})
    for a in cur:
        s = _parse_date_any(a.get("start"))
        e = _parse_date_any(a.get("end"))
        if not s or not e:
            continue
        if _overlap(s, e, start, end):
            role = (a.get("role") or "").lower()
            wid = a.get("worker_id")
            if role and wid:
                out[role].add(wid)
    return out


def _filter_free_for_range(candidates: list[str], busy_set: set[str]) -> list[str]:
    return [wid for wid in candidates if wid not in busy_set]


# ----------------------
# Planning helpers (durations, ordering, assignment)
# ----------------------

def _get_productivity(db, work_code: str):
    """Ritorna produttivita' per singolo operaio (unita'/ora) e unita' di misura.
    Schema atteso nel catalogo: productivity_per_worker_per_hour (float), unit (str).
    """
    if not work_code:
        return None, None
    doc = db["work_catalog"].find_one(
        {"code": {"$regex": f"^{work_code}$", "$options": "i"}},
        {"_id":0, "productivity_per_worker_per_hour":1, "unit":1}
    )
    if not doc:
        return None, None
    return doc.get("productivity_per_worker_per_hour"), doc.get("unit")


def _estimate_duration_days(qty: float, prod_per_worker_per_hour: float | None, crew_size: int, daily_hours: int) -> int:
    """Durata (giorni interi) = ceil( qty / (prod * crew * daily_hours) ). Se prod mancante, usa 1 giorno di default."""
    try:
        qty = float(qty or 0)
        crew_size = max(1, int(crew_size or 1))
        daily_hours = max(1, int(daily_hours or 8))
        if not prod_per_worker_per_hour or prod_per_worker_per_hour <= 0:
            return 1
        tot_hours = qty / (prod_per_worker_per_hour * crew_size)
        days = math.ceil(tot_hours / daily_hours)
        return max(1, int(days))
    except Exception:
        return 1


def _simple_topo_order(db, items: list[dict]) -> list[int]:
    """Ordina gli indici delle lavorazioni in base ai prerequisiti dichiarati nel catalogo.
    Se mancano work_code o prerequisiti, mantiene l'ordine d'ingresso.
    """
    # mappa code -> index list
    code_to_idxs = defaultdict(list)
    for i, it in enumerate(items):
        wc = (it.get("work_code") or "").strip()
        if wc:
            code_to_idxs[wc.upper()].append(i)
    # build graph
    N = len(items)
    indeg = [0]*N
    adj = [[] for _ in range(N)]
    for i, it in enumerate(items):
        wc = (it.get("work_code") or "").strip()
        if not wc:
            continue
        pres = _get_prerequisites(get_db(), wc) or []
        for p in pres:
            for j in code_to_idxs.get(p.upper(), []):
                # j (prereq) -> i (task)
                adj[j].append(i)
                indeg[i] += 1
    # Kahn
    q = deque([i for i in range(N) if indeg[i] == 0])
    out = []
    while q:
        u = q.popleft()
        out.append(u)
        for v in adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)
    if len(out) == N:
        return out
    # cicli o info mancanti -> fallback ordine naturale
    return list(range(N))


# ----------------------
# Endpoint principale
# ----------------------

@schedule_bp.post("/capacity_check")
def capacity_check():
    data = request.get_json(force=True) or {}

    # Finestre temporali
    try:
        start = _parse_date(data.get("start"))
        end = _parse_date(data.get("end"))
    except Exception:
        return jsonify({"ok": False, "error": "start/end (YYYY-MM-DD) richiesti"}), 422

    # Filtri geografici opzionali
    region = (data.get("region") or "").strip() or None
    city = (data.get("city") or "").strip() or None

    # Crew richiesti (si può specificare in 3 modi)
    crew_roles: dict[str, int] = {}

    db = get_db()

    # C) Da catalogo (work_code)
    work_code = (data.get("work_code") or "").strip()
    if work_code:
        cat = _crew_from_catalog(db, work_code)
        if cat.get("crew_roles"):
            crew_roles.update(cat["crew_roles"])  # multi-ruolo dal catalogo
        elif cat.get("min_crew") and data.get("role"):
            # fallback: se esiste solo min_crew, replica lo stesso ruolo N volte
            crew_roles[str(data.get("role")).lower()] = int(cat["min_crew"])

    # B) Esplicito nel body (multi-ruolo)
    if isinstance(data.get("crew_roles"), dict):
        for k, v in data["crew_roles"].items():
            try:
                crew_roles[str(k).lower()] = int(v)
            except Exception:
                pass

    # A) Semplice (un ruolo + crew_min)
    role = (data.get("role") or "").strip().lower()
    if role and not crew_roles:
        crew_min = int(data.get("crew_min") or 1)
        crew_roles[role] = crew_min

    # Capo cantiere obbligatorio (default True): 1 unità sempre richiesta sul periodo
    require_foreman = data.get("require_foreman")
    require_foreman = True if require_foreman is None else bool(require_foreman)
    if require_foreman:
        crew_roles["capo cantiere"] = max(1, int(crew_roles.get("capo cantiere", 0)))

    if not crew_roles:
        return jsonify({"ok": False, "error": "specifica work_code o crew_roles o role/crew_min"}), 422

    # Calcolo disponibilità per giorno/ruolo (proxy: available==True)
    # TODO: quando esisteranno assignment/agenda, escludere le date già impegnate
    role_to_ids = {r: _find_free_ids_for_role(db, r, region, city) for r in crew_roles.keys()}

    shortage_days = []
    for day in _daterange(start, end):
        day_str = day.strftime("%Y-%m-%d")
        day_ok = True
        roles_report = []
        for r, needed in crew_roles.items():
            free_count = len(role_to_ids.get(r, []))
            enough = free_count >= int(needed)
            roles_report.append({"role": r, "free": free_count, "needed": int(needed), "ok": enough})
            if not enough:
                day_ok = False
        if not day_ok:
            shortage_days.append({"day": day_str, "roles": roles_report})

    ok = len(shortage_days) == 0

    # Suggerimento basico: slitta di 7 giorni se non ok e se numericamente sembra fattibile
    suggestions = {"date_alternatives": [], "worker_swaps": []}
    if not ok:
        alt_start = start + timedelta(days=7)
        alt_end = end + timedelta(days=7)
        # NOTE: usiamo lo stesso snapshot numerico
        alt_ok = True
        for day in _daterange(alt_start, alt_end):
            for r, needed in crew_roles.items():
                if len(role_to_ids.get(r, [])) < int(needed):
                    alt_ok = False
                    break
            if not alt_ok:
                break
        if alt_ok:
            suggestions["date_alternatives"].append({
                "start": alt_start.strftime("%Y-%m-%d"),
                "end": alt_end.strftime("%Y-%m-%d"),
                "reason": "squadra minima disponibile"
            })

    # Telemetria non bloccante
    try:
        role_str = role or ",".join([f"{k}:{v}" for k, v in crew_roles.items()])
        log_assignment_attempt({
            "role": role_str,
            "start": data.get("start"),
            "end": data.get("end"),
            "ok": ok,
            "shortage_days": len(shortage_days),
            "suggested_dates": len(suggestions.get("date_alternatives") or []),
        })
    except Exception:
        pass

    return jsonify({
        "ok": ok,
        "work_code": work_code or None,
        "crew_roles": crew_roles,
        "require_foreman": require_foreman,
        "period": {"start": data.get("start"), "end": data.get("end")},
        "region": region,
        "city": city,
        "shortage_days": shortage_days,
        "suggestions": suggestions,
    }), 200


# ----------------------
# Auto-plan endpoint
# ----------------------

@schedule_bp.post("/auto_plan")
def auto_plan():
    """Pianifica una sequenza di lavorazioni rispettando prerequisiti, squadra minima e capocantiere.
    Non scrive sul DB: restituisce un piano "tentativo" con assegnazioni per ruolo.

    Body esempio:
    {
      "start": "2025-11-17",
      "region": "Lazio",
      "city": "Roma",
      "daily_hours": 8,
      "require_foreman": true,
      "items": [
        {"work_code":"MASS_ETTO", "qty":120, "unit":"m2"},
        {"work_code":"ELEC_ROUGH", "qty":40,  "unit":"pz"},
        {"work_code":"PLUMB_ROUGH","qty":20,  "unit":"pz"},
        {"work_code":"FLOOR_TILE", "qty":120, "unit":"m2"}
      ]
    }
    """
    db = get_db()
    data = request.get_json(force=True) or {}

    try:
        cur_day = _parse_date(data.get("start"))
    except Exception:
        return jsonify({"ok": False, "error": "start (YYYY-MM-DD) richiesto"}), 422

    region = (data.get("region") or "").strip() or None
    city   = (data.get("city") or "").strip() or None
    daily_hours = int(data.get("daily_hours") or 8)
    require_foreman = True if data.get("require_foreman") is None else bool(data.get("require_foreman"))

    items = data.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "error": "items[] richiesto"}), 422

    # Risolve crew requirements per ogni item
    enriched = []
    for it in items:
        wc = (it.get("work_code") or "").strip()
        qty = it.get("qty")
        unit = it.get("unit")
        if not wc:
            return jsonify({"ok": False, "error": "ogni item richiede work_code"}), 422
        crew = _crew_from_catalog(db, wc)
        crew_roles = crew.get("crew_roles") or {}
        if not crew_roles and crew.get("min_crew"):
            # fallback generico: un solo ruolo dal primary_role non sempre disponibile qui -> richiede specifica
            crew_roles = {}
        prod, cat_unit = _get_productivity(db, wc)
        enriched.append({
            "work_code": wc,
            "qty": qty,
            "unit": unit or cat_unit,
            "crew_roles": crew_roles,
            "prod": prod,
        })

    order = _simple_topo_order(db, enriched)

    # stato disponibilità locale (per questa pianificazione) -> evito riuso nello stesso slot
    local_reserved = defaultdict(lambda: defaultdict(set))
    # es: local_reserved["2025-11-18"]["elettricista"] = {"W-1001","W-1002"}

    plan = []
    warnings = []

    for idx in order:
        it = enriched[idx]
        wc = it["work_code"]
        qty = float(it.get("qty") or 0)
        unit = it.get("unit")
        crew_roles = dict(it.get("crew_roles") or {})

        # capo cantiere sempre
        if require_foreman:
            crew_roles["capo cantiere"] = max(1, int(crew_roles.get("capo cantiere", 0)))

        # stima durata con crew size = somma delle quantità richieste (senza contare capocantiere)
        crew_size_for_prod = sum(v for k, v in crew_roles.items() if k != "capo cantiere") or 1
        duration_days = _estimate_duration_days(qty, it.get("prod"), crew_size_for_prod, daily_hours)

        # trova il primo slot consecutivo con disponibilità sufficiente per TUTTI i ruoli
        start_day = None
        assigned = defaultdict(list)  # role -> worker_ids
        check_day = cur_day
        # ricerchiamo avanzando nel calendario finché troviamo un blocco valido
        while True:
            slot_ok = True
            # controlla ogni giorno nel potenziale range [check_day, check_day+duration_days-1]
            temp_selection = {d: {r: [] for r in crew_roles} for d in range(duration_days)}
            for offset in range(duration_days):
                day = (check_day + timedelta(days=offset)).strftime("%Y-%m-%d")
                for role, needed in crew_roles.items():
                    # lista di liberi dal DB (proxy available + geo)
                    candidates = _find_free_ids_for_role(db, role, region, city)
                    # rimuovi quelli già riservati localmente in quello stesso giorno
                    already = local_reserved[day][role]
                    free = [wid for wid in candidates if wid not in already]
                    if len(free) < int(needed):
                        slot_ok = False
                        break
                    temp_selection[offset][role] = free[:int(needed)]
                if not slot_ok:
                    break
            if slot_ok:
                start_day = check_day
                # conferma la prenotazione locale
                for offset in range(duration_days):
                    day = (start_day + timedelta(days=offset)).strftime("%Y-%m-%d")
                    for role, ids in temp_selection[offset].items():
                        for wid in ids:
                            local_reserved[day][role].add(wid)
                            if wid not in assigned[role]:
                                assigned[role].append(wid)
                break
            else:
                check_day = check_day + timedelta(days=1)
                # safety net per evitare loop infinito su datasets vuoti
                if (check_day - cur_day).days > 365:
                    warnings.append({"work_code": wc, "reason": "no_slot_with_capacity_within_1y"})
                    break

        if start_day is None:
            # non pianificabile ora
            plan.append({
                "work_code": wc,
                "qty": qty,
                "unit": unit,
                "status": "unscheduled",
                "reason": "capacity_or_staffing",
                "crew_roles": crew_roles,
            })
            continue

        end_day = start_day + timedelta(days=duration_days-1)
        plan.append({
            "work_code": wc,
            "qty": qty,
            "unit": unit,
            "status": "planned",
            "start": start_day.strftime("%Y-%m-%d"),
            "end": end_day.strftime("%Y-%m-%d"),
            "duration_days": duration_days,
            "crew_roles": crew_roles,
            "assigned": assigned,
        })
        # aggiorna cursore al giorno successivo alla fine di questo lavoro (esecuzione sequenziale per prerequisiti)
        cur_day = end_day + timedelta(days=1)

    return jsonify({
        "ok": True,
        "region": region,
        "city": city,
        "daily_hours": daily_hours,
        "require_foreman": require_foreman,
        "plan": plan,
        "warnings": warnings
    }), 200

# ----------------------
# Commit plan endpoint
# ----------------------

@schedule_bp.post("/commit_plan")
def commit_plan():
    """Conferma un piano generato da /auto_plan e lo salva nel progetto.
    Opzionalmente crea anche le assegnazioni dei lavoratori.

    Body atteso:
    {
      "project_id": "PRJ123",              # obbligatorio
      "site_id": "SITE_A",                # opzionale
      "assign_now": true,                   # opzionale (default false)
      "plan": [ { ... output di /auto_plan ... } ]
    }
    """
    db = get_db()
    data = request.get_json(force=True) or {}

    project_id = (data.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"ok": False, "error": "project_id richiesto"}), 422

    plan = data.get("plan") or []
    if not isinstance(plan, list) or not plan:
        return jsonify({"ok": False, "error": "plan[] richiesto (output di /auto_plan)"}), 422

    site_id = (data.get("site_id") or "").strip() or None
    assign_now = bool(data.get("assign_now") or False)

    # Normalizza e assegna un plan_id
    plan_id = f"PLAN-{uuid4().hex[:8].upper()}"
    saved_items = []

    for it in plan:
        if not isinstance(it, dict):
            continue
        status = it.get("status")
        if status != "planned":
            # salviamo solo le attività pianificate
            continue
        saved_items.append({
            "plan_id": plan_id,
            "work_code": it.get("work_code"),
            "qty": it.get("qty"),
            "unit": it.get("unit"),
            "start": it.get("start"),
            "end": it.get("end"),
            "duration_days": it.get("duration_days"),
            "crew_roles": it.get("crew_roles"),
            "assigned": it.get("assigned"),
            "site_id": site_id,
        })

    if not saved_items:
        return jsonify({"ok": False, "error": "nessuna attività pianificata nel plan"}), 422

    # Salva nel progetto (preferiamo project_drafts; se non esiste, proviamo projects)
    upd = {"$push": {"schedule": {"$each": saved_items}}}
    res = db["project_drafts"].update_one({"id": project_id}, upd)
    if res.matched_count == 0:
        res = db["projects"].update_one({"id": project_id}, upd)
    if res.matched_count == 0:
        # crea bozza progetto minima
        db["project_drafts"].update_one({"id": project_id}, {"$set": {"id": project_id}, "$push": {"schedule": {"$each": saved_items}}}, upsert=True)

    created_assignments = []

    if assign_now:
        # Crea documenti in collezione assignments (idempotenza: usa plan_id+work_code+day+role+wid)
        for it in saved_items:
            # assigned: dict role -> [worker_ids]
            assigned = it.get("assigned") or {}
            start = it.get("start")
            end = it.get("end")
            for role, wids in (assigned.items() if isinstance(assigned, dict) else []):
                for wid in wids:
                    doc_id = f"A-{plan_id}-{it.get('work_code','')}-{role}-{wid}-{start}-{end}"
                    db["assignments"].update_one(
                        {"id": doc_id},
                        {"$set": {
                            "id": doc_id,
                            "plan_id": plan_id,
                            "project_id": project_id,
                            "site_id": site_id,
                            "work_code": it.get("work_code"),
                            "role": role,
                            "worker_id": wid,
                            "start": start,
                            "end": end,
                        }},
                        upsert=True
                    )
                    created_assignments.append(doc_id)

        # NOTA: non forziamo workers.available=False; lasciamo che il capacity_check evoluto legga assignments per data

    return jsonify({
        "ok": True,
        "project_id": project_id,
        "plan_id": plan_id,
        "saved_items": len(saved_items),
        "assignments_created": len(created_assignments),
        "site_id": site_id,
    }), 200


# ----------------------
# Assign workers to saved plan
# ----------------------

@schedule_bp.post("/assign")
def assign_workers_to_plan():
    """Assegna automaticamente i lavoratori alle attività salvate nello schedule del progetto.

    Body:
    {
      "project_id": "PRJ123",        # obbligatorio
      "plan_id": "PLAN-XXXX",        # opzionale (se assente, prende tutte le voci senza assignment)
      "region": "Lazio",              # opzionale (filtra i candidati)
      "city": "Roma",                 # opzionale (filtra i candidati)
      "require_foreman": true          # default True (aggiunge/impone 1 capocantiere)
    }
    """
    db = get_db()
    data = request.get_json(force=True) or {}

    project_id = (data.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"ok": False, "error": "project_id richiesto"}), 422

    plan_id = (data.get("plan_id") or "").strip() or None
    region = (data.get("region") or "").strip() or None
    city   = (data.get("city") or "").strip() or None
    require_foreman = True if data.get("require_foreman") is None else bool(data.get("require_foreman"))

    # Carica lo schedule salvato (project_drafts prior, poi projects)
    proj = db["project_drafts"].find_one({"id": project_id}) or db["projects"].find_one({"id": project_id})
    if not proj:
        return jsonify({"ok": False, "error": "progetto non trovato"}), 404

    schedule_items = list(proj.get("schedule") or [])
    if not schedule_items:
        return jsonify({"ok": False, "error": "nessuna voce di schedule nel progetto"}), 404

    # Filtra per plan_id se fornito
    if plan_id:
        schedule_items = [it for it in schedule_items if (it.get("plan_id") == plan_id)]
        if not schedule_items:
            return jsonify({"ok": False, "error": "plan_id non trovato nello schedule"}), 404

    # Raccogli assegnazioni esistenti (per idempotenza)
    existing = set()
    cur = db["assignments"].find({"project_id": project_id}, {"_id":0, "id":1})
    for a in cur:
        if a.get("id"):
            existing.add(a["id"])

    created = []
    skipped = []

    for it in schedule_items:
        start = _parse_date_any(it.get("start"))
        end   = _parse_date_any(it.get("end"))
        if not start or not end:
            skipped.append({"work_code": it.get("work_code"), "reason": "missing_dates"})
            continue

        crew_roles = dict(it.get("crew_roles") or {})
        if require_foreman:
            crew_roles["capo cantiere"] = max(1, int(crew_roles.get("capo cantiere", 0)))

        # lavoratori occupati nel range (per ruolo)
        busy = _busy_workers_in_range(db, start, end)

        assigned_any = False
        for role, needed in crew_roles.items():
            # candidati liberi per ruolo/geo
            candidates = _find_free_ids_for_role(db, role, region, city)
            # escludi occupati nel range
            free_candidates = _filter_free_for_range(candidates, busy.get(role, set()))
            take = free_candidates[: int(needed)]
            if len(take) < int(needed):
                skipped.append({
                    "work_code": it.get("work_code"),
                    "role": role,
                    "needed": int(needed),
                    "available": len(free_candidates),
                    "reason": "not_enough_free_workers"
                })
                # non blocchiamo: assegniamo quanto disponibile (parziale)
            for wid in take:
                doc_id = f"A-{it.get('plan_id','PLAN')}-{it.get('work_code','')}-{role}-{wid}-{it.get('start')}-{it.get('end')}"
                if doc_id in existing:
                    continue
                db["assignments"].update_one(
                    {"id": doc_id},
                    {"$set": {
                        "id": doc_id,
                        "plan_id": it.get("plan_id"),
                        "project_id": project_id,
                        "site_id": it.get("site_id"),
                        "work_code": it.get("work_code"),
                        "role": role,
                        "worker_id": wid,
                        "start": it.get("start"),
                        "end": it.get("end"),
                    }},
                    upsert=True
                )
                existing.add(doc_id)
                created.append(doc_id)
                assigned_any = True

        # opzionale: potremmo aggiornare lo schedule con un flag "assigned": true/false
        # (lasciamo al frontend decidere se farlo in un update separato)

    return jsonify({
        "ok": True,
        "project_id": project_id,
        "plan_id": plan_id,
        "assignments_created": len(created),
        "partial_skips": skipped
    }), 200
    