# app.py
"""
Application factory - ESSENTIALS ONLY.
Cleaned up from 1699 lines of duplicates and cruft.
"""
import os
import logging
import uuid
from typing import Dict, Any
from flask import Flask, g, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from config.config import Config

# ---------------------------------------------------------------------
# Logging (idempotent setup)
# ---------------------------------------------------------------------
_LOGGING_CONFIGURED = False
_REQUEST_ID_FACTORY_SET = False


def _configure_logging(app: Flask) -> logging.Logger:
    """Configure global logging only once, including request_id injection."""
    global _LOGGING_CONFIGURED, _REQUEST_ID_FACTORY_SET

    if not _LOGGING_CONFIGURED:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        )
        _LOGGING_CONFIGURED = True

    # Add request_id to every log record (only set factory once globally)
    from flask import has_request_context

    if not _REQUEST_ID_FACTORY_SET:
        old_factory = logging.getLogRecordFactory()

        def record_factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            record.request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
            return record

        logging.setLogRecordFactory(record_factory)
        _REQUEST_ID_FACTORY_SET = True

    return logging.getLogger("app")

# MongoDB
from db.mongo import init_mongo

try:
    from db.mongo import ensure_indexes_safely as ensure_indexes
except ImportError:
    from db.mongo import ensure_mongo_indexes as ensure_indexes

# RAG Components
from models.vector_store import VectorStore
from models.chat_model import ChatModel
from utils.file_processor import FileProcessor
from utils.intent_router import IntentRouter

try:
    from utils.web_retriever import WebRetriever
except ImportError:
    WebRetriever = None


# ---------------------------------------------------------------------
# Component Initialization
# ---------------------------------------------------------------------
def _init_components(app: Flask) -> None:
    """Initialize shared components (VectorStore, LLM, Router, etc)."""
    cfg = app.config

    web_retriever = None
    enable_web = cfg.get("ENABLE_WEB_RETRIEVAL", False)
    app.logger.info(f"🌐 Web Retrieval Config: ENABLE_WEB_RETRIEVAL={enable_web}, WebRetriever class available={WebRetriever is not None}")

    if enable_web and WebRetriever:
        try:
            web_retriever = WebRetriever(
                max_results=5,
                timeout=cfg.get("WEB_TIMEOUT_SEC", 8),
            )
            app.logger.info("✅ WebRetriever initialized successfully")
        except Exception as e:
            app.logger.error(f"❌ WebRetriever init failed: {e}")
            import traceback
            app.logger.error(traceback.format_exc())
    elif not enable_web:
        app.logger.warning("⚠️ Web retrieval DISABLED (ENABLE_WEB_RETRIEVAL=False)")
    elif not WebRetriever:
        app.logger.warning("⚠️ WebRetriever class NOT AVAILABLE (import failed)")

    required = [
        "GOOGLE_API_KEY", "MODEL_NAME", "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSION", "QDRANT_PATH", "QDRANT_COLLECTION"
    ]
    missing = [k for k in required if not cfg.get(k)]

    if missing:
        app.logger.warning(
            f"Config missing for RAG ({', '.join(missing)}). Starting without vector_store/LLM."
        )
        app.extensions["deps"] = {
            "vector_store": None,
            "chat_model": None,
            "file_processor": None,
            "web_retriever": None,
            "router": None
        }
        return

    # Create directories
    os.makedirs(cfg.get("UPLOAD_FOLDER", "uploads"), exist_ok=True)
    os.makedirs(cfg.get("QDRANT_PATH", "./qdrant_data"), exist_ok=True)

    # Initialize components
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

    router = IntentRouter(api_key=cfg["GOOGLE_API_KEY"])

    app.extensions["deps"] = {
        "vector_store": vector_store,
        "chat_model": chat_model,
        "file_processor": file_processor,
        "web_retriever": web_retriever,
        "router": router,
    }


