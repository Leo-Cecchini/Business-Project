# services/telemetry.py
from __future__ import annotations
from typing import Dict, Any
from datetime import datetime, timezone
from threading import Thread
try:
    from mongoengine.connection import get_db
except Exception:
    get_db = None

def fire_and_forget(event: Dict[str, Any]):
    """Non blocca la risposta utente."""
    def _run():
        try:
            db = get_db()
            event["ts"] = datetime.now(timezone.utc)
            db["telemetry"].insert_one(event)
        except Exception:
            pass
    Thread(target=_run, daemon=True).start()

def log_estimate_quality(ctx: Dict[str,Any]):
    """
    ctx atteso:
      { "region":..., "city":..., "factors":[...],
        "items_count": N, "grand_total": float,
        "source": "preview|commit",
        "latency_ms": int,
        "parse_ok": bool, "had_error": bool }
    """
    fire_and_forget({"type":"estimate_quality", **ctx})

def log_assignment_attempt(ctx: Dict[str,Any]):
    """
    ctx: { "role":..., "start":..., "end":..., "ok": bool,
           "shortage_days": int, "suggested_dates": int }
    """
    fire_and_forget({"type":"assignment_attempt", **ctx})

def log_chat_metrics(ctx: Dict[str,Any]):
    """
    ctx: { "intent":..., "tokens_in":int, "tokens_out":int, "latency_ms":int,
           "parsed_items":int, "had_error":bool }
    """
    fire_and_forget({"type":"chat_metrics", **ctx})