# routes/computo.py
import logging
from flask import Blueprint, request, jsonify, send_file, current_app
import google.generativeai as genai

# Service
from services import ComputoService

log = logging.getLogger("computo_route")
computo_bp = Blueprint("computo", __name__, url_prefix="/api/projects")

# --- Helper AI Singleton (Configuration) ---
_json_model = None

def get_ai_model():
    """Recupera o inizializza il modello Gemini configurato per JSON."""
    global _json_model
    if _json_model:
        return _json_model
    
    api_key = current_app.config.get("GOOGLE_API_KEY")
    if not api_key:
        # Fallback env var
        import os
        api_key = os.getenv("GOOGLE_API_KEY")
        
    if not api_key:
        raise ValueError("API Key Google non configurata")
    
    genai.configure(api_key=api_key)
    generation_config = genai.GenerationConfig(response_mime_type="application/json")
    _json_model = genai.GenerativeModel('gemini-2.5-flash', generation_config=generation_config)
    return _json_model

# ============================================
# ENDPOINTS
# ============================================

@computo_bp.route("/<pid>/computo/upload", methods=["POST"])
def upload_computo_pdf(pid):
    """Upload PDF -> Estrazione AI -> Save DB."""
    if 'file' not in request.files:
        return jsonify({"error": "File mancante"}), 400
        
    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "Filename vuoto"}), 400

    try:
        model = get_ai_model()
        computo = ComputoService.process_pdf_upload(pid, file, model)
        return jsonify(computo.to_dict()), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        log.exception("Upload computo error")
        return jsonify({"error": str(e)}), 500


@computo_bp.route("/<pid>/computo/generate", methods=["POST"])
def generate_computo_ai(pid):
    """Descrizione -> Generazione AI -> Save DB."""
    data = request.get_json() or {}
    description = data.get("description")
    
    if not description:
        return jsonify({"error": "Descrizione mancante"}), 400
        
    try:
        model = get_ai_model()
        computo = ComputoService.generate_from_description(pid, description, model)
        return jsonify(computo.to_dict()), 201
    except Exception as e:
        log.exception("Generate computo error")
        return jsonify({"error": str(e)}), 500


@computo_bp.route("/<pid>/computo/plan", methods=["POST"])
def plan_works_from_computo(pid):
    """Latest Computo -> Work Pipeline -> Update Project Works."""
    data = request.get_json() or {}
    start_date = data.get("start_date")
    
    if not start_date:
        return jsonify({"error": "Data inizio (start_date) richiesta"}), 400
        
    try:
        # Per la pianificazione (sequenza lavori) vogliamo poter funzionare
        # anche senza API key (es. valutazione/professore). In quel caso il
        # ComputoProcessor userà una strategia di fallback deterministica.
        try:
            model = get_ai_model()
        except Exception:
            model = None

        works = ComputoService.plan_works_from_computo(pid, start_date, model)
        
        # Serializza i WorkItem
        works_json = [
            {
                "work_name": w.work_name,
                "status": w.status,
                "start": w.start_date_planned.isoformat() if w.start_date_planned else None,
                "end": w.end_date_planned.isoformat() if w.end_date_planned else None,
                "workers": w.number_of_workers
            } 
            for w in works
        ]
        return jsonify({"success": True, "works": works_json}), 200
        
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        log.exception("Plan works error")
        return jsonify({"error": str(e)}), 500
@computo_bp.route("/<pid>/lavori/generate", methods=["POST"])
def generate_lavori_alias(pid):
    """Alias per plan_works_from_computo - compatibilità frontend."""
    return plan_works_from_computo(pid)

@computo_bp.route("/<pid>/computo/latest", methods=["GET"])
def get_latest_computo(pid):
    try:
        computo = ComputoService.get_latest_computo(pid)
        if not computo:
            return jsonify({"error": "Nessun computo trovato"}), 404
        return jsonify(computo.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@computo_bp.route("/<pid>/computo/download", methods=["GET"])
def download_computo_pdf(pid):
    """Genera (se serve) e scarica il PDF del computo."""
    cid = request.args.get("computo_id")
    try:
        pdf_path = ComputoService.generate_pdf_report(pid, cid)
        return send_file(
            pdf_path, 
            as_attachment=True, 
            download_name=f"Computo_{pid}.pdf"
        )
    except Exception as e:
        log.exception("Download PDF error")
        return jsonify({"error": str(e)}), 500
@computo_bp.route("/<pid>/computo/pdf", methods=["POST"])
def generate_pdf_post(pid):
    """Alias POST per compatibilità frontend."""
    return download_computo_pdf(pid)