# ---------------------------------------------------------------------
# Application Factory
# ---------------------------------------------------------------------
def create_app(config_class=Config) -> Flask:
    """
    Create and configure the Flask application.

    This is the CLEANED UP version - duplicates and cruft removed.
    Only essential initialization remains.
    """
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(config_class)
    app.secret_key = os.getenv("FLASK_SECRET_KEY", getattr(Config, "SECRET_KEY", "change-me"))

    # --- MongoDB Init ---
    try:
        from mongoengine import disconnect
        disconnect(alias="default")
    except Exception:
        pass

    init_mongo()

    try:
        with app.app_context():
            ensure_indexes()
            app.logger.info("MongoDB indexes normalized")
    except Exception as e:
        app.logger.warning(f"Index normalization skipped: {e}")

    # --- Config ---
    app.config.setdefault("UPLOAD_FOLDER", os.path.join(app.root_path, "uploads"))
    app.config.setdefault("MAX_CONTENT_LENGTH", 64 * 1024 * 1024)  # 64MB

    # --- CORS ---
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
            "expose_headers": ["Content-Type"],
            "supports_credentials": False
        },
        r"/chat/*": {
            "origins": "*",
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        },
        r"/analytics/*": {
            "origins": "*",
            "methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type"],
        }
    })

    # --- Logging with request_id ---
    log = _configure_logging(app)

    log.info(f"GOOGLE_API_KEY present: {bool(os.getenv('GOOGLE_API_KEY'))}")
    log.info(f"MODEL_NAME: {os.getenv('MODEL_NAME')}")

    # Validate config if present
    if hasattr(Config, "validate"):
        try:
            Config.validate()
        except Exception as e:
            log.warning(f"Config validation failed: {e}")

    # --- Initialize Components ---
    should_init = not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if should_init:
        with app.app_context():
            _init_components(app)
            deps = app.extensions.get("deps", {})
            rag_active = bool(deps.get("vector_store") and deps.get("chat_model") and deps.get("router"))
            log.info(f"Components initialized (RAG active={rag_active})")

    # --- Request Hooks ---
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
        # Disable caching for API endpoints
        try:
            if request.path.startswith("/api/"):
                resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                resp.headers["Pragma"] = "no-cache"
                resp.headers["Expires"] = "0"
        except Exception:
            pass
        return resp

    # --- Error Handler ---
    @app.errorhandler(Exception)
    def _handle_error(e):
        if isinstance(e, HTTPException):
            return jsonify({"error": e.name, "message": e.description}), e.code

        log.exception("Unhandled exception")
        if app.debug:
            import traceback
            return jsonify({
                "error": "Internal Server Error",
                "message": str(e),
                "traceback": traceback.format_exc()
            }), 500
        else:
            return jsonify({
                "error": "Internal Server Error",
                "message": "An unexpected error occurred"
            }), 500

    # --- Static Files ---
    @app.get("/uploads/<path:filename>")
    def serve_upload(filename: str):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=False)

    # --- Blueprint Registration ---
    from routes.materials import materials_bp
    from routes.chat import chat_bp
    from routes.company import company_bp
    from routes.catalog import workcat_bp
    from routes.schedule import schedule_bp
    from utils.estimate import estimate_bp
    from routes.workers import workers_bp
    from routes.projects import projects_bp
    from routes.computo import computo_bp
    from routes.analytics import chat_analytics_bp

    app.register_blueprint(materials_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(estimate_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(company_bp)
    app.register_blueprint(workcat_bp)
    app.register_blueprint(workers_bp)          # ← Era mancante!
    app.register_blueprint(projects_bp)         # ← Era mancante!
    app.register_blueprint(computo_bp)          # ← Era mancante!
    app.register_blueprint(chat_analytics_bp)   # ← Era mancante!

    @app.route('/health')
    def health():
        return {"status": "ok"}, 200

    # Log routes for debugging
    try:
        for rule in app.url_map.iter_rules():
            log.info(f"ROUTE: {rule} → {rule.endpoint} [{','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))}]")
    except Exception:
        pass

    return app
