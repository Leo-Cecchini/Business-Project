# routes/schedule.py
from flask import Blueprint, request, jsonify
from services import ScheduleService

schedule_bp = Blueprint("schedule", __name__, url_prefix="/api/schedule")

@schedule_bp.post("/capacity_check")
def capacity_check():
    """Verifica disponibilità per un periodo e ruolo."""
    data = request.get_json(force=True) or {}
    try:
        res = ScheduleService.check_capacity(
            start_str=data.get("start"),
            end_str=data.get("end"),
            role=data.get("role"),
            work_code=data.get("work_code"),
            crew_min=data.get("crew_min"),
            crew_roles_input=data.get("crew_roles"),
            region=data.get("region"),
            city=data.get("city"),
            require_foreman=data.get("require_foreman")
        )
        return jsonify(res)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 422
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ============================================
# DEPRECATI andavano in project
# ============================================

@schedule_bp.post("/auto_plan")
def auto_plan():
    """Genera piano lavori (simulazione)."""
    data = request.get_json(force=True) or {}
    try:
        res = ScheduleService.generate_plan(
            items=data.get("items", []),
            start_date=data.get("start"),
            region=data.get("region"),
            city=data.get("city"),
            daily_hours=data.get("daily_hours"),
            require_foreman=data.get("require_foreman")
        )
        return jsonify({"ok": True, **res})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 422
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@schedule_bp.post("/commit_plan")
def commit_plan():
    """Salva il piano generato."""
    data = request.get_json(force=True) or {}
    try:
        res = ScheduleService.commit_plan(
            project_id=data.get("project_id"),
            plan_data=data.get("plan"),
            site_id=data.get("site_id"),
            assign=bool(data.get("assign_now"))
        )
        return jsonify({"ok": True, **res})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 422
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500