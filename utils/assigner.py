from typing import List, Dict
from models.worker import Worker
import math

def _csv_set(s: str) -> set:
    return set([x.strip().lower() for x in (s or "").split(",") if x.strip()])

def score_worker(worker: Worker, req_role: str, req_skills: set, req_certs: set, site_city: str | None) -> float:
    s = 0.0
    # ruolo richiesto
    if req_role and (worker.role or "").lower() == req_role.lower():
        s += 2.0
    # competenze
    wskills = {sk.name.lower() for sk in worker.skills}
    s += 1.5 * len(req_skills & wskills)
    # certificazioni
    wcerts = _csv_set(worker.certifications)
    s += 1.0 * len(req_certs & wcerts)
    # prossimità (bonus se stessa città)
    if site_city and worker.home_city and worker.home_city.lower() == site_city.lower():
        s += 0.8
    # disponibilità
    avail = (worker.availability or "FT").upper()
    if avail == "OUT":
        s -= 3.0
    elif avail == "PT":
        s -= 0.3
    # costo (più basso = meglio) — normalizziamo ogni 5 €/h ~ -0.2
    if worker.hourly_rate:
        s -= 0.2 * (worker.hourly_rate / 5.0)
    # carico (meno carico = meglio)
    s -= 0.05 * (worker.current_load or 0.0)
    return round(s, 3)

def choose_workers(candidates: List[Worker], required_hours: float, req_role: str, req_skills: set, req_certs: set, site_city: str | None):
    """Greedy: ordina per punteggio e alloca ore fino a copertura."""
    scored = [(w, score_worker(w, req_role, req_skills, req_certs, site_city)) for w in candidates]
    scored.sort(key=lambda t: t[1], reverse=True)
    left = required_hours
    picks = []
    for w, sc in scored:
        if left <= 0:
            break
        if (w.availability or "FT").upper() == "OUT":
            continue
        # cap semplice: full-time 40h, part-time 20h, altrimenti 30h
        cap = 40 if (w.availability or "FT").upper() == "FT" else (20 if (w.availability or "FT").upper() == "PT" else 30)
        free = max(0.0, cap - (w.current_load or 0.0))
        if free <= 0:
            continue
        assign = min(free, left)
        picks.append({
            "worker_id": w.id,
            "name": w.name,
            "hours": round(assign, 1),
            "score": sc,
            "hourly_rate": w.hourly_rate,
            "home_city": w.home_city,
            "role": w.role,
        })
        left -= assign
    return picks, max(0.0, left)