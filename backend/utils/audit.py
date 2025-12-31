# utils/audit.py
from datetime import datetime
from typing import Any
from mongoengine.connection import get_db

def audit_log(event: str, user_id: str | None, payload: dict[str, Any] | None = None):
    db = get_db()
    doc = {
        "event": event,
        "user_id": user_id,
        "payload": payload or {},
        "ts": datetime.utcnow(),
    }
    db["audit_logs"].insert_one(doc)