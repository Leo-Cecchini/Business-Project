# routes/projects.py
from __future__ import annotations
import os
import uuid

from flask import Blueprint, request, jsonify, g, current_app
from werkzeug.utils import secure_filename

# Rimuovi SQLAlchemy imports
# from models import db
# from models.project import Project

# Usa il modello Mongo
from models_mongo.project import ProjectDoc
from routes.company import company_overview  # per restituire KPI aggiornati

# Template helpers (Opzione A)
from project_template import create_new_project, add_work

projects_bp = Blueprint("projects", __name__, url_prefix="/api/projects")


# ------------------------------- Utils -------------------------------

def _ensure_upload_dir(project_id: str) -> str:
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


# Mapper ProjectDoc -> dict compatibile con UI esistente

def _doc_to_dict(p: ProjectDoc) -> dict:
    meta = getattr(p, "meta_extra", {}) or {}
    return {
        "id": p.id,
        "company_id": meta.get("company_id"),
        "name": p.name,
        "city": getattr(p, "address", None) or meta.get("city"),
        "start_date": meta.get("start_date"),
        "end_date": meta.get("end_date"),
        "status": _normalize_status(getattr(p, "status", None) or meta.get("status")),
    }


# Helper: append a work item into meta_extra["works"] using the same structure as project_template.add_work

def _append_work_to_project_meta(p: ProjectDoc, *, work_name: str, start_planned: str | None,
                                 end_planned: str | None, duration_estimated: float | int | None,
                                 workers: list[str] | None) -> dict:
    meta = p.meta_extra or {}
    works_list = list(meta.get("works") or [])
    # Costruiamo un mini dizionario compatibile con add_work()
    tmp_project = {
        "_id": p.id,
        "name": p.name,
        "project_date": meta.get("project_date"),
        "project_address": getattr(p, "address", None) or meta.get("project_address") or meta.get("city"),
        "status": p.status or meta.get("status") or "quotation",
        "metric_computation_id": meta.get("metric_computation_id", ""),
        "works": works_list,
    }
    add_work(
        project=tmp_project,
        work_name=work_name,
        start_planned=start_planned,
        end_planned=end_planned,
        duration_estimated=float(duration_estimated or 0),
        workers=workers or [],
    )
    # Persisti su ProjectDoc
    meta["works"] = tmp_project["works"]
    p.meta_extra = meta
    p.save()
    return meta["works"][-1]

@projects_bp.get("/<project_id>")
def get_project(project_id: str):
    p = ProjectDoc.objects(id=str(project_id)).first()
    if not p:
        return jsonify({"error": "Cantiere non trovato"}), 404
    meta = p.meta_extra or {}
    # Evita payload eccessivi: limita il numero di works restituiti
    works = list(meta.get("works") or [])
    if len(works) > 300:
        works = works[-300:]
    status_norm = _normalize_status(getattr(p, "status", None) or meta.get("status"))
    payload = {
        "_id": p.id,
        "name": p.name,
        "project_date": meta.get("project_date"),
        "project_address": getattr(p, "address", None) or meta.get("project_address") or meta.get("city"),
        "status": status_norm,
        "stato": status_norm,  # alias per compatibilità UI
        "metric_computation_id": meta.get("metric_computation_id", ""),
        "works": works,
        "assignments": meta.get("assignments", []),  # per mostrare assegnazioni/booking lato UI
    }
    return jsonify(payload)

@projects_bp.post("/<pid>/works")
def add_work_api(pid: str):
    p = ProjectDoc.objects(id=pid).first()
    if not p:
        return jsonify({"error": "Cantiere non trovato"}), 404
    d = request.get_json(force=True) or {}
    item = _append_work_to_project_meta(
        p,
        work_name=d.get("work_name") or d.get("name") or "Attività",
        start_planned=d.get("start_planned") or d.get("start_date_planned"),
        end_planned=d.get("end_planned") or d.get("end_date_planned"),
        duration_estimated=d.get("duration_estimated") or d.get("duration_estimated_hours"),
        workers=d.get("workers") or [],
    )
    return jsonify({"ok": True, "projectId": pid, "work": item, "works_count": len(p.meta_extra.get("works", []))})

@projects_bp.patch("/<pid>/works/status")
def update_work_status_api(pid: str):
    p = ProjectDoc.objects(id=pid).first()
    if not p:
        return jsonify({"error": "Cantiere non trovato"}), 404
    d = request.get_json(force=True) or {}
    target = (d.get("work_name") or "").strip()
    new_status = (d.get("status") or "").strip()
    if not target or not new_status:
        return jsonify({"error": "work_name e status sono obbligatori"}), 422
    meta = p.meta_extra or {}
    works = list(meta.get("works") or [])
    changed = False
    for w in works:
        if w.get("work_name") == target:
            w["status"] = new_status
            changed = True
            break
    if changed:
        meta["works"] = works
        p.meta_extra = meta
        p.save()
    return jsonify({"ok": changed})


# ------------------------------- Endpoints -------------------------------

@projects_bp.get("")
def list_projects():
    """Lista dei cantieri (ordinati dal più recente, per id desc come fallback)."""
    rows = ProjectDoc.objects.order_by("-id").all()
    return jsonify([_doc_to_dict(p) for p in rows])

@projects_bp.get("/list")
def list_projects_legacy():
    """Alias compatibile con le vecchie UI: `/api/projects/list` → stessa risposta di list_projects."""
    return list_projects()

