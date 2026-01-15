# services/capacity.py
from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
try:
    from mongoengine.connection import get_db
except Exception:
    get_db = None

DateLike = str  # "YYYY-MM-DD"

def _daterange(d0: datetime, d1: datetime):
    cur = d0
    while cur <= d1:
        yield cur
        cur += timedelta(days=1)

def _parse_date(s: DateLike) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")

def _day_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")

def _load_assignments(role: str, start: DateLike, end: DateLike, site_id: str|None=None):
    db = get_db()
    q = {"role": {"$regex": role, "$options": "i"}, "dates": {"$exists": True}}
    if site_id:
        q["site_id"] = site_id
    cur = db["assignments"].find(q, {"_id":0,"worker_id":1,"role":1,"dates":1,"hours":1,"site_id":1})
    return list(cur)

def _load_workers(role: str, site_id: str|None=None):
    db = get_db()
    q = {"role": {"$regex": role, "$options": "i"}}
    cur = db["workers"].find(q, {"_id":0,"id":1,"name":1,"role":1,"available":1,"home_city":1,"skills":1})
    rows = list(cur)
    if site_id:
        # (opzionale) filtra per area/logistica
        pass
    return rows

def check_capacity(role: str, daily_hours: float, start: DateLike, end: DateLike, site_id: str|None=None) -> Dict[str,Any]:
    """
    Controlla se c'è capacità sufficiente per ruolo in [start,end] con 'daily_hours' per giorno.
    Ritorna: {ok, shortage_days[], suggestions:{date_alternatives[], worker_swaps[]}}
    """
    if not get_db:
        return {"ok": True, "note": "DB non disponibile, nessun controllo"}

    d0, d1 = _parse_date(start), _parse_date(end)
    span_days = [ _day_key(d) for d in _daterange(d0, d1) ]

    # 1) capacità grezza = n° lavoratori disponibili * 8h (parametrizzabile)
    workers = _load_workers(role, site_id)
    n_workers = sum(1 for w in workers if w.get("available") in (True, "true", "1", 1, "si", "sì"))
    daily_cap = n_workers * 8.0

    # 2) domanda = daily_hours (richiesta per giorno)
    demand = {day: daily_hours for day in span_days}

    # 3) sottrai ore già allocate
    asg = _load_assignments(role, start, end, site_id)
    used = {day: 0.0 for day in span_days}
    for a in asg:
        for day in (a.get("dates") or []):
            if day in used:
                used[day] += float(a.get("hours") or 0.0)

    shortage = []
    for day in span_days:
        free = max(0.0, daily_cap - used.get(day, 0.0))
        if free < demand[day]:
            shortage.append({"day": day, "needed": demand[day], "free": free})

    if not shortage:
        return {"ok": True, "shortage_days": [], "suggestions": {}}

    # 4) suggerisci alternative: a) spostamento date, b) swap lavoratori compatibili
    # a) prime 3 date successive con capienza
    alt_dates = []
    probe = d1 + timedelta(days=1)
    steps = 0
    while len(alt_dates) < 3 and steps < 14:  # guarda max 2 settimane oltre
        k = _day_key(probe)
        # ricalcola used del giorno di probe
        used_probe = 0.0
        for a in asg:
            if k in (a.get("dates") or []):
                used_probe += float(a.get("hours") or 0.0)
        free_probe = max(0.0, daily_cap - used_probe)
        if free_probe >= daily_hours:
            alt_dates.append(k)
        probe += timedelta(days=1)
        steps += 1

    # b) swap: elenca 5 lavoratori disponibili del ruolo
    swaps = [
        {"id": w.get("id"), "name": w.get("name")}
        for w in workers if w.get("available") in (True,"true","1",1,"si","sì")
    ][:5]

    return {
        "ok": False,
        "shortage_days": shortage,
        "suggestions": {
            "date_alternatives": alt_dates,
            "worker_swaps": swaps
        }
    }