from flask import Blueprint, jsonify, render_template, request
from models_mongo.worker import WorkerDoc
from datetime import datetime, timedelta

import subprocess, sys, os

from services.analytics_service import generate_and_save_report
from flask import abort

chat_analytics_bp = Blueprint("chat_analytics", __name__, url_prefix="/analytics")

def _db():
    return WorkerDoc._get_db()

# --- API: ultimi report (JSON) ---
@chat_analytics_bp.route("/reports", methods=["GET"])
def list_reports():
    limit = int(request.args.get("limit", 5))
    site_id = request.args.get("site_id")
    q = {}
    if site_id:
        q["site_id"] = site_id
    rows = list(_db()["chat_quality_reports"]
                .find(q)
                .sort("created_at", -1)
                .limit(limit))
    def _row(r):
        return {
            "id": str(r.get("_id")),
            "created_at": r.get("created_at"),
            "period_days": r.get("period_days"),
            "site_id": r.get("site_id"),
            "metrics": r.get("metrics") or {},
            "report": r.get("report") or "",
            "bad_examples": r.get("bad_examples") or [],
        }
    return jsonify([_row(r) for r in rows])

# --- API: summary KPI veloci (reuse di 6B se l’hai già) ---
@chat_analytics_bp.route("/summary", methods=["GET"])
def summary():
    db = _db()
    col = db["chat_analytics"]
    days = int(request.args.get("days", 7))
    since = datetime.utcnow() - timedelta(days=days)
    total = col.count_documents({})
    last = col.count_documents({"timestamp": {"$gte": since}})
    errors = col.count_documents({"had_error": True, "timestamp": {"$gte": since}})
    return jsonify({
        "total_chats": total,
        "last_days": days,
        "last_days_chats": last,
        "last_days_errors": errors,
        "error_rate": round(errors / last, 3) if last else 0.0
    })

# --- Pagina HTML: Statistiche (render server-side) ---
@chat_analytics_bp.route("/", methods=["GET"])
def analytics_page():
    db = _db()
    # KPI ultimi 7 giorni
    since = datetime.utcnow() - timedelta(days=7)
    col = db["chat_analytics"]
    total = col.count_documents({})
    last = col.count_documents({"timestamp": {"$gte": since}})
    errors = col.count_documents({"had_error": True, "timestamp": {"$gte": since}})

    # Ultimi 5 report qualità
    reports = list(db["chat_quality_reports"]
                   .find({})
                   .sort("created_at", -1)
                   .limit(5))

    return render_template(
        "analytics.html",
        kpi={
            "total_chats": total,
            "last_7d": last,
            "error_rate": (round(errors/last, 3) if last else 0.0)
        },
        reports=reports
    )


@chat_analytics_bp.route("/reports/generate", methods=["POST"])
def generate_report():
    # TODO: controlla permessi admin qui
    try:
        payload = request.get_json(silent=True) or {}
        days = int(payload.get("days") or request.args.get("days", 7))
        limit = int(payload.get("limit") or request.args.get("limit", 500))
        site_id = payload.get("site_id") or request.args.get("site_id")

        db = _db()
        doc = generate_and_save_report(db, days=days, limit=limit, site_id=site_id)
        # rispondi con info essenziali
        return jsonify({
            "ok": True,
            "id": doc.get("id"),
            "created_at": doc.get("created_at"),
            "period_days": doc.get("period_days"),
            "site_id": doc.get("site_id"),
            "metrics": {
                "total_chats": (doc.get("metrics") or {}).get("total_chats"),
                "error_rate": (doc.get("metrics") or {}).get("error_rate"),
            }
        }), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500