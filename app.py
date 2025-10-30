# app.py
import os
import uuid
import logging
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
        """Crea un cantiere in MongoDB."""
        data = request.get_json(force=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name è obbligatorio"}), 400
        status = (data.get("status") or "Preventivo").strip()
        try:
            from models_mongo.project import ProjectDoc
            p = ProjectDoc(name=name, status=status)
            p.save()
            return jsonify({"ok": True, "id": str(p.id)}), 200
        except Exception as e:
            app.logger.exception("create_project error")
            return jsonify({"ok": False, "error": str(e)}), 400

    # Error handler (mantiene le HTTPException originali)
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

    # Log mappa delle rotte esposte (utile per verificare i prefix)
    try:
        for rule in app.url_map.iter_rules():
            log.info("ROUTE: %s → endpoint=%s methods=%s", rule, rule.endpoint, ",".join(sorted(rule.methods)))
    except Exception:
        pass

    return app


# ---------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------
if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", False))