@projects_bp.post("")
def create_project():
    """
    Crea un nuovo cantiere usando il template Python (Opzione A):
    - genera il JSON di progetto con create_new_project()
    - aggiunge eventuali works dal payload con add_work()
    - salva su Mongo mappando sui campi esistenti (name, address, status) e mette il resto in meta_extra
    """
    data = request.get_json(force=True) or {}

    # Parametri base (compatibili con la UI attuale)
    proj_id = str(data.get("id") or uuid.uuid4())
    # Garanzia di unicità dell'ID: se esiste già, rigenera (caso estremamente raro)
    if ProjectDoc.objects(id=proj_id).first():
      proj_id = str(uuid.uuid4())
    name = (data.get("name") or "Nuovo cantiere").strip()
    project_address = (data.get("project_address") or data.get("address") or "").strip()
    metric_id = (data.get("metric_computation_id") or "").strip()
    status_raw = (data.get("status") or "quotation").strip()

    if not name:
        return jsonify({"error": "Nome cantiere mancante"}), 422

    # 1) Crea la struttura base con il TUO template Python
    project_dict = create_new_project(
        project_id=proj_id,
        name=name,
        address=project_address,
        metric_computation_id=metric_id,
        status=status_raw,
    )

    # 2) Aggiungi eventuali works dal body usando add_work()
    #    (supporta sia i nomi start_planned/end_planned sia start_date_planned/end_date_planned)
    works_in = data.get("works") or []
    for w in works_in:
        add_work(
            project=project_dict,
            work_name=w.get("work_name") or w.get("name") or "Attività",
            start_planned=w.get("start_planned") or w.get("start_date_planned"),
            end_planned=w.get("end_planned") or w.get("end_date_planned"),
            duration_estimated=float(
                w.get("duration_estimated")
                or w.get("duration_estimated_hours")
                or 0
            ),
            workers=w.get("workers") or [],
        )

    # 3) Salva su Mongo
    #    Il modello corrente espone i campi: id, name, address, status, meta_extra
    #    → mappiamo address = project_address; status normalizzato allo standard UI
    ProjectDoc(
        id=project_dict["_id"],
        name=project_dict["name"],
        address=project_dict["project_address"],
        status=_normalize_status(project_dict.get("status")),
        meta_extra={
            # Conserviamo nel documento tutte le info del template
            "project_date": project_dict.get("project_date"),
            "metric_computation_id": project_dict.get("metric_computation_id"),
            "works": project_dict.get("works", []),
            # eventuali campi extra provenienti dal payload originale
            **{k: v for k, v in data.items() if k not in {
                "id","name","project_address","address","status","metric_computation_id","works"
            }}
        },
    ).save()

    # 4) Crea cartella upload per il cantiere
    _ensure_upload_dir(proj_id)

    # 5) Risposta: ritorniamo la struttura template-like attesa dalla UI
    return jsonify({"projectId": proj_id, "project": project_dict}), 201


@projects_bp.delete("/<project_id>")
def delete_project(project_id: str):
    p = ProjectDoc.objects(id=str(project_id)).first()
    if not p:
        return jsonify({"error": "Cantiere non trovato"}), 404
    ProjectDoc.objects(id=str(project_id)).delete()
    # ritorna KPI aggiornati per aggiornare i contatori sul frontend
    return company_overview()


@projects_bp.get("/<project_id>/summary")
def project_summary(project_id: str):
    """Riepilogo del cantiere + elenco documenti su disco."""
    p = ProjectDoc.objects(id=str(project_id)).first()
    if not p:
        return jsonify({"error": "Cantiere non trovato"}), 404

    folder = _ensure_upload_dir(str(project_id))
    docs = []
    if os.path.exists(folder):
        for fname in sorted(os.listdir(folder)):
            if fname.startswith("."):
                continue
            docs.append({"name": fname, "path": f"/uploads/project_{project_id}/{fname}"})

    return jsonify({
        "project": _doc_to_dict(p),
        "documents": docs
    })


@projects_bp.get("/<project_id>/documents")
def project_documents_list(project_id: str):
    """Solo la lista documenti su disco (comodo per frontend)."""
    if not ProjectDoc.objects(id=str(project_id)).first():
        return jsonify({"error": "Cantiere non trovato"}), 404

    folder = _ensure_upload_dir(str(project_id))
    docs = []
    if os.path.exists(folder):
        for fname in sorted(os.listdir(folder)):
            if fname.startswith("."):
                continue
            docs.append({"name": fname, "path": f"/uploads/project_{project_id}/{fname}"})
    return jsonify({"documents": docs})


@projects_bp.post("/<project_id>/documents")
def upload_project_document(project_id: str):
    """
    Carica un documento del cantiere:
    - salva su disco
    - indicizza nel vector store per la ricerca semantica (se componenti presenti)
    """
    p = ProjectDoc.objects(id=str(project_id)).first()
    if not p:
        return jsonify({"error": "Cantiere non trovato"}), 404

    if "file" not in request.files:
        return jsonify({"error": "Nessun file in upload"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Nome file vuoto"}), 400

    # Salvataggio fisico
    folder = _ensure_upload_dir(str(project_id))
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
            base_md["project_id"] = str(project_id)
            metas.append(base_md)
        added = vector_store.add_documents(texts, metas)
    except Exception as e:
        # l'upload è andato a buon fine; fallisce solo l'indicizzazione
        return jsonify({"ok": True, "file": filename, "indexed": 0, "warning": f"Indicizzazione fallita: {e}"}), 207

    return jsonify({"ok": True, "indexed": added, "file": filename})


@projects_bp.post("/<pid>/status")
def toggle_status(pid: str):
    p = ProjectDoc.objects(id=str(pid)).first()
    if not p:
        return jsonify({"error": "Cantiere non trovato"}), 404

    cur = _normalize_status(getattr(p, "status", None))
    p.status = "Preventivo" if cur == "Confermato" else "Confermato"
    p.save()
    return company_overview()