# routes/company.py
from __future__ import annotations
import os
import uuid
from datetime import date
from typing import List, Dict

from flask import Blueprint, jsonify, request, current_app, g
from werkzeug.utils import secure_filename

from models_mongo.worker import WorkerDoc
from models_mongo.project import ProjectDoc
from models_mongo.material import MaterialDoc

company_bp = Blueprint("company", __name__, url_prefix="/api/company")


# ---------------------------------------------------------------------
# Helpers filesystem per documenti aziendali
# ---------------------------------------------------------------------
def _company_upload_dir() -> str:
    base = current_app.config.get("UPLOAD_FOLDER", "uploads")
    path = os.path.join(base, "company")
    os.makedirs(path, exist_ok=True)
    return path


def _list_company_docs() -> List[Dict[str, str]]:
    folder = _company_upload_dir()
    out: List[Dict[str, str]] = []
    if os.path.exists(folder):
        for fname in sorted(os.listdir(folder)):
            if fname.startswith("."):
                continue
            out.append({"name": fname, "path": f"/uploads/company/{fname}"})
    return out


# ---------------------------------------------------------------------
# KPI Overview
# ---------------------------------------------------------------------
@company_bp.get("/overview")
def company_overview():
    """
    KPI aziendali aggregati:
      - workers_total:   totale operai
      - projects_total:  tutti i progetti
      - documents_total: documenti aziendali (uploads/company)
      - active_projects: progetti 'Confermato'
      - active_workers:  operai disponibili (available = 1)
      - roles_breakdown: conteggio per ruolo
      - active_projects_list: ultimi nomi progetti confermati
    """
    today = date.today()

    # Operai totali
    try:
        workers_total = WorkerDoc.objects.count()
    except Exception:
        workers_total = 0

    # Progetti totali
    try:
        projects_total = ProjectDoc.objects.count()
    except Exception:
        projects_total = 0

    # Materiali totali
    try:
        materials_total = MaterialDoc.objects.count()
    except Exception:
        materials_total = 0

    # Progetti confermati (case-insensitive: "Confermato")
    try:
        active_projects = ProjectDoc.objects(status__iexact="Confermato").count()
    except Exception:
        active_projects = 0

    # Lista nomi progetti confermati (max 10)
    try:
        active_projects_list = [
            getattr(p, "name", None)
            for p in ProjectDoc.objects(status__iexact="Confermato").only("name").order_by("-id").limit(10)
        ]
    except Exception:
        active_projects_list = []

    # Ruoli (tutti) con conteggio e disponibili
    try:
        col = WorkerDoc._get_collection()
        agg_total = list(col.aggregate([{ "$group": { "_id": "$role", "count": { "$sum": 1 } } }]))
        roles_breakdown = { (r.get("_id") or "Senza ruolo"): int(r.get("count", 0)) for r in agg_total }
    except Exception:
        roles_breakdown = {}

    # Operai disponibili (available = True)
    try:
        active_workers = WorkerDoc.objects(available=True).count()
    except Exception:
        active_workers = 0

    # Documenti aziendali (FS)
    documents_total = len(_list_company_docs())

    return jsonify(
        dict(
            workers_total=workers_total,
            projects_total=projects_total,
            materials_total=materials_total,
            documents_total=documents_total,
            active_projects=active_projects,
            active_workers=active_workers,
            roles_breakdown=roles_breakdown,
            active_projects_list=active_projects_list,
        )
    )


# ---------------------------------------------------------------------
# Documenti aziendali
# ---------------------------------------------------------------------
@company_bp.get("/documents")
def list_company_documents():
    """Ritorna l'elenco dei documenti aziendali (FS)."""
    return jsonify({"documents": _list_company_docs()})


@company_bp.post("/documents")
def upload_company_document():
    """
    Carica un documento aziendale condiviso tra tutti i cantieri.
    - salva su uploads/company/
    - indicizza nel vector store (se presente)
    - ritorna l'overview aggiornata (così il frontend aggiorna i KPI subito)
    """
    if "file" not in request.files:
        return jsonify({"error": "Nessun file in upload"}), 400
    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "Nome file vuoto"}), 400

    folder = _company_upload_dir()
    filename = secure_filename(file.filename)
    fpath = os.path.join(folder, filename)

    # Evita collisioni
    if os.path.exists(fpath):
        stem, ext = os.path.splitext(filename)
        filename = f"{stem}-{uuid.uuid4().hex[:6]}{ext}"
        fpath = os.path.join(folder, filename)

    file.save(fpath)

    # Indicizza nel vector store (se disponibile)
    file_processor = getattr(g, "file_processor", None)
    vector_store = getattr(g, "vector_store", None)
    if file_processor and vector_store:
        try:
            chunks = file_processor.process(fpath)  # [(text, metadata), ...]
            texts = [t for (t, _) in chunks]
            metas = []
            for _, md in chunks:
                base_md = md or {}
                base_md["source"] = filename
                base_md["scope"] = "company"  # utile per filtri di ricerca
                metas.append(base_md)
            vector_store.add_documents(texts, metas)
        except Exception as e:
            # Non blocchiamo l'upload se l'indicizzazione fallisce
            # (puoi loggare l'errore e tornare 207 se preferisci)
            pass

    # restituisci KPI aggiornati (documents_total incluso)
    return company_overview()