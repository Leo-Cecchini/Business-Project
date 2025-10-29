# routes/company.py
from __future__ import annotations
import os
import uuid
from datetime import date
from typing import List, Dict

from flask import Blueprint, jsonify, request, current_app, g
from werkzeug.utils import secure_filename
from sqlalchemy import func

from models import db
from models.worker import Worker
from models.project import Project
from models.material import Material

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
    workers_total = db.session.scalar(
        db.select(func.count()).select_from(Worker)
    ) or 0

    # Progetti
    projects_total = db.session.scalar(
        db.select(func.count()).select_from(Project)
    ) or 0

    # Materiali
    materials_total = db.session.scalar(
        db.select(func.count()).select_from(Material)
    ) or 0

    # Progetti confermati
    active_projects = db.session.scalar(
        db.select(func.count())
        .select_from(Project)
        .where(func.lower(func.coalesce(Project.status, "")) == "confermato")
    ) or 0

    # Lista nomi progetti confermati (max 10)
    active_projects_list = [
        name
        for (name,) in db.session.execute(
            db.select(Project.name)
            .where(func.lower(func.coalesce(Project.status, "")) == "confermato")
            .order_by(Project.id.desc())
            .limit(10)
        ).all()
    ]

    # Ruoli (tutti)
    roles_breakdown = dict(
        db.session.execute(
            db.select(Worker.role, func.count()).group_by(Worker.role)
        ).all()
    )

    # Operai disponibili (available = 1)
    active_workers = db.session.scalar(
        db.select(func.count()).select_from(Worker).where(Worker.available.is_(True))
    ) or 0

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