# routes/chat_analytics.py
from flask import Blueprint, jsonify, request
from services.analytics_service import AnalyticsService

chat_analytics_bp = Blueprint("chat_analytics", __name__, url_prefix="/analytics")

@chat_analytics_bp.route("/reports", methods=["GET"])
def list_reports():
    """Lista report salvati (JSON)."""
    limit = int(request.args.get("limit", 5))
    site_id = request.args.get("site_id")
    
    # RIMOSSO 'db' dalla chiamata
    reports = AnalyticsService.list_reports(limit=limit, site_id=site_id)
    return jsonify(reports)

@chat_analytics_bp.route("/summary", methods=["GET"])
@chat_analytics_bp.route("/", methods=["GET"])
def summary():
    """KPI Dashboard in formato JSON."""
    days = int(request.args.get("days", 7))
    site_id = request.args.get("site_id")
    
    # RIMOSSO 'db' dalla chiamata
    stats = AnalyticsService.get_summary(days=days, site_id=site_id)
    
    return jsonify({
        "total_chats": stats.get("total_chats", 0),
        "last_days": stats.get("period_days", days),
        "last_days_chats": stats.get("period_chats", 0), 
        "period_errors": stats.get("period_errors", 0),
        "error_rate": stats.get("error_rate", 0.0)
    })

@chat_analytics_bp.route("/reports/generate", methods=["POST"])
def generate_report():
    try:
        payload = request.get_json(silent=True) or {}
        days = int(payload.get("days") or request.args.get("days", 7))
        limit = int(payload.get("limit") or request.args.get("limit", 500))
        site_id = payload.get("site_id") or request.args.get("site_id")

        # RIMOSSO 'db' dalla chiamata
        doc = AnalyticsService.generate_and_save_report(days=days, limit=limit, site_id=site_id)
        
        return jsonify({
            "ok": True,
            "id": doc.get("id"),
            "created_at": doc.get("created_at"),
            "metrics": doc.get("metrics")
        }), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    
@chat_analytics_bp.route("/reports/latest", methods=["GET"])
def get_latest_report():
    """Recupera l'ultimo report generato."""
    site_id = request.args.get("site_id")
    reports = AnalyticsService.list_reports(limit=1, site_id=site_id)
    
    if not reports:
        return jsonify({"ok": False, "error": "Nessun report disponibile"}), 404
    
    return jsonify({
        "ok": True,
        "report": reports[0]
    })