# app.py
import os
import uuid
import logging
from typing import Dict, Any

from flask import Flask, g, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from sqlalchemy import text

from config import Config

# DB
from models import db  # models/__init__.py: db = SQLAlchemy()

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

    # DB URL (fallback a SQLite locale)
    db_url = os.getenv("DATABASE_URL", getattr(Config, "DATABASE_URL", "")).strip()
    if not db_url:
        db_path = os.path.join(app.root_path, "data.db")
        db_url = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

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

    # Inizializza DB
    db.init_app(app)

    # Valida config se previsto
    if hasattr(Config, "validate"):
        Config.validate()

    # Crea tabelle e componenti solo nel processo attivo (evita doppio con reloader)
    should_init = not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if should_init:
        with app.app_context():
            # IMPORTA TUTTI I MODELLI PRIMA DI create_all()
            from models.material import Material  # noqa: F401
            from models.worker import Worker      # noqa: F401
            # Project & co. (Company, Project, ProjectDocument, ProjectMaterial se presente)
            from models.project import Company, Project, ProjectDocument  # noqa: F401
            try:
                # se nel tuo models/project.py hai definito anche ProjectMaterial:
                from models.project import ProjectMaterial  # noqa: F401
            except Exception:
                pass
            # Shifts (se esiste)
            try:
                from models.staff_shift import StaffShift  # noqa: F401
            except Exception:
                pass

            db.create_all()
            _init_components(app)
            log.info("DB e componenti inizializzati.")

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
        return resp

    @app.teardown_appcontext
    def _shutdown_session(exception=None):
        # chiude in modo sicuro eventuali sessioni DB al termine del contesto
        try:
            db.session.remove()
        except Exception:
            pass

    # Health check
    @app.get("/healthz")
    def healthz():
        deps = app.extensions.get("deps", {})
        try:
            db.session.execute(text("SELECT 1"))
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

    # --- Stats helpers (SQLite direct) ---
    import sqlite3
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if db_uri.startswith("sqlite:////"):  # absolute path
        _db_path = db_uri.replace("sqlite:////", "/", 1)
    elif db_uri.startswith("sqlite:///"):  # relative to app
        _db_path = db_uri.replace("sqlite:///", "", 1)
    else:
        _db_path = db_uri  # fallback (non-sqlite URIs won't work with sqlite3)

    def _q(sql, params=()):
        con = sqlite3.connect(_db_path)
        con.row_factory = sqlite3.Row
        with con:
            rows = con.execute(sql, params).fetchall()
        return rows

    @app.get("/api/stats/workers")
    def stats_workers():
        try:
            tot = _q("SELECT COUNT(*) AS c FROM workers")[0]["c"]
        except Exception:
            tot = 0
        try:
            lib = _q("SELECT COUNT(*) AS c FROM workers WHERE available=1")[0]["c"]
        except Exception:
            lib = 0
        return jsonify({"total": int(tot), "free": int(lib)}), 200

    @app.get("/api/stats/projects")
    def stats_projects():
        try:
            exists = _q("SELECT name FROM sqlite_master WHERE type='table' AND name='projects'")
            if exists:
                tot = _q("SELECT COUNT(*) AS c FROM projects")[0]["c"]
                att = _q("SELECT COUNT(*) AS c FROM projects WHERE status='Confermato'")[0]["c"]
            else:
                tot, att = 0, 0
        except Exception:
            tot, att = 0, 0
        return jsonify({"total": int(tot), "active": int(att)}), 200

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
    from routes.projects import projects_bp
    from routes.workers import workers_bp

    app.register_blueprint(views_bp)                    # pagine HTML
    app.register_blueprint(api_bp, url_prefix="/api")   # API legacy/varie
    app.register_blueprint(materials_bp, url_prefix="/api")
    app.register_blueprint(staff_bp, url_prefix="/api/staff")
    app.register_blueprint(estimate_bp)                 # /api/estimate
    app.register_blueprint(chat_bp)                     # /api/chat
    app.register_blueprint(company_bp)                  # /api/company
    app.register_blueprint(projects_bp)                 # /api/projects
    app.register_blueprint(workers_bp)                  # /api/workers

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