# app.py
import os
import uuid
import logging
import re
import requests
from functools import lru_cache
from datetime import datetime
from typing import Dict, Any

from flask import Flask, g, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from config import Config

# MongoDB
from db.mongo import init_mongo, ensure_mongo_indexes

# DB

# Componenti RAG
from models.vector_store import VectorStore
from models.chat_model import ChatModel
from utils.file_processor import FileProcessor
from utils.web_retriever import WebRetriever  # opzionale
from utils.intent_router import IntentRouter  # opzionale


# ---------------------------------------------------------------------
# Inizializzazione componenti condivisi (vector store, LLM, ecc.)
# ---------------------------------------------------------------------
def _init_components(app: Flask) -> None:
    cfg = app.config

    required = [
        "GOOGLE_API_KEY", "MODEL_NAME", "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSION", "QDRANT_PATH", "QDRANT_COLLECTION"
    ]
    missing = [k for k in required if not cfg.get(k)]

    if missing:
        # In dev potresti voler partire anche senza RAG: qui loggo warning e non crasho.
        app.logger.warning("Config mancante per RAG (%s). Avvio senza vector_store/LLM.", ", ".join(missing))
        app.extensions["deps"] = {"vector_store": None, "chat_model": None, "file_processor": None,
                                  "web_retriever": None, "router": None}
        return

    os.makedirs(cfg.get("UPLOAD_FOLDER", "uploads"), exist_ok=True)
    os.makedirs(cfg.get("QDRANT_PATH", "./qdrant_data"), exist_ok=True)

    vector_store = VectorStore(
        path=cfg["QDRANT_PATH"],
        collection_name=cfg["QDRANT_COLLECTION"],
        embedding_model=cfg["EMBEDDING_MODEL"],
        embedding_dim=cfg["EMBEDDING_DIMENSION"],
    )

    chat_model = ChatModel(
        api_key=cfg["GOOGLE_API_KEY"],
        model_name=cfg["MODEL_NAME"],
        temperature=cfg.get("TEMPERATURE", 0.1),
    )

    file_processor = FileProcessor(
        chunk_size=cfg.get("CHUNK_SIZE", 1200),
        chunk_overlap=cfg.get("CHUNK_OVERLAP", 120),
    )

    web_retriever = None
    if cfg.get("ENABLE_WEB_RETRIEVAL", False):
        web_retriever = WebRetriever(
            max_results=5,
            timeout=cfg.get("WEB_TIMEOUT_SEC", 8),
        )

    router = IntentRouter(api_key=cfg["GOOGLE_API_KEY"])

    app.extensions["deps"] = {
        "vector_store": vector_store,
        "chat_model": chat_model,
        "file_processor": file_processor,
        "web_retriever": web_retriever,
        "router": router,
    }


