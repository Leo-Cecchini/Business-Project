# routes/projects.py
from __future__ import annotations
import os
import uuid

from flask import Blueprint, request, jsonify, g, current_app
from werkzeug.utils import secure_filename

from models import db
from models.project import Project
from routes.company import company_overview  # per restituire KPI aggiornati

projects_bp = Blueprint("projects", __name__, url_prefix="/api/projects")


# ------------------------------- Utils -------------------------------

def _ensure_upload_dir(project_id: int) -> str:
    base = current_app.config.get("UPLOAD_FOLDER", "uploads")
    path = os.path.join(base, f"project_{project_id}")
    os.makedirs(path, exist_ok=True)
    return path

def _normalize_status(s: str | None) -> str:
    """
    Mappa varianti accettate allo standard dell'app:
    - 'Confermato' | 'confirmed' | 'attivo' | 'active' -> 'Confermato'
    - tutto il resto o None -> 'Preventivo'
    """
    if not s:
        return "Preventivo"
    s_low = s.strip().lower()
    if s_low in {"confermato", "confirmed", "attivo", "active"}:
        return "Confermato"
    if s_low in {"preventivo", "pending", "da approvare"}:
        return "Preventivo"
    # fallback sicuro
    return "Preventivo"


# ------------------------------- Endpoints -------------------------------

@projects_bp.get("")
def list_projects():
    """Lista dei cantieri (ordinati dal più recente)."""
    rows = Project.query.order_by(Project.id.desc()).all()
    return jsonify([p.to_dict() for p in rows])


@projects_bp.post("")
def create_project():
    """
    Crea un nuovo cantiere.
    Nota: normalizziamo lo status a 'Preventivo' o 'Confermato'.
    """
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nome cantiere mancante"}), 422

    p = Project(
        company_id=int(data.get("company_id") or 1),
        name=name,
        city=(data.get("city") or "").strip() or None,
        start_date=(data.get("start_date") or "").strip() or None,
        end_date=(data.get("end_date") or "").strip() or None,
        status=_normalize_status(data.get("status")),   # <<< normalizzazione
    )
    db.session.add(p)
    db.session.commit()

    # crea cartella upload per il cantiere
    _ensure_upload_dir(p.id)

    # puoi decidere se tornare l'overview già qui:
    # return company_overview(), 201
    return jsonify(p.to_dict()), 201


@projects_bp.delete("/<int:project_id>")
def delete_project(project_id: int):
    """Elimina un cantiere. (I file su disco non vengono rimossi in questa versione.)"""
    p = Project.query.get_or_404(project_id)
    db.session.delete(p)
    db.session.commit()
    # ritorna KPI aggiornati per aggiornare i contatori sul frontend
    return company_overview()


@projects_bp.get("/<int:project_id>/summary")
def project_summary(project_id: int):
    """Riepilogo del cantiere + elenco documenti su disco."""
    p = Project.query.get(project_id)
    if not p:
        return jsonify({"error": "Cantiere non trovato"}), 404

    folder = _ensure_upload_dir(project_id)
    docs = []
    if os.path.exists(folder):
        for fname in sorted(os.listdir(folder)):
            if fname.startswith("."):
                continue
            docs.append({"name": fname, "path": f"/uploads/project_{project_id}/{fname}"})

    return jsonify({
        "project": p.to_dict(),
        "documents": docs
    })


@projects_bp.get("/<int:project_id>/documents")
def project_documents_list(project_id: int):
    """Solo la lista documenti su disco (comodo per frontend)."""
    if not Project.query.get(project_id):
        return jsonify({"error": "Cantiere non trovato"}), 404

    folder = _ensure_upload_dir(project_id)
    docs = []
    if os.path.exists(folder):
        for fname in sorted(os.listdir(folder)):
            if fname.startswith("."):
                continue
            docs.append({"name": fname, "path": f"/uploads/project_{project_id}/{fname}"})
    return jsonify({"documents": docs})


@projects_bp.post("/<int:project_id>/documents")
def upload_project_document(project_id: int):
    """
    Carica un documento del cantiere:
    - salva su disco
    - indicizza nel vector store per la ricerca semantica (se componenti presenti)
    """
    p = Project.query.get(project_id)
    if not p:
        return jsonify({"error": "Cantiere non trovato"}), 404

    if "file" not in request.files:
        return jsonify({"error": "Nessun file in upload"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Nome file vuoto"}), 400

    # Salvataggio fisico
    folder = _ensure_upload_dir(project_id)
    filename = secure_filename(file.filename)
    # evita collisioni
    if os.path.exists(os.path.join(folder, filename)):
        stem, ext = os.path.splitext(filename)
        filename = f"{stem}-{uuid.uuid4().hex[:6]}{ext}"
    fpath = os.path.join(folder, filename)
    file.save(fpath)

    # Indicizzazione (se i componenti sono disponibili)
    file_processor = getattr(g, "file_processor", None)
    vector_store = getattr(g, "vector_store", None)
    if not file_processor or not vector_store:
        # non blocchiamo l'upload se manca l'indicizzazione
        return jsonify({"ok": True, "file": filename, "indexed": 0})

    try:
        chunks = file_processor.process(fpath)  # [(text, metadata), ...]
        texts = [t for (t, _) in chunks]
        metas = []
        for _, md in chunks:
            base_md = md or {}
            base_md["source"] = filename
            base_md["project_id"] = project_id
            metas.append(base_md)
        added = vector_store.add_documents(texts, metas)
    except Exception as e:
        # l'upload è andato a buon fine; fallisce solo l'indicizzazione
        return jsonify({"ok": True, "file": filename, "indexed": 0, "warning": f"Indicizzazione fallita: {e}"}), 207

    return jsonify({"ok": True, "indexed": added, "file": filename})


@projects_bp.post("/<int:pid>/status")
def toggle_status(pid: int):
    """
    Alterna lo stato del cantiere:
      - se 'Confermato' -> 'Preventivo'
      - altrimenti -> 'Confermato'
    Restituisce l'overview aggiornata per aggiornare i KPI sul frontend.
    """
    p = Project.query.get_or_404(pid)
    cur = (p.status or "").strip().lower()
    p.status = "Preventivo" if cur == "confermato" else "Confermato"
    db.session.commit()
    return company_overview()