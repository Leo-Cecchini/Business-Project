# services/retrieval.py
from __future__ import annotations
from typing import Dict, Any, List

try:
    from mongoengine.connection import get_db
except Exception:
    get_db = None

def _fetch_docs(site_id: str) -> List[Dict[str, Any]]:
    if not get_db:
        return []
    db = get_db()
    # adatta i nomi collezioni ai tuoi
    cur = db["files"].find({"site_id": site_id}, {"_id": 0, "name": 1, "type": 1, "url": 1})
    return list(cur)

def _fetch_assignments(site_id: str) -> List[Dict[str, Any]]:
    if not get_db:
        return []
    db = get_db()
    cur = db["assignments"].find({"site_id": site_id}, {"_id": 0, "work_id": 1, "worker_id": 1, "role": 1, "dates": 1})
    return list(cur)

def _fetch_work_items(site_id: str) -> List[Dict[str, Any]]:
    if not get_db:
        return []
    db = get_db()
    cur = db["work_items"].find({"site_id": site_id}, {"_id": 0, "id": 1, "label": 1, "status": 1, "dates": 1})
    return list(cur)

def _fetch_project(site_id: str) -> Dict[str, Any]:
    if not get_db:
        return {}
    db = get_db()
    proj = db["projects"].find_one({"site_id": site_id}, {"_id": 0})
    return proj or {}

def build_context(site_id: str) -> Dict[str, Any]:
    """Compatto e pronto per il prompt."""
    return {
        "project": _fetch_project(site_id),
        "work_items": _fetch_work_items(site_id),
        "assignments": _fetch_assignments(site_id),
        "documents": _fetch_docs(site_id),
    }