# ---------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------
def create_app(config_class=Config) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(config_class)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", getattr(Config, "SECRET_KEY", "change-me"))


    # --- MongoDB init ---
    # Inizializza la connessione a Mongo (workers/materials/projects si appoggeranno qui)
    init_mongo()
    try:
        ensure_mongo_indexes()
    except Exception as e:
        app.logger.warning(f"Mongo index build skipped: {e}")

    # Uploads
    app.config.setdefault("UPLOAD_FOLDER", os.path.join(app.root_path, "uploads"))
    app.config.setdefault("MAX_CONTENT_LENGTH", 64 * 1024 * 1024)  # 64MB

    # CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Logging con request_id
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
    )
    from flask import has_request_context
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
        return record

    logging.setLogRecordFactory(record_factory)
    log = logging.getLogger("app")

    # Debug visibilità variabili d'ambiente chiave
    log.info("GOOGLE_API_KEY presente: %s", bool(os.getenv("GOOGLE_API_KEY")))
    log.info("MODEL_NAME: %s", os.getenv("MODEL_NAME"))


    # Valida config se previsto
    if hasattr(Config, "validate"):
        Config.validate()

    # Crea tabelle e componenti solo nel processo attivo (evita doppio con reloader)
    should_init = not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if should_init:
        with app.app_context():
            # Non creiamo più le tabelle SQL per workers/materials/projects.
            # Manteniamo SQLAlchemy caricato solo per eventuali parti legacy.

            # Inizializza componenti condivisi (VectorStore/LLM/Router, ecc.)
            _init_components(app)
            log.info("Componenti inizializzati (Mongo attivo per workers/materials/projects).")

    # Request hooks
    @app.before_request
    def _before():
        g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        deps: Dict[str, Any] = app.extensions.get("deps", {})
        g.vector_store = deps.get("vector_store")
        g.chat_model = deps.get("chat_model")
        g.file_processor = deps.get("file_processor")
        g.web_retriever = deps.get("web_retriever")
        g.router = deps.get("router")

    @app.after_request
    def _after(resp):
        resp.headers["X-Request-ID"] = getattr(g, "request_id", "-")
        # Disable caching for API endpoints to prevent stale KPI values
        try:
            if request.path.startswith("/api/"):
                resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                resp.headers["Pragma"] = "no-cache"
                resp.headers["Expires"] = "0"
        except Exception:
            pass
        return resp


    # Health check
    @app.get("/healthz")
    def healthz():
        from mongoengine.connection import get_connection
        deps = app.extensions.get("deps", {})
        # Verifica MongoDB
        try:
            client = get_connection()
            client.admin.command("ping")
            ok_db = True
        except Exception:
            ok_db = False

        return jsonify({
            "ok": bool(deps.get("vector_store")) and bool(deps.get("chat_model")) and ok_db and bool(deps.get("router")),
            "vector_store": bool(deps.get("vector_store")),
            "llm": bool(deps.get("chat_model")),
            "router": bool(deps.get("router")),
            "db": ok_db,
            "web_enabled": app.config.get("ENABLE_WEB_RETRIEVAL", False),
        })

    # Simple ping per verificare wiring UI ⇄ API
    @app.get("/api/ping")
    def api_ping():
        return jsonify({"ok": True, "msg": "pong"}), 200

    # --- Stats helpers (Mongo) ---
    @app.get("/api/stats/workers")
    def stats_workers():
        try:
            from models_mongo.worker import WorkerDoc
            tot = WorkerDoc.objects.count()
            lib = WorkerDoc.objects(available=True).count()
        except Exception:
            tot, lib = 0, 0
        return jsonify({"total": int(tot), "free": int(lib)}), 200

    @app.get("/api/stats/projects")
    def stats_projects():
        try:
            from models_mongo.project import ProjectDoc
            tot = ProjectDoc.objects.count()
            att = ProjectDoc.objects(status__iexact="Confermato").count()
        except Exception:
            tot, att = 0, 0
        return jsonify({"total": int(tot), "active": int(att)}), 200

    # --- Dashboard summary + CRUD per bottoni ---
    @app.get("/api/dashboard/summary")
    def dashboard_summary():
        """Ritorna conteggi reali da MongoDB per popolare i riquadri KPI."""
        try:
            from models_mongo.worker import WorkerDoc
            from models_mongo.project import ProjectDoc
            operai = WorkerDoc.objects.count()
            operai_attivi = WorkerDoc.objects(available=True).count()
            cantieri = ProjectDoc.objects.count()
            cantieri_attivi = ProjectDoc.objects(status__iexact="Confermato").count()
        except Exception as e:
            app.logger.warning("dashboard_summary fallback: %s", e)
            operai = operai_attivi = cantieri = cantieri_attivi = 0
        return jsonify({
            "operai": int(operai),
            "operai_attivi": int(operai_attivi),
            "cantieri": int(cantieri),
            "cantieri_attivi": int(cantieri_attivi),
            "documenti_azienda": 0
        }), 200
    def _next_worker_id():
        """Genera un ID univoco sequenziale in formato W-#### basato sui record esistenti."""
        try:
            from models_mongo.worker import WorkerDoc
            max_n = 0
            for code in WorkerDoc.objects.only('id').scalar('id'):
                if isinstance(code, str) and code.startswith('W-'):
                    try:
                        n = int(code.split('W-')[1])
                        if n > max_n:
                            max_n = n
                    except Exception:
                        continue
            return f"W-{max_n+1}"
        except Exception:
            # fallback sicuro
            return f"W-{str(uuid.uuid4())[:8]}"

    def _parse_date(s: str):
        if not s:
            return None
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return None

    def _next_project_id() -> str:
        """Genera un ID sequenziale in formato P-#### basato sui record esistenti."""
        try:
            from models_mongo.project import ProjectDoc
            max_n = 1000
            import re as _re
            rx = _re.compile(r"^P-(\d{3,})$")
            for code in ProjectDoc.objects.only('id').scalar('id'):
                if isinstance(code, str):
                    m = rx.match(code)
                    if m:
                        try:
                            n = int(m.group(1))
                            if n > max_n:
                                max_n = n
                        except Exception:
                            continue
            return f"P-{max_n+1}"
        except Exception:
            return f"P-{str(uuid.uuid4())[:8]}"

    def _normalize_min_address(addr_payload: dict | None):
        """Return a minimal normalized address dict or None.
        Expected keys (any may be missing):
          formatted, street, street_number, city, state, postal_code
        """
        if not addr_payload or not isinstance(addr_payload, dict):
            return None
        street = (addr_payload.get("street") or "").strip()
        number = (addr_payload.get("street_number") or addr_payload.get("number") or "").strip()
        city   = (addr_payload.get("city") or "").strip()
        state  = (addr_payload.get("state") or addr_payload.get("country") or "").strip()
        zipc   = (addr_payload.get("postal_code") or addr_payload.get("zip") or "").strip()
        formatted = (addr_payload.get("formatted") or "").strip()
        if not formatted:
            parts = []
            line1 = " ".join([p for p in [street, number] if p])
            if line1:
                parts.append(line1)
            line2 = " ".join([p for p in [zipc, city] if p])
            if line2:
                parts.append(line2)
            if state:
                parts.append(state)
            formatted = ", ".join([p for p in parts if p])
        return {
            "formatted": formatted or None,
            "street": street or None,
            "street_number": number or None,
            "city": city or None,
            "state": state or None,
            "postal_code": zipc or None,
        }

    @app.post("/api/workers")
    def api_create_worker():
        """Crea un operaio in MongoDB. Mappa is_active -> available."""
        data = request.get_json(force=True) or {}
        app.logger.info("/api/workers payload=%s", data)

        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name è obbligatorio"}), 400

        role = (data.get("role") or "operaio").strip()
        is_active = bool(data.get("is_active", True))

        # Genera sempre un ID univoco stile W-####
        wid = _next_worker_id()

        def _as_list(v):
            if isinstance(v, list):
                return [str(x).strip() for x in v if str(x).strip()]
            if isinstance(v, str):
                return [s.strip() for s in v.split(',') if s.strip()]
            return []

        hourly_rate = data.get("hourly_rate")
        try:
            hourly_rate = float(hourly_rate) if hourly_rate is not None else None
        except Exception:
            hourly_rate = None

        skills = _as_list(data.get("skills"))
        certs  = _as_list(data.get("certifications"))

        try:
            from models_mongo.worker import WorkerDoc
            w = WorkerDoc(
                id=wid,                     # PK custom generata lato server
                name=name,
                role=role,
                available=is_active,
                home_city=data.get("home_city"),
                hourly_rate=hourly_rate,
                skills=skills if skills else None,
                certifications=certs if certs else None,
            )
            w.save()
            return jsonify({"ok": True, "id": str(w.id)}), 200
        except Exception as e:
            app.logger.exception("create_worker error")
            return jsonify({"ok": False, "error": str(e)}), 400
    
    @app.delete("/api/workers/<worker_id>")
    def api_delete_worker(worker_id: str):
        """Elimina un operaio per ID custom (es. W-1048)."""
        try:
            from models_mongo.worker import WorkerDoc
            obj = WorkerDoc.objects.get(id=worker_id)
            obj.delete()
            return jsonify({"ok": True}), 200
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 404

    @app.post("/api/projects")
    def api_create_project():
        """Crea un cantiere. Le date inserite al create sono sempre STIME; se status=Confermato sono obbligatorie."""
        data = request.get_json(force=True) or {}

        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name è obbligatorio"}), 400

        status = (data.get("status") or "Preventivo").strip()
        if status not in ("Preventivo", "Confermato"):
            return jsonify({"error": "status deve essere 'Preventivo' o 'Confermato'"}), 400

        # Import modello e leggi l'elenco dei campi disponibili
        try:
            from models_mongo.project import ProjectDoc
        except Exception as e:
            app.logger.exception("ProjectDoc import error")
            return jsonify({"ok": False, "error": f"Modello ProjectDoc non disponibile: {e}"}), 500

        model_fields = set(ProjectDoc._fields.keys())

        # Leggi la città (potrebbe essere usata nei controlli di unicità)
        city = (data.get("city") or data.get("citta") or "").strip()

        # --- Address normalization and city fallback ---
        addr_in = data.get("address") if isinstance(data, dict) else None
        addr_norm = _normalize_min_address(addr_in) if addr_in else None
        if not city and addr_norm and addr_norm.get("city"):
            city = addr_norm.get("city")

        # Unicità: (name, city) oppure (name, citta) se il campo esiste
        try:
            if "city" in model_fields:
                exists = ProjectDoc.objects(name=name, city=(city or None)).first()
            elif "citta" in model_fields:
                exists = ProjectDoc.objects(name=name, citta=(city or None)).first()
            else:
                # fallback: se non esiste il campo città nel modello, usiamo solo name
                exists = ProjectDoc.objects(name=name).first()
            if exists:
                return jsonify({"error": "Esiste già un cantiere con lo stesso nome nella stessa città"}), 409
        except Exception:
            pass

        # ID: accetta quello passato se libero, altrimenti genera P-####
        wanted_id = (data.get("id") or "").strip()
        if wanted_id and ProjectDoc.objects(id=wanted_id).first():
            return jsonify({"error": "ID già esistente"}), 409
        pid = wanted_id or _next_project_id()

        # Raccogli le date inserite nel form (sempre come STIME)
        # Accettiamo alias dal frontend: start/end oppure start_date_estimated/end_date_estimated
        start_str = (data.get("start") or data.get("projStart") or data.get("start_date_estimated") or "").strip()
        end_str   = (data.get("end")   or data.get("projEnd")   or data.get("end_date_estimated")   or "").strip()

        # Se Confermato → le STIME sono OBBLIGATORIE
        if status == "Confermato" and (not start_str or not end_str):
            return jsonify({"error": "Per 'Confermato' sono obbligatorie le stime di inizio e fine (start/end)"}), 400

        # Validazione ordine date stima: fine >= inizio (vale per entrambi gli status)
        if start_str and end_str:
            try:
                s = datetime.strptime(start_str, "%Y-%m-%d")
                e = datetime.strptime(end_str,   "%Y-%m-%d")
                if e < s:
                    return jsonify({"error": "La data di fine (stima) non può essere antecedente alla data di inizio (stima)"}), 400
            except ValueError:
                # in caso di formato non valido, lascia che eventuali altri controlli gestiscano
                pass

        # Prepara kwargs SOLO con i campi che esistono nel modello
        doc_kwargs = {"id": pid}
        if "name" in model_fields:
            doc_kwargs["name"] = name
        if "status" in model_fields:
            doc_kwargs["status"] = status

        # city/citta opzionale (usa quello che esiste nel modello)
        if "city" in model_fields:
            doc_kwargs["city"] = city or None
        elif "citta" in model_fields:
            doc_kwargs["citta"] = city or None

        # project_address / addresses (indirizzo minimale)
        if addr_norm:
            if "project_address" in model_fields and addr_norm.get("formatted"):
                doc_kwargs["project_address"] = addr_norm.get("formatted")
            if "addresses" in model_fields:
                doc_kwargs["addresses"] = [addr_norm]

        # Salva sempre le STIME in meta_extra (senza cambiare lo schema)
        if "meta_extra" in model_fields:
            m = {}
            m["created_at"] = datetime.utcnow().strftime("%Y-%m-%d")
            if start_str or end_str:
                m["estimate"] = {"start": (start_str or None), "end": (end_str or None)}
            doc_kwargs["meta_extra"] = m

        try:
            p = ProjectDoc(**doc_kwargs)
            p.save()
            # Risposta: ritorna solo i campi realmente presenti
            resp = {"ok": True}
            for f in ("id", "name", "status", "city", "citta", "project_address", "addresses", "meta_extra"):
                if f in model_fields:
                    resp[f] = getattr(p, f, None)
            return jsonify(resp), 201
        except Exception as e:
            app.logger.exception("create_project error")
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.patch("/api/projects/<pid>/address")
    @app.post("/api/projects/<pid>/address")
    def api_upsert_project_address(pid: str):
        """Imposta o aggiunge un indirizzo minimale su un progetto.
        Body accetta:
          - address: { formatted?, street?, street_number?, city?, state?, postal_code? }
          - make_primary: bool (default True) -> se True l'indirizzo diventa primario
        Aggiorna anche city (per unicità name+city) e project_address se presenti nel modello.
        """
        try:
            from models_mongo.project import ProjectDoc
        except Exception as e:
            app.logger.exception("ProjectDoc import error")
            return jsonify({"ok": False, "error": f"Modello ProjectDoc non disponibile: {e}"}), 500

        data = request.get_json(force=True) or {}
        addr_in = data.get("address") if isinstance(data, dict) else None
        make_primary = bool(data.get("make_primary", True))
        addr_norm = _normalize_min_address(addr_in) if addr_in else None
        if not addr_norm or not any(addr_norm.values()):
            return jsonify({"error": "address mancante o non valido"}), 400

        # carica progetto
        obj = ProjectDoc.objects(id=pid).first()
        if not obj:
            return jsonify({"error": "Progetto non trovato"}), 404

        model_fields = set(ProjectDoc._fields.keys())

        # calcola la nuova city da salvare (se disponibile)
        new_city = addr_norm.get("city") or getattr(obj, "city", None)

        # Verifica unicità name+city se il modello ha la city
        try:
            if "city" in model_fields and new_city:
                dup = ProjectDoc.objects(id__ne=pid, name=obj.name, city=new_city).first()
                if dup:
                    return jsonify({"error": "Esiste già un cantiere con lo stesso nome nella stessa città"}), 409
            elif "citta" in model_fields and new_city:
                dup = ProjectDoc.objects(id__ne=pid, name=obj.name, citta=new_city).first()
                if dup:
                    return jsonify({"error": "Esiste già un cantiere con lo stesso nome nella stessa città"}), 409
        except Exception:
            pass

        # aggiorna fields indirizzo
        try:
            # addresses
            if "addresses" in model_fields:
                current = list(getattr(obj, "addresses", []) or [])
                if make_primary:
                    # rimuovi eventuali duplicati (stessa formatted+city)
                    current = [a for a in current if not (
                        (a.get("formatted") == addr_norm.get("formatted")) and (a.get("city") == addr_norm.get("city"))
                    )]
                    obj.addresses = [addr_norm] + current
                else:
                    # evita doppioni in coda
                    exists = any((a.get("formatted") == addr_norm.get("formatted")) and (a.get("city") == addr_norm.get("city")) for a in current)
                    if not exists:
                        current.append(addr_norm)
                    obj.addresses = current

            # project_address (stringa primaria)
            if "project_address" in model_fields and addr_norm.get("formatted") and make_primary:
                obj.project_address = addr_norm.get("formatted")

            # city/citta
            if new_city:
                if "city" in model_fields:
                    obj.city = new_city
                elif "citta" in model_fields:
                    obj.citta = new_city

            obj.save()
            return jsonify({
                "ok": True,
                "id": str(obj.id),
                "name": getattr(obj, "name", None),
                "city": getattr(obj, "city", None) if "city" in model_fields else getattr(obj, "citta", None),
                "project_address": getattr(obj, "project_address", None) if "project_address" in model_fields else None,
                "addresses": getattr(obj, "addresses", None) if "addresses" in model_fields else None,
            }), 200
        except Exception as e:
            app.logger.exception("upsert_project_address error")
            return jsonify({"ok": False, "error": str(e)}), 400

    # === Projects: helpers & listing ===
    def _project_to_dict_safe(obj):
        if obj is None:
            return {}
        if hasattr(obj, "to_mongo"):
            try:
                data = obj.to_mongo().to_dict()
                data["id"] = str(getattr(obj, "id", data.get("id") or data.get("_id") or ""))
            except Exception:
                data = {k: getattr(obj, k, None) for k in ("id","name","nome","city","citta","status","stato","project_address","address","addresses")}
        elif isinstance(obj, dict):
            data = obj
        else:
            data = {}
        return {
            "id": str(data.get("id") or data.get("_id") or ""),
            "name": data.get("name") or data.get("nome") or "",
            "city": data.get("city") or data.get("citta") or "",
            "status": data.get("status") or data.get("stato") or "Preventivo",
            "project_address": data.get("project_address") or data.get("address") or None,
        }

    @app.get("/api/projects/<pid>")
    def api_get_project(pid: str):
        try:
            from models_mongo.project import ProjectDoc
            obj = ProjectDoc.objects(id=pid).first()
            if obj:
                return jsonify(_project_to_dict_safe(obj)), 200
        except Exception as e:
            app.logger.warning(f"api_get_project: fallback raw due to {e}")
        try:
            from mongoengine.connection import get_db
            db = get_db()
            raw = db["projects"].find_one({"id": pid}) or db["projects"].find_one({"_id": pid})
            if not raw:
                return jsonify({"error": "Progetto non trovato"}), 404
            return jsonify(_project_to_dict_safe(raw)), 200
        except Exception as ee:
            app.logger.exception("api_get_project raw error")
            return jsonify({"ok": False, "error": str(ee)}), 500

    @app.get("/api/projects/list")
    def api_list_projects():
        def _norm(p: dict) -> dict:
            me = (p.get("meta_extra") or {})
            est = me.get("estimate") or {}
            prog = me.get("progress") or {}
            return {
                "id": str(p.get("id") or p.get("_id") or ""),
                "name": p.get("name") or p.get("nome") or "",
                "city": p.get("city") or p.get("citta") or "",
                "status": p.get("status") or p.get("stato") or "Preventivo",
                "project_address": p.get("project_address") or p.get("address") or None,
                "start_date_estimated": p.get("start_date_estimated") or est.get("start"),
                "end_date_estimated": p.get("end_date_estimated") or est.get("end"),
                "progress_percent": prog.get("percent"),
            }
        try:
            from models_mongo.project import ProjectDoc
            docs = list(ProjectDoc.objects)
            items = []
            for d in docs:
                try:
                    m = d.to_mongo().to_dict()
                    m["id"] = str(getattr(d, "id", m.get("id") or m.get("_id") or ""))
                except Exception:
                    m = {k: getattr(d, k, None) for k in ("id","name","nome","city","citta","status","stato","project_address","address","addresses")}
                # Ensure meta_extra is a dict for _norm
                if not isinstance(m.get("meta_extra"), dict):
                    m["meta_extra"] = {}
                items.append(_norm(m))
            items_sorted = sorted(items, key=lambda x: (x.get("name") or "").lower())
            return jsonify({"items": items_sorted, "total": len(items_sorted)}), 200
        except Exception as e:
            app.logger.warning(f"api_list_projects: fallback raw due to {e}")
        try:
            from mongoengine.connection import get_db
            db = get_db()
            cur = db["projects"].find({}, {
                "_id":1,"id":1,"name":1,"nome":1,"city":1,"citta":1,"status":1,"stato":1,
                "project_address":1,"address":1,
                "start_date_estimated":1,"end_date_estimated":1,
                "meta_extra":1
            })
            items = [_norm(doc) for doc in cur]
            items_sorted = sorted(items, key=lambda x: (x.get("name") or "").lower())
            return jsonify({"items": items_sorted, "total": len(items_sorted)}), 200
        except Exception as ee:
            app.logger.exception("api_list_projects raw error")
            return jsonify({"ok": False, "error": str(ee)}), 500

    @app.patch("/api/projects/<pid>/confirm")
    def api_confirm_project(pid: str):
        """
        Conferma un progetto: richiede start_date_estimated & end_date_estimated,
        valida che end >= start (YYYY-MM-DD), imposta status=Confermato.
        Non permette il revert a Preventivo (questo endpoint solo conferma).
        """
        data = request.get_json(force=True) or {}
        start_str = (data.get("start_date_estimated") or data.get("start") or "").strip()
        end_str   = (data.get("end_date_estimated")   or data.get("end")   or "").strip()
        if not start_str or not end_str:
            return jsonify({"error": "start_date_estimated ed end_date_estimated sono obbligatorie"}), 400
        # valida formato e ordine
        try:
            s = datetime.strptime(start_str, "%Y-%m-%d")
            e = datetime.strptime(end_str,   "%Y-%m-%d")
            if e < s:
                return jsonify({"error": "La data di fine (stima) non può precedere la data di inizio (stima)"}), 400
        except ValueError:
            return jsonify({"error": "Formato data non valido. Usa YYYY-MM-DD"}), 400

        # 1) Prova con MongoEngine
        try:
            from models_mongo.project import ProjectDoc
            obj = ProjectDoc.objects(id=pid).first()
            if not obj:
                return jsonify({"error": "Progetto non trovato"}), 404

            fields = set(getattr(ProjectDoc, "_fields", {}).keys())
            # status
            if "status" in fields:
                obj.status = "Confermato"
            elif "stato" in fields:
                obj.stato = "Confermato"

            # date stima: salva sui campi se esistono, altrimenti in meta_extra
            if "start_date_estimated" in fields:
                obj.start_date_estimated = start_str
            else:
                if hasattr(obj, "meta_extra"):
                    me = dict(obj.meta_extra or {})
                    est = dict(me.get("estimate") or {})
                    est["start"] = start_str
                    me["estimate"] = est
                    obj.meta_extra = me

            if "end_date_estimated" in fields:
                obj.end_date_estimated = end_str
            else:
                if hasattr(obj, "meta_extra"):
                    me = dict(obj.meta_extra or {})
                    est = dict(me.get("estimate") or {})
                    est["end"] = end_str
                    me["estimate"] = est
                    obj.meta_extra = me

            obj.save()
            return jsonify({"ok": True, "id": str(obj.id), "status": "Confermato", "start_date_estimated": start_str, "end_date_estimated": end_str}), 200
        except Exception as me_err:
            app.logger.warning("api_confirm_project: ME failed, fallback raw: %s", me_err)

        # 2) Fallback PyMongo
        try:
            from mongoengine.connection import get_db
            db = get_db()
            # tenta update per id
            q = {"id": pid}
            upd = {"$set": {"status": "Confermato", "start_date_estimated": start_str, "end_date_estimated": end_str}}
            doc = db["projects"].find_one_and_update(q, upd, return_document=True)
            if not doc:
                # prova con _id
                q2 = {"_id": pid}
                doc = db["projects"].find_one_and_update(q2, upd, return_document=True)
            if not doc:
                return jsonify({"error": "Progetto non trovato"}), 404
            return jsonify({"ok": True, "id": str(doc.get("id") or doc.get("_id")), "status": "Confermato", "start_date_estimated": start_str, "end_date_estimated": end_str}), 200
        except Exception as ee:
            app.logger.exception("api_confirm_project raw error")
            return jsonify({"ok": False, "error": str(ee)}), 500

    @app.patch("/api/projects/<pid>/progress")
    def api_update_project_progress(pid: str):
        """Aggiorna l'avanzamento lavori del cantiere (0..100), opzionale nota.
        Scrive in meta_extra.progress { percent, note?, updated_at } e aggiunge storico in meta_extra.progress_history.
        Consentito solo se status == "Confermato".
        """
        data = request.get_json(force=True) or {}
        try:
            percent = int(data.get("percent"))
        except Exception:
            return jsonify({"error": "percent deve essere un intero"}), 400
        if percent < 0 or percent > 100:
            return jsonify({"error": "percent deve essere tra 0 e 100"}), 400
        note = (data.get("note") or "").strip() or None
        now_iso = datetime.utcnow().isoformat(timespec="seconds")

        # 1) MongoEngine branch
        try:
            from models_mongo.project import ProjectDoc
            obj = ProjectDoc.objects(id=pid).first()
            if not obj:
                return jsonify({"error": "Progetto non trovato"}), 404
            current_status = getattr(obj, "status", None) or getattr(obj, "stato", None) or "Preventivo"
            if str(current_status) != "Confermato":
                return jsonify({"error": "Aggiornamento consentito solo per cantieri Confermati"}), 409

            me = dict(getattr(obj, "meta_extra", {}) or {})
            me_progress = dict(me.get("progress") or {})
            me_progress["percent"] = percent
            if note:
                me_progress["note"] = note
            me_progress["updated_at"] = now_iso
            me["progress"] = me_progress

            # append history (mantieni ultimi 50)
            hist = list(me.get("progress_history") or [])
            hist.append({"percent": percent, "note": note, "at": now_iso})
            if len(hist) > 50:
                hist = hist[-50:]
            me["progress_history"] = hist

            obj.meta_extra = me
            obj.save()
            return jsonify({"ok": True, "id": str(obj.id), "percent": percent, "note": note}), 200
        except Exception as me_err:
            app.logger.warning("api_update_project_progress: ME failed, fallback raw: %s", me_err)

        # 2) PyMongo fallback
        try:
            from mongoengine.connection import get_db
            db = get_db()
            # Leggi documento
            doc = db["projects"].find_one({"id": pid}) or db["projects"].find_one({"_id": pid})
            if not doc:
                return jsonify({"error": "Progetto non trovato"}), 404
            status = doc.get("status") or doc.get("stato") or "Preventivo"
            if str(status) != "Confermato":
                return jsonify({"error": "Aggiornamento consentito solo per cantieri Confermati"}), 409

            me = dict(doc.get("meta_extra") or {})
            me_progress = dict((me.get("progress") or {}))
            me_progress["percent"] = percent
            if note:
                me_progress["note"] = note
            me_progress["updated_at"] = now_iso
            me["progress"] = me_progress
            hist = list(me.get("progress_history") or [])
            hist.append({"percent": percent, "note": note, "at": now_iso})
            if len(hist) > 50:
                hist = hist[-50:]
            me["progress_history"] = hist

            upd = {"$set": {"meta_extra": me}}
            target = {"id": pid} if doc.get("id") == pid else {"_id": pid}
            db["projects"].update_one(target, upd)
            return jsonify({"ok": True, "id": str(doc.get("id") or doc.get("_id")), "percent": percent, "note": note}), 200
        except Exception as ee:
            app.logger.exception("api_update_project_progress raw error")
            return jsonify({"ok": False, "error": str(ee)}), 500

    @app.patch("/api/projects/<pid>/progress/note")
    def api_add_progress_note(pid: str):
        """
        Aggiunge una nota di avanzamento (testo libero) nello storico del cantiere.
        Consentito solo se status == "Confermato".
        Non modifica la percentuale: verrà aggiornata da un'assistente/automazione separata.
        Body: { "text": "..." }
        """
        data = request.get_json(force=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"error": "text è obbligatorio"}), 400
        now_iso = datetime.utcnow().isoformat(timespec="seconds")

        # 1) MongoEngine branch
        try:
            from models_mongo.project import ProjectDoc
            obj = ProjectDoc.objects(id=pid).first()
            if not obj:
                return jsonify({"error": "Progetto non trovato"}), 404
            status = getattr(obj, "status", None) or getattr(obj, "stato", None) or "Preventivo"
            if str(status) != "Confermato":
                return jsonify({"error": "Aggiornamento consentito solo per cantieri Confermati"}), 409

            me = dict(getattr(obj, "meta_extra", {}) or {})
            hist = list(me.get("progress_history") or [])
            hist.append({"note": text, "at": now_iso, "by": "user"})
            if len(hist) > 200:
                hist = hist[-200:]
            me["progress_history"] = hist
            obj.meta_extra = me
            obj.save()
            return jsonify({"ok": True, "id": str(obj.id), "note": text, "at": now_iso}), 200
        except Exception as me_err:
            app.logger.warning("api_add_progress_note: ME failed, fallback raw: %s", me_err)

        # 2) PyMongo fallback
        try:
            from mongoengine.connection import get_db
            db = get_db()
            doc = db["projects"].find_one({"id": pid}) or db["projects"].find_one({"_id": pid})
            if not doc:
                return jsonify({"error": "Progetto non trovato"}), 404
            status = doc.get("status") or doc.get("stato") or "Preventivo"
            if str(status) != "Confermato":
                return jsonify({"error": "Aggiornamento consentito solo per cantieri Confermati"}), 409

            me = dict(doc.get("meta_extra") or {})
            hist = list(me.get("progress_history") or [])
            hist.append({"note": text, "at": now_iso, "by": "user"})
            if len(hist) > 200:
                hist = hist[-200:]
            me["progress_history"] = hist

            upd = {"$set": {"meta_extra": me}}
            target = {"id": pid} if doc.get("id") == pid else {"_id": pid}
            db["projects"].update_one(target, upd)
            return jsonify({"ok": True, "id": str(doc.get("id") or doc.get("_id")), "note": text, "at": now_iso}), 200
        except Exception as ee:
            app.logger.exception("api_add_progress_note raw error")
            return jsonify({"ok": False, "error": str(ee)}), 500
        
    @app.post("/api/projects/<pid>/auto-assign")
    def api_auto_assign(pid: str):
        """
        Auto-assegna operai al cantiere (regole base, AI-ready).
        Disponibile solo per cantieri Confermati.
        """
        data = request.get_json(force=True) or {}
        strategy = (data.get("strategy") or "basic").lower()

        # 1) Recupera progetto
        try:
            from models_mongo.project import ProjectDoc
            proj = ProjectDoc.objects(id=pid).first()
        except Exception:
            proj = None

        if not proj:
            return jsonify({"error": "Progetto non trovato"}), 404

        status = getattr(proj, "status", None) or getattr(proj, "stato", None) or "Preventivo"
        if status != "Confermato":
            return jsonify({"error": "Disponibile solo per cantieri Confermati"}), 409

        works = list(getattr(proj, "works", []) or [])

        # 2) Recupera operai liberi
        try:
            from models_mongo.worker import WorkerDoc
            free_workers = list(WorkerDoc.objects(available=True))
            by_role = {}
            for w in free_workers:
                role = (getattr(w, "role", None) or "Operaio edile").lower()
                by_role.setdefault(role, []).append(w)
        except Exception:
            from mongoengine.connection import get_db
            db = get_db()
            free_workers = list(db["workers"].find({"available": True}))
            by_role = {}
            for w in free_workers:
                role = (w.get("role") or "Operaio edile").lower()
                by_role.setdefault(role, []).append(w)

        # 3) Mapping parole chiave → ruoli
        ROLE_BY_KEYWORD = {
            "elettric": "elettricista",
            "cablagg":  "elettricista",
            "impianto elettrico": "elettricista",
            "mur": "muratore",
            "parete": "muratore",
            "intonac": "muratore",
            "paviment": "piastrellista",
            "piastrell": "piastrellista",
            "idraulic": "idraulico",
            "tubo": "idraulico",
            "cartongesso": "cartongessista"
        }

        def infer_role(work_name: str) -> str:
            n = (work_name or "").lower()
            for kw, role in ROLE_BY_KEYWORD.items():
                if kw in n:
                    return role
            return "operaio edile"

        # 4) Assegnazioni
        assigned = []
        for w in works:
            role_needed = infer_role(w.get("work_name", ""))
            candidates = by_role.get(role_needed, []) or by_role.get(role_needed.capitalize(), []) or []
            if not candidates:
                continue
            chosen = candidates.pop(0)
            cid = getattr(chosen, "id", None) or chosen.get("id") or chosen.get("_id")
            cname = getattr(chosen, "name", None) or chosen.get("name")
            assigned.append({
                "worker_id": str(cid),
                "worker_name": cname,
                "role": role_needed,
                "work_name": w.get("work_name"),
                "start": w.get("start_date_planned") or w.get("start"),
                "end": w.get("end_date_planned") or w.get("end"),
            })

        # 5) Persistenza
        try:
            me = dict(getattr(proj, "meta_extra", {}) or {})
            curr = list(me.get("assignments") or [])
            curr.extend(assigned)
            me["assignments"] = curr
            proj.meta_extra = me
            proj.save()

            from models_mongo.worker import WorkerDoc
            for a in assigned:
                WorkerDoc.objects(id=a["worker_id"]).update_one(set__available=False)
        except Exception as e:
            app.logger.warning(f"Persistenza assegnazioni fallita: {e}")

        msg = "Nessun lavoro da assegnare" if not works else (f"Assegnazioni create: {len(assigned)}" if assigned else "Nessun operaio compatibile disponibile")
        return jsonify({"ok": True, "assigned": assigned, "message": msg}), 200

    @app.delete("/api/projects/<pid>")
    def api_delete_project(pid: str):
        """Elimina definitivamente un cantiere dal database.
        Rimuove il documento per id (o _id) usando MongoEngine, con fallback PyMongo.
        """
        # 1) Prova con MongoEngine
        try:
            from models_mongo.project import ProjectDoc
            obj = ProjectDoc.objects(id=pid).first()
            if obj:
                obj.delete()
                return jsonify({"ok": True}), 200
        except Exception as me_err:
            app.logger.warning("api_delete_project: ME failed, fallback raw: %s", me_err)

        # 2) Fallback PyMongo
        try:
            from mongoengine.connection import get_db
            db = get_db()
            res = db["projects"].delete_one({"id": pid})
            if res.deleted_count == 0:
                res = db["projects"].delete_one({"_id": pid})
            if res.deleted_count == 0:
                return jsonify({"ok": False, "error": "Progetto non trovato"}), 404
            return jsonify({"ok": True}), 200
        except Exception as ee:
            app.logger.exception("api_delete_project raw error")
            return jsonify({"ok": False, "error": str(ee)}), 500

    # Error handler (mantiene le HTTPException originali)
    # --- Geoapify proxy (facoltativo: evita di esporre la chiave al client) ---
    @lru_cache(maxsize=256)
    def _geo_autocomplete_cached(q: str, lang: str = "it", limit: int = 7):
        key = app.config.get("GEOAPIFY_KEY", "")
        if not key or not q:
            return {"features": []}
        url = "https://api.geoapify.com/v1/geocode/autocomplete"
        params = {"text": q, "lang": lang or "it", "limit": str(limit or 7), "apiKey": key}
        r = requests.get(url, params=params, timeout=6)
        r.raise_for_status()
        return r.json()

    @app.get("/api/geo/autocomplete")
    def geo_autocomplete():
        q = (request.args.get("text") or "").strip()
        if len(q) < 3:
            return jsonify({"features": []})
        lang = (request.args.get("lang") or "it").strip() or "it"
        try:
            data = _geo_autocomplete_cached(q, lang, int(request.args.get("limit", 7)))
            # Minimizza e normalizza i campi utili al frontend
            feats = []
            for f in data.get("features", []):
                p = f.get("properties", {})
                feats.append({
                    "formatted": p.get("formatted"),
                    "street": p.get("street") or p.get("name"),
                    "housenumber": p.get("housenumber"),
                    "city": p.get("city") or p.get("town") or p.get("village") or p.get("county"),
                    "state": p.get("country") or p.get("state"),
                    "postcode": p.get("postcode"),
                })
            return jsonify({"features": feats})
        except requests.HTTPError as e:
            app.logger.warning("Geoapify proxy error: %s", e)
            return jsonify({"features": [], "error": str(e)}), 502
    @app.errorhandler(Exception)
    def _handle_error(e):
        if isinstance(e, HTTPException):
            return e  # lascia Flask gestire 4xx/5xx noti
        app.logger.exception("Unhandled error")
        return jsonify({
            "error": str(e),
            "request_id": getattr(g, "request_id", "-")
        }), 500

    # ---------------------------
    # Static: serve gli upload
    # ---------------------------
    @app.get("/uploads/<path:filename>")
    def serve_upload(filename: str):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)

    # Blueprints (una volta sola ciascuno)
    from routes.api import api_bp
    from routes.views import views_bp
    from routes.materials import materials_bp
    from routes.staff import staff_bp
    from routes.estimate import estimate_bp
    from routes.chat import chat_bp
    from routes.company import company_bp

    app.register_blueprint(views_bp)                    # pagine HTML
    app.register_blueprint(api_bp, url_prefix="/api")   # API legacy/varie
    app.register_blueprint(materials_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(estimate_bp)                 # /api/estimate
    app.register_blueprint(chat_bp)                     # /api/chat
    app.register_blueprint(company_bp)

    
    # Log delle rotte per debug
    try:
        for rule in app.url_map.iter_rules():
            log.info("ROUTE: %s → endpoint=%s methods=%s", rule, rule.endpoint, ",".join(sorted(rule.methods)))
    except Exception:
        pass
    return app