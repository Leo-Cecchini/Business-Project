import os
import logging
import uuid
from flask import Flask, g, jsonify, request
from flask_cors import CORS

from config import Config

# Componenti RAG
from models.vector_store import VectorStore
from models.chat_model import ChatModel
from utils.file_processor import FileProcessor
from utils.web_retriever import WebRetriever  # opzionale

# Blueprints
from routes.api import api_bp
from routes.views import views_bp
from routes.materials import materials_bp
from routes.staff import staff_bp

# DB
from models import db  # models/__init__.py -> db = SQLAlchemy()


def _init_components(app: Flask):
    """Crea e registra i componenti dell'app (vector store, LLM, file processor, web retriever opzionale)."""
    cfg = app.config

    # --- Validazioni base ---
    missing = []
    for key in [
        "GOOGLE_API_KEY", "MODEL_NAME", "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSION", "QDRANT_PATH", "QDRANT_COLLECTION"
    ]:
        if not cfg.get(key):
            missing.append(key)
    if missing:
        raise RuntimeError(f"Config mancante: {', '.join(missing)}")

    os.makedirs(cfg["UPLOAD_FOLDER"], exist_ok=True)

    # --- Istanzia componenti principali ---
    vector_store = VectorStore(
        path=cfg.get("QDRANT_PATH"),
        collection_name=cfg["QDRANT_COLLECTION"],
        embedding_model=cfg["EMBEDDING_MODEL"],
        embedding_dim=cfg["EMBEDDING_DIMENSION"],
    )

    chat_model = ChatModel(
        api_key=cfg["GOOGLE_API_KEY"],
        model_name=cfg["MODEL_NAME"],            # es. "gemini-2.5-flash"
        temperature=cfg.get("TEMPERATURE", 0.2),
    )

    file_processor = FileProcessor(
        chunk_size=cfg.get("CHUNK_SIZE", 1200),
        chunk_overlap=cfg.get("CHUNK_OVERLAP", 120),
    )

    # --- Web retriever opzionale ---
    web_retriever = None
    if cfg.get("ENABLE_WEB_RETRIEVAL", False):
        web_retriever = WebRetriever(
            max_results=5,
            timeout=cfg.get("WEB_TIMEOUT_SEC", 6),
        )

    # Registra in app.extensions per accesso nei blueprint
    app.extensions["deps"] = {
        "vector_store": vector_store,
        "chat_model": chat_model,
        "file_processor": file_processor,
        "web_retriever": web_retriever,
    }


def create_app(config_class=Config) -> Flask:
    """Application factory."""
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(config_class)

    # --- Config DB (fallback a sqlite:///data.db)
    app.config["SQLALCHEMY_DATABASE_URI"] = getattr(
        Config, "DATABASE_URL", os.getenv("DATABASE_URL", "sqlite:///data.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db_path = os.path.join(app.root_path, "data.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    db.init_app(app)

    # Validazione config opzionale
    if hasattr(Config, "validate"):
        Config.validate()

    # CORS (frontend separato o uso locale)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
    )
    from flask import has_request_context
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        if has_request_context():
            try:
                from flask import g as _g
                record.request_id = getattr(_g, "request_id", "-")
            except Exception:
                record.request_id = "-"
        else:
            record.request_id = "-"
        return record

    logging.setLogRecordFactory(record_factory)
    log = logging.getLogger("app")

    # Inizializza componenti una sola volta (evita doppio init con reloader)
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        # ⚠️ IMPORTA i modelli PRIMA di creare le tabelle!
        from models.material import Material
        from models.worker import Worker

        with app.app_context():
            db.create_all()          # crea tabelle in data.db
            _init_components(app)    # vector store / chat model / file processor / web retriever
            log.info("Vector store, Chat model e DB inizializzati")

    # Request hooks
    @app.before_request
    def _before():
        g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        deps = app.extensions.get("deps", {})
        g.vector_store = deps.get("vector_store")
        g.chat_model = deps.get("chat_model")
        g.file_processor = deps.get("file_processor")
        g.web_retriever = deps.get("web_retriever")

    @app.after_request
    def _after(resp):
        resp.headers["X-Request-ID"] = getattr(g, "request_id", "-")
        return resp

    # Health check
    @app.get("/healthz")
    def healthz():
        deps = app.extensions.get("deps", {})
        ok_vs = bool(deps.get("vector_store"))
        ok_llm = bool(deps.get("chat_model"))
        web_enabled = app.config.get("ENABLE_WEB_RETRIEVAL", False)
        # Quick DB check
        try:
            db.session.execute(db.text("SELECT 1"))
            ok_db = True
        except Exception:
            ok_db = False
        return jsonify({
            "ok": ok_vs and ok_llm and ok_db,
            "vector_store": ok_vs,
            "llm": ok_llm,
            "db": ok_db,
            "web_enabled": web_enabled,
        })

    # Error handler JSON
    @app.errorhandler(Exception)
    def _handle_error(e):
        code = getattr(e, "code", 500)
        log = logging.getLogger("app")
        log.exception("Unhandled error")
        return jsonify({
            "error": str(e),
            "request_id": getattr(g, "request_id", "-")
        }), code

    # Blueprints
    app.register_blueprint(views_bp)                               # pagine HTML
    app.register_blueprint(api_bp, url_prefix="/api")              # API JSON (chat, upload, ecc.)
    app.register_blueprint(staff_bp, url_prefix="/api/staff")      # API Operai
    app.register_blueprint(materials_bp, url_prefix="/api")        # /api/materials, /api/materials/import-csv

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.getenv("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", False))