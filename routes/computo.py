# routes/computo.py
import os
import uuid
import json
import logging
from datetime import datetime, date # Assicura che 'date' sia importato
from flask import Blueprint, request, jsonify, g, current_app
from werkzeug.utils import secure_filename

import google.generativeai as genai

# Modelli DB
from models_mongo.project import ProjectDoc, WorkItem
from models_mongo.computo import ComputoDoc # <-- 1. IMPORTA IL NUOVO MODELLO

# Logica del Notebook
import utils.computo_processor as computo_processor

log = logging.getLogger("computo_api")
computo_bp = Blueprint("computo", __name__, url_prefix="/api/projects")

# --- Helper per Modello AI (JSON-ONLY) ---
_json_model = None
def get_json_model():
    global _json_model
    if _json_model:
        return _json_model
    try:
        api_key = current_app.config.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY non configurata nell'app Flask.")
        genai.configure(api_key=api_key)
        generation_config = genai.GenerationConfig(response_mime_type="application/json")
        model_name = 'gemini-2.5-pro'
        _json_model = genai.GenerativeModel(model_name, generation_config=generation_config)
        log.info(f"Modello GenAI (JSON-only) configurato: {model_name}")
        return _json_model
    except Exception as e:
        log.error(f"Impossibile configurare il modello GenAI (JSON-only): {e}", exc_info=True)
        return None

# --- Helpers FileSystem & Qdrant ---
def _ensure_project_upload_dir(project_id: str) -> str:
    base = current_app.config.get("UPLOAD_FOLDER", "uploads")
    path = os.path.join(base, f"project_{project_id}")
    os.makedirs(path, exist_ok=True)
    return path

def _save_to_qdrant(computo_data: dict, pid: str):
    vector_store = getattr(g, "vector_store", None)
    if not vector_store:
        log.warning("VectorStore non disponibile, skip indicizzazione Qdrant.")
        return
    try:
        text_content = json.dumps(computo_data, ensure_ascii=False)
        computo_id = computo_data.get("_id", "N/A")
        source_name = f"computo_metrico_{computo_id}.json"
        texts = [text_content]
        metas = [{"project_id": str(pid), "source": source_name, "document_id": computo_id}]
        vector_store.add_documents(texts, metas)
        log.info(f"Computo metrico {computo_id} indicizzato su Qdrant per progetto {pid}.")
    except Exception as e:
        log.error(f"Fallita indicizzazione Qdrant per progetto {pid}: {e}", exc_info=True)


# --- API Endpoints ---

