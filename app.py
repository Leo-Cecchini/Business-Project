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
from db.mongo import init_mongo
try:
    from db.mongo import ensure_indexes_safely as ensure_indexes
except ImportError:
    from db.mongo import ensure_mongo_indexes as ensure_indexes

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

    # --- DB bootstrap (export JSON mancanti → seed non distruttivo) PRIMA di connettere Mongo ---
    if os.environ.get("BOOTSTRAP_DB", "1") == "1":
        try:
            if os.environ.get("EXPORT_MISSING_SEED", "0") == "1":
                # Crea/aggiorna file in data/db_seed/ a partire dal DB corrente (solo se mancano)
                from scripts.export_db import ensure_seed_files_from_db
                ensure_seed_files_from_db(("work_catalog", "workers", "pricelists", "materials"))
            # Popola il DB con i JSON presenti se la collezione è vuota (idempotente)
            from scripts.seed_db import seed_if_needed
            seed_if_needed(("work_catalog", "workers", "pricelists", "materials"))
            app.logger.info("DB bootstrap ok (export missing + seed_if_needed)")
        except Exception as e:
            app.logger.warning(f"DB bootstrap skipped: {e}")

    # --- MongoDB init (dopo bootstrap) ---
    # Disconnessione difensiva dell'alias default (nel caso gli script bootstrap abbiano già aperto la connessione)
    try:
        from mongoengine import disconnect
        disconnect(alias="default")
    except Exception:
        pass
    # Inizializza la connessione a Mongo (workers/materials/projects si appoggeranno qui)
    init_mongo()
    # Esegui la normalizzazione indici una sola volta all'avvio (evita code 85)
    try:
        from db.mongo import ensure_indexes_safely
        with app.app_context():
            ensure_indexes_safely()
            app.logger.info("Mongo indici normalizzati (una tantum all'avvio)")
    except Exception as e:
        app.logger.warning("Index normalize skipped: %s", e)

    # Best-effort: crea unique compound index su (region, city) per pricelists
    try:
        from mongoengine.connection import get_db
        _db = get_db()
        _db["pricelists"].create_index([("region", 1), ("city", 1)], unique=True, name="uniq_region_city")
        app.logger.info("Index pricelists.uniq_region_city ok")
    except Exception as ie:
        app.logger.warning("Index pricelists create skipped: %s", ie)

    # Warm-up: trigger collection access to finalize auto-index creation before serving requests
    try:
        from mongoengine.connection import get_db
        _db = get_db()
        _ = _db["materials"].count_documents({})
        _ = _db["projects"].count_documents({})
        _ = _db["workers"].count_documents({})
        _ = _db["pricelists"].count_documents({})
        _ = _db["work_catalog"].count_documents({})
        app.logger.info("Mongo warm-up counts ok")
    except Exception as e:
        app.logger.warning("Mongo warm-up skipped: %s", e)


    # Uploads
    app.config.setdefault("UPLOAD_FOLDER", os.path.join(app.root_path, "uploads"))
    app.config.setdefault("MAX_CONTENT_LENGTH", 64 * 1024 * 1024)  # 64MB

    # CORS
    CORS(app, resources={
        r"/api/*": {"origins": "*"},
        r"/chat/*": {"origins": "*"},  # compat per rotta legacy senza /api
    })

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

    @app.post("/api/admin/reindex")
    def admin_reindex():
        try:
            ensure_indexes()
            # Optional warm-up after reindex to stabilize counts
            from mongoengine.connection import get_db
            _db = get_db()
            _ = _db["materials"].count_documents({})
            _ = _db["projects"].count_documents({})
            _ = _db["workers"].count_documents({})
            return jsonify({"ok": True, "message": "Indexes normalized"}), 200
        except Exception as e:
            app.logger.exception("admin_reindex error")
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.post("/api/dev/seed")
    def api_dev_seed():
        """
        (DEV ONLY) Trigger a reseed from data/db_seed/*.json.
        Uses scripts/seed_db.main(); safe to call multiple times.
        """
        try:
            from scripts.seed_db import main as seed_main
            res = seed_main()  # expected to return a dict with counts per collection
            return jsonify({"ok": True, "result": res}), 200
        except Exception as e:
            app.logger.exception("api_dev_seed error")
            return jsonify({"ok": False, "error": str(e)}), 500

    # Simple ping per verificare wiring UI ⇄ API
    @app.get("/api/ping")
    def api_ping():
        return jsonify({"ok": True, "msg": "pong"}), 200

    @app.get("/api/health")
    def api_health():
        # Semplice health sotto /api per test rapidi dal frontend
        deps = app.extensions.get("deps", {})
        return jsonify({
            "ok": bool(deps.get("vector_store")) and bool(deps.get("chat_model")),
            "vector_store": bool(deps.get("vector_store")),
            "llm": bool(deps.get("chat_model")),
        }), 200

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
            # Best-effort: salva anche campi extra non modellati (es. home_region)
            try:
                from mongoengine.connection import get_db
                db = get_db()
                extra = {}
                if data.get("home_region"):
                    extra["home_region"] = data.get("home_region")
                if data.get("region"):
                    extra["region"] = data.get("region")
                if data.get("available") is not None:
                    extra["available"] = bool(data.get("available"))
                if data.get("current_site"):
                    extra["current_site"] = data.get("current_site")
                if extra:
                    db["workers"].update_one({"id": w.id}, {"$set": extra})
            except Exception:
                pass
            return jsonify({"ok": True, "id": str(w.id)}), 200
        except Exception as e:
            app.logger.exception("create_worker error")
            return jsonify({"ok": False, "error": str(e)}), 400
    @app.patch("/api/workers/<worker_id>")
    def api_patch_worker(worker_id: str):
        """Aggiorna campi base del lavoratore (safe patch)."""
        data = request.get_json(force=True) or {}
        fields = {k: v for k, v in data.items() if k in {"name","role","available","home_city","home_region","hourly_rate","region"}}
        # Normalizza hourly_rate
        if "hourly_rate" in fields:
            try:
                fields["hourly_rate"] = float(fields["hourly_rate"]) if fields["hourly_rate"] is not None else None
            except Exception:
                fields.pop("hourly_rate", None)
        # 1) MongoEngine
        try:
            from models_mongo.worker import WorkerDoc
            obj = WorkerDoc.objects(id=worker_id).first()
            if obj:
                if "name" in fields: obj.name = fields["name"]
                if "role" in fields: obj.role = fields["role"]
                if "available" in fields: obj.available = bool(fields["available"])
                if "home_city" in fields and hasattr(obj, "home_city"): obj.home_city = fields["home_city"]
                if "hourly_rate" in fields and hasattr(obj, "hourly_rate"): obj.hourly_rate = fields["hourly_rate"]
                obj.save()
                # Campi extra non modellati
                extra = {}
                for k in ("home_region","region"):
                    if k in fields:
                        extra[k] = fields[k]
                if extra:
                    try:
                        from mongoengine.connection import get_db
                        db = get_db()
                        db["workers"].update_one({"id": worker_id}, {"$set": extra})
                    except Exception:
                        pass
                return jsonify({"ok": True}), 200
        except Exception as me_err:
            app.logger.warning(f"api_patch_worker: ME failed, fallback raw: {me_err}")
        # 2) PyMongo fallback
        try:
            from mongoengine.connection import get_db
            db = get_db()
            upd = {"$set": fields}
            res = db["workers"].update_one({"id": worker_id}, upd)
            if res.matched_count == 0:
                res = db["workers"].update_one({"_id": worker_id}, upd)
                if res.matched_count == 0:
                    return jsonify({"ok": False, "error": "Worker non trovato"}), 404
            return jsonify({"ok": True}), 200
        except Exception as ee:
            app.logger.exception("api_patch_worker raw error")
            return jsonify({"ok": False, "error": str(ee)}), 500

    @app.post("/api/workers/<worker_id>/toggle")
    def api_toggle_worker(worker_id: str):
        """Inverti lo stato di disponibilità (available)."""
        # 1) MongoEngine
        try:
            from models_mongo.worker import WorkerDoc
            obj = WorkerDoc.objects(id=worker_id).first()
            if obj:
                cur = bool(getattr(obj, "available", True))
                obj.available = not cur
                obj.save()
                return jsonify({"ok": True, "available": bool(obj.available)}), 200
        except Exception:
            pass
        # 2) PyMongo
        try:
            from mongoengine.connection import get_db
            db = get_db()
            doc = db["workers"].find_one({"id": worker_id}) or db["workers"].find_one({"_id": worker_id})
            if not doc:
                return jsonify({"ok": False, "error": "Worker non trovato"}), 404
            cur = bool(doc.get("available", True))
            db["workers"].update_one({"id": doc.get("id") or worker_id}, {"$set": {"available": (not cur)}})
            return jsonify({"ok": True, "available": (not cur)}), 200
        except Exception as ee:
            app.logger.exception("api_toggle_worker raw error")
            return jsonify({"ok": False, "error": str(ee)}), 500

    @app.post("/api/workers/sync_availability")
    def api_sync_availability():
        """Inizializza available=True dove mancante o copia da is_active se presente."""
        try:
            from mongoengine.connection import get_db
            db = get_db()
            # 1) set available=True se il campo manca
            r1 = db["workers"].update_many({"available": {"$exists": False}}, {"$set": {"available": True}})
            # 2) allinea a is_active se esiste
            cur = db["workers"].find({"is_active": {"$exists": True}}, {"id":1,"is_active":1})
            changed = 0
            for d in cur:
                try:
                    db["workers"].update_one({"id": d.get("id")}, {"$set": {"available": bool(d.get("is_active"))}})
                    changed += 1
                except Exception:
                    continue
            return jsonify({"ok": True, "set_true_if_missing": getattr(r1, 'modified_count', None), "synced_from_is_active": changed}), 200
        except Exception as ee:
            app.logger.exception("api_sync_availability error")
            return jsonify({"ok": False, "error": str(ee)}), 500

    def _worker_to_dict_safe(obj):
        """Serialize WorkerDoc or raw dict to a minimal safe dict."""
        if obj is None:
            return {}
        if hasattr(obj, "to_mongo"):
            try:
                data = obj.to_mongo().to_dict()
                data["id"] = str(getattr(obj, "id", data.get("id") or data.get("_id") or ""))
            except Exception:
                data = {k: getattr(obj, k, None) for k in ("id","name","role","available","home_city","home_region","hourly_rate")}
        elif isinstance(obj, dict):
            data = obj
        else:
            data = {}
        return {
            "id": str(data.get("id") or data.get("_id") or ""),
            "name": data.get("name") or "",
            "role": data.get("role") or "",
            "available": bool(data.get("available", True)),
            "home_city": data.get("home_city"),
            "home_region": data.get("home_region") or data.get("region"),
            "hourly_rate": data.get("hourly_rate"),
        }

    def _parse_bool(v):
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("1","true","t","yes","y","si","sì"):  # support it/yes
            return True
        if s in ("0","false","f","no","n"):
            return False
        return None

    @app.get("/api/workers/<worker_id>")
    def api_get_worker(worker_id: str):
        """Ritorna un lavoratore per id custom (W-####) con fallback PyMongo."""
        # 1) MongoEngine
        try:
            from models_mongo.worker import WorkerDoc
            obj = WorkerDoc.objects(id=worker_id).first()
            if obj:
                return jsonify(_worker_to_dict_safe(obj)), 200
        except Exception:
            pass
        # 2) PyMongo
        try:
            from mongoengine.connection import get_db
            db = get_db()
            raw = db["workers"].find_one({"id": worker_id}) or db["workers"].find_one({"_id": worker_id})
            if not raw:
                return jsonify({"error": "Worker non trovato"}), 404
            return jsonify(_worker_to_dict_safe(raw)), 200
        except Exception as ee:
            app.logger.exception("api_get_worker raw error")
            return jsonify({"ok": False, "error": str(ee)}), 500

    @app.get("/api/workers")
    def api_list_workers():
        """Lista/ricerca lavoratori con filtri opzionali: id, name, role, available, city, region.
        Esempi:
          /api/workers?available=true
          /api/workers?role=piastrellista&available=true
          /api/workers?name=Mario
          /api/workers?region=Lombardia
        """
        q_id = (request.args.get("id") or "").strip()
        q_name = (request.args.get("name") or request.args.get("q") or "").strip()
        q_role = (request.args.get("role") or "").strip()
        q_city = (request.args.get("city") or "").strip()
        q_region = (request.args.get("region") or "").strip()
        q_av = _parse_bool(request.args.get("available"))

        # 1) MongoEngine
        try:
            from models_mongo.worker import WorkerDoc
            qs = WorkerDoc.objects
            if q_id:
                qs = qs(id=q_id)
            if q_name:
                qs = qs(name__icontains=q_name)
            if q_role:
                qs = qs(role__icontains=q_role)
            if q_av is not None:
                qs = qs(available=q_av)
            # region/city se i campi esistono
            try:
                if q_city:
                    qs = qs(home_city__icontains=q_city)
            except Exception:
                pass
            try:
                if q_region:
                    # prova home_region poi region
                    qs = qs(__raw__={"$or": [
                        {"home_region": {"$regex": q_region, "$options": "i"}},
                        {"region": {"$regex": q_region, "$options": "i"}}
                    ]})
            except Exception:
                pass
            items = [_worker_to_dict_safe(x) for x in qs]
            items_sorted = sorted(items, key=lambda x: (x.get("name") or "").lower())
            return jsonify({"items": items_sorted, "total": len(items_sorted)}), 200
        except Exception as me_err:
            app.logger.warning(f"api_list_workers: ME failed, fallback raw: {me_err}")

        # 2) PyMongo fallback
        try:
            from mongoengine.connection import get_db
            db = get_db()
            filt = {}
            if q_id:
                filt["id"] = q_id
            if q_name:
                filt["name"] = {"$regex": q_name, "$options": "i"}
            if q_role:
                filt["role"] = {"$regex": q_role, "$options": "i"}
            if q_av is not None:
                filt["available"] = bool(q_av)
            if q_city:
                filt["home_city"] = {"$regex": q_city, "$options": "i"}
            if q_region:
                filt["$or"] = [
                    {"home_region": {"$regex": q_region, "$options": "i"}},
                    {"region": {"$regex": q_region, "$options": "i"}}
                ]
            cur = db["workers"].find(filt, {"_id":0})
            items = [_worker_to_dict_safe(doc) for doc in cur]
            items_sorted = sorted(items, key=lambda x: (x.get("name") or "").lower())
            return jsonify({"items": items_sorted, "total": len(items_sorted)}), 200
        except Exception as ee:
            app.logger.exception("api_list_workers raw error")
            return jsonify({"ok": False, "error": str(ee)}), 500

    @app.get("/api/workers/free")
    def api_list_free_workers():
        """Comodo: restituisce i lavoratori disponibili, con filtri opzionali role/region/city."""
        args = request.args.to_dict(flat=True)
        args["available"] = "true"
        with app.test_request_context(query_string=args):
            return api_list_workers()
    
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
        if wanted_id:
            # verifica unicità sull'ID richiesto
            if ProjectDoc.objects(id=wanted_id).first():
                return jsonify({"error": "ID già esistente"}), 409
        pid = wanted_id or _next_project_id()
        if not pid:
            return jsonify({"error": "Impossibile generare ID progetto"}), 500

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
        doc_kwargs = {}
        if "id" in model_fields:
            doc_kwargs["id"] = pid
        else:
            # Modello senza field "id": usa la PK nativa
            doc_kwargs["_id"] = pid
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

    # === Works drafts & commits ===
    def _get_project_by_id(pid: str):
        """Helper: ritorna ProjectDoc (se possibile) oppure raw dict (PyMongo)."""
        # 1) MongoEngine
        try:
            from models_mongo.project import ProjectDoc
            obj = ProjectDoc.objects(id=pid).first()
            if obj:
                return obj
        except Exception as _:
            pass
        # 2) PyMongo
        try:
            from mongoengine.connection import get_db
            db = get_db()
            raw = db["projects"].find_one({"id": pid}) or db["projects"].find_one({"_id": pid})
            return raw
        except Exception:
            return None

    def _ensure_meta_extra_container(obj, key: str):
        """Ritorna (meta_extra_dict, changed_bool). Crea i contenitori mancanti."""
        changed = False
        me = dict(getattr(obj, "meta_extra", {}) or {}) if not isinstance(obj, dict) else dict(obj.get("meta_extra") or {})
        if key not in me or not isinstance(me.get(key), (list, dict)):
            # drafts => dict, works => list
            me[key] = {} if key == "work_drafts" else []
            changed = True
        return me, changed

    def _save_project_obj(obj, me_updated: dict) -> bool:
        """Scrive meta_extra aggiornato su ProjectDoc o raw dict. Ritorna True se ok."""
        # MongoEngine branch
        try:
            if hasattr(obj, "meta_extra"):
                obj.meta_extra = me_updated
                obj.save()
                return True
        except Exception:
            pass
        # PyMongo branch
        try:
            from mongoengine.connection import get_db
            db = get_db()
            pid_val = getattr(obj, "id", None) or obj.get("id") or obj.get("_id")
            q = {"id": pid_val} if obj.get("id") == pid_val or getattr(obj, "id", None) == pid_val else {"_id": pid_val}
            db["projects"].update_one(q, {"$set": {"meta_extra": me_updated}})
            return True
        except Exception:
            return False

    @app.post("/api/projects/<pid>/works/draft")
    def api_create_work_draft(pid: str):
        """Crea una bozza di lavoro dentro meta_extra.work_drafts[draft_id].
        Body: { item: { scope, materials[], labor[], totals{} } } oppure { scope, materials, ... }
        Ritorna: { ok, draft_id }
        """
        data = request.get_json(force=True) or {}
        item = data.get("item") if isinstance(data, dict) else None
        if not item:
            item = {k: v for k, v in data.items() if k in ("scope","materials","labor","totals")}
        if not isinstance(item, dict):
            return jsonify({"error": "payload non valido"}), 400

        obj = _get_project_by_id(pid)
        if not obj:
            return jsonify({"error": "Progetto non trovato"}), 404

        draft_id = str(uuid.uuid4())[:8]
        now_iso = datetime.utcnow().isoformat(timespec="seconds")

        me, _ = _ensure_meta_extra_container(obj, "work_drafts")
        drafts = dict(me.get("work_drafts") or {})
        drafts[draft_id] = {
            "draft_id": draft_id,
            "status": "draft",
            "created_at": now_iso,
            "updated_at": now_iso,
            "item": item,
        }
        me["work_drafts"] = drafts

        if not _save_project_obj(obj, me):
            return jsonify({"ok": False, "error": "persistenza fallita"}), 500
        return jsonify({"ok": True, "draft_id": draft_id}), 201

    @app.get("/api/projects/<pid>/works/draft/<draft_id>")
    def api_get_work_draft(pid: str, draft_id: str):
        obj = _get_project_by_id(pid)
        if not obj:
            return jsonify({"error": "Progetto non trovato"}), 404
        me = dict(getattr(obj, "meta_extra", {}) or {}) if not isinstance(obj, dict) else dict(obj.get("meta_extra") or {})
        drafts = dict(me.get("work_drafts") or {})
        d = drafts.get(draft_id)
        if not d:
            return jsonify({"error": "Bozza non trovata"}), 404
        return jsonify({"ok": True, **d}), 200

    @app.patch("/api/projects/<pid>/works/draft/<draft_id>")
    def api_update_work_draft(pid: str, draft_id: str):
        data = request.get_json(force=True) or {}
        obj = _get_project_by_id(pid)
        if not obj:
            return jsonify({"error": "Progetto non trovato"}), 404

        me, _ = _ensure_meta_extra_container(obj, "work_drafts")
        drafts = dict(me.get("work_drafts") or {})
        d = drafts.get(draft_id)
        if not d:
            return jsonify({"error": "Bozza non trovata"}), 404

        item = data.get("item") if isinstance(data, dict) else None
        if not item:
            # supporta patch diretta dei campi dell'item
            item = d.get("item", {})
            for k in ("scope","materials","labor","totals"):
                if k in data:
                    item[k] = data[k]
        d["item"] = item
        d["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
        drafts[draft_id] = d
        me["work_drafts"] = drafts

        if not _save_project_obj(obj, me):
            return jsonify({"ok": False, "error": "persistenza fallita"}), 500
        return jsonify({"ok": True, "draft_id": draft_id}), 200

    @app.post("/api/projects/<pid>/works/commit/<draft_id>")
    def api_commit_work_draft(pid: str, draft_id: str):
        """Sposta la bozza in `works` (lista) e la rimuove da work_drafts."""
        obj = _get_project_by_id(pid)
        if not obj:
            return jsonify({"error": "Progetto non trovato"}), 404

        # carica containers
        me, _ = _ensure_meta_extra_container(obj, "work_drafts")
        drafts = dict(me.get("work_drafts") or {})
        d = drafts.get(draft_id)
        if not d:
            return jsonify({"error": "Bozza non trovata"}), 404

        me, _ = _ensure_meta_extra_container(obj, "works")
        works_list = list(me.get("works") or [])

        item = d.get("item") or {}
        work_entry = {
            "work_id": str(uuid.uuid4())[:8],
            "work_name": item.get("scope") or item.get("work") or "lavoro",
            "materials": item.get("materials") or [],
            "labor": item.get("labor") or [],
            "totals": item.get("totals") or {},
            "created_at": datetime.utcnow().isoformat(timespec="seconds"),
        }
        works_list.append(work_entry)
        me["works"] = works_list
        # rimuovi la bozza
        drafts.pop(draft_id, None)
        me["work_drafts"] = drafts

        if not _save_project_obj(obj, me):
            return jsonify({"ok": False, "error": "persistenza fallita"}), 500
        return jsonify({"ok": True, "work": work_entry}), 201

    @app.post("/api/projects/<pid>/works/bulk")
    def api_commit_works_bulk(pid: str):
        """Aggiunge una o più voci di lavoro direttamente a `works`.
        Body: { items: [ { scope, materials[], labor[], totals{} }, ... ] }
        """
        data = request.get_json(force=True) or {}
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            return jsonify({"error": "items deve essere una lista non vuota"}), 400

        obj = _get_project_by_id(pid)
        if not obj:
            return jsonify({"error": "Progetto non trovato"}), 404

        me, _ = _ensure_meta_extra_container(obj, "works")
        works_list = list(me.get("works") or [])

        created = []
        for it in items:
            if not isinstance(it, dict):
                continue
            work_entry = {
                "work_id": str(uuid.uuid4())[:8],
                "work_name": it.get("scope") or it.get("work") or "lavoro",
                "materials": it.get("materials") or [],
                "labor": it.get("labor") or [],
                "totals": it.get("totals") or {},
                "created_at": datetime.utcnow().isoformat(timespec="seconds"),
            }
            created.append(work_entry)
            works_list.append(work_entry)
        me["works"] = works_list

        if not _save_project_obj(obj, me):
            return jsonify({"ok": False, "error": "persistenza fallita"}), 500
        return jsonify({"ok": True, "created": created, "count": len(created)}), 201
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
    from routes.work_catalog import workcat_bp
    from routes.schedule import schedule_bp

    app.register_blueprint(views_bp)                    # pagine HTML
    app.register_blueprint(api_bp, url_prefix="/api")   # API legacy/varie
    app.register_blueprint(materials_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(estimate_bp)
    app.register_blueprint(schedule_bp)                 # capacità/overbooking API
    app.register_blueprint(chat_bp, url_prefix="/api")
    app.register_blueprint(company_bp)
    app.register_blueprint(workcat_bp)

    
    # Log delle rotte per debug
    try:
        for rule in app.url_map.iter_rules():
            log.info("ROUTE: %s → endpoint=%s methods=%s", rule, rule.endpoint, ",".join(sorted(rule.methods)))
    except Exception:
        pass
    return app