@computo_bp.post("/<pid>/computo/upload")
def upload_computo(pid: str):
    """
    API 1: Carica PDF, estrae JSON, salva in 'ComputoDoc' 
    e AGGIUNGE l'ID all'array 'metric_computation_ids' del progetto.
    """
    project = ProjectDoc.objects(id=pid).first()
    if not project:
        return jsonify({"error": "Progetto non trovato"}), 404

    if "file" not in request.files: return jsonify({"error": "Nessun file in upload"}), 400
    file = request.files["file"]
    if file.filename == "": return jsonify({"error": "Nome file vuoto"}), 400

    model_json = get_json_model()
    if not model_json:
        return jsonify({"error": "Modello AI (JSON) non inizializzato."}), 500

    try:
        folder = _ensure_project_upload_dir(pid)
        filename = secure_filename(file.filename)
        fpath = os.path.join(folder, filename)
        file.save(fpath)

        computo_id = f"CME-{uuid.uuid4().hex[:8]}"
        
        if not filename.lower().endswith(".pdf"):
             return jsonify({"error": "Supportati solo file PDF."}), 415

        log.info(f"Avvio estrazione PDF per progetto {pid}, file: {filename}")
        
        computo_json = computo_processor.extract_computo_from_pdf(
            model=model_json, 
            pdf_path=fpath,
            document_id=computo_id
        )

        if not computo_json:
            return jsonify({"error": "Estrazione fallita."}), 500

        # --- 2. Salva in una collezione separata ---
        new_computo = ComputoDoc(
            id=computo_id,
            project_id=pid,
            data=computo_json,
            created_at=datetime.utcnow()
        )
        new_computo.save()

        # --- 3. AGGIUNGI (push) l'ID alla lista del progetto ---
        project.update(push__metric_computation_ids=computo_id)
        
        _save_to_qdrant(computo_json, pid)

        return jsonify(computo_json), 200

    except Exception as e:
        log.error(f"Errore in /computo/upload per progetto {pid}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@computo_bp.post("/<pid>/computo/generate")
def generate_computo(pid: str):
    """
    API 2: Genera JSON da testo, salva in 'ComputoDoc' 
    e AGGIUNGE l'ID all'array 'metric_computation_ids' del progetto.
    """
    project = ProjectDoc.objects(id=pid).first()
    if not project:
        return jsonify({"error": "Progetto non trovato"}), 404

    model_json = get_json_model()
    if not model_json:
        return jsonify({"error": "Modello AI (JSON) non inizializzato."}), 500

    data = request.get_json(force=True)
    description = data.get("description")
    if not description:
        return jsonify({"error": "La 'description' è obbligatoria."}), 400

    try:
        form_metadata = {
            "document_title": f"Preventivo per {project.name}",
            "subject": project.name,
            "client": "N/D", 
            "location": project.project_address or project.city or "N/D",
            "project_manager": "N/D",
            "technician": "N/D",
            "date": date.today().isoformat()
        }
        
        computo_id = f"CME-GEN-{uuid.uuid4().hex[:8]}"
        
        log.info(f"Avvio generazione CME per progetto {pid}...")
        
        computo_json = computo_processor.generate_computo_from_description(
            model=model_json, 
            project_description=description,
            metadata=form_metadata,
            document_id=computo_id
        )

        if not computo_json:
            return jsonify({"error": "Generazione fallita."}), 500

        # --- 2. Salva in una collezione separata ---
        new_computo = ComputoDoc(
            id=computo_id,
            project_id=pid,
            data=computo_json,
            created_at=datetime.utcnow()
        )
        new_computo.save()

        # --- 3. AGGIUNGI (push) l'ID alla lista del progetto ---
        project.update(push__metric_computation_ids=computo_id)
        
        _save_to_qdrant(computo_json, pid)
        
        folder = _ensure_project_upload_dir(pid)
        pdf_filename = f"computo_{computo_id}.pdf"
        pdf_path = os.path.join(folder, pdf_filename)
        
        computo_processor.create_pdf_report(computo_json, pdf_path)
        
        pdf_url = f"/uploads/project_{pid}/{pdf_filename}"

        return jsonify({
            "computo": computo_json,
            "pdf_report_url": pdf_url
        }), 200

    except Exception as e:
        log.error(f"Errore in /computo/generate per progetto {pid}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@computo_bp.post("/<pid>/lavori/generate")
def generate_lavori(pid: str):
    """
    API 3: Legge l'array di ID computo, prende l'ULTIMO ID,
    recupera il JSON da 'ComputoDoc' e genera la 'lista lavori'.
    """
    project = ProjectDoc.objects(id=pid).first()
    if not project:
        return jsonify({"error": "Progetto non trovato"}), 404

    model_json = get_json_model()
    if not model_json:
        return jsonify({"error": "Modello AI (JSON) non inizializzato."}), 500
        
    data = request.get_json(force=True)
    start_date = data.get("start_date")
    if not start_date:
        return jsonify({"error": "'start_date' (YYYY-MM-DD) è obbligatoria."}), 400

    try:
        # --- 1. Trova l'ULTIMO computo_id ---
        if not project.metric_computation_ids:
            return jsonify({"error": "Nessun computo metrico trovato. Caricare o generare prima un computo."}), 404
        
        latest_computo_id = project.metric_computation_ids[-1]
        
        # --- 2. Recupera il ComputoDoc dalla collezione separata ---
        computo_doc = ComputoDoc.objects(id=latest_computo_id).first()
        if not computo_doc or not computo_doc.data:
            return jsonify({"error": f"ID computo {latest_computo_id} non trovato nel database."}), 404
            
        computo_data = computo_doc.data # Usa il JSON dal documento collegato
        
        log.info(f"Avvio generazione pipeline lavori per progetto {pid} (usa Computo ID: {latest_computo_id})...")
        
        work_pipeline_json = computo_processor.generate_work_pipeline(
            model=model_json,
            metric_data=computo_data,
            start_date=start_date
        )
        
        if not work_pipeline_json:
            return jsonify({"error": "Generazione pipeline fallita."}), 500
            
        work_items = [WorkItem(**item) for item in work_pipeline_json]
        
        # --- 3. Salva la pipeline nel progetto ---
        project.update(
            set__works=work_items,
            set__status="planned"
        )
        
        project.reload()
        
        return jsonify(project.to_mongo().to_dict()), 200

    except Exception as e:
        log.error(f"Errore in /lavori/generate per progetto {pid}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500