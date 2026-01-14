# routes/chat.py
import os
import uuid
import logging
from flask import Blueprint, request, jsonify, session, g, current_app
import re
from mongoengine.connection import get_db

from services.chat_service import ChatService
from bson import ObjectId
from models_mongo.project import ProjectDoc

log = logging.getLogger("chat")
chat_bp = Blueprint("chat", __name__, url_prefix="/api")

def get_chat_service():
    """Factory per inizializzare il servizio con le dipendenze request-scoped."""
    vs = getattr(g, "vector_store", None)
    cm = getattr(g, "chat_model", None)
    wr = getattr(g, "web_retriever", None)
    rt = getattr(g, "router", None)
    
    # Fallback mode: crea istanze basic se mancanti
    if not cm:
        log.warning("chat_model missing, creating fallback instance")
        try:
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY")
            if api_key:
                from models.chat_model import ChatModel
                cm = ChatModel(
                    api_key=api_key,
                    model_name=os.getenv("MODEL_NAME", "gemini-2.0-flash-exp"),
                    temperature=0.1
                )
                g.chat_model = cm
            else:
                log.error("No API key found (GOOGLE_API_KEY or OPENAI_API_KEY)")
                return None
        except Exception as e:
            log.error(f"Failed to create fallback chat_model: {e}")
            return None
    
    if not vs:
        log.warning("vector_store missing, creating fallback instance")
        try:
            from models.vector_store import VectorStore
            vs = VectorStore(
                path=os.getenv("QDRANT_PATH", "./qdrant_data"),
                collection_name=os.getenv("QDRANT_COLLECTION", "documents"),
                embedding_model=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
                embedding_dim=int(os.getenv("EMBEDDING_DIMENSION", "384"))
            )
            g.vector_store = vs
        except Exception as e:
            log.warning(f"Failed to create fallback vector_store: {e}")
    
    if not wr:
        try:
            from utils.web_retriever import WebRetriever
            wr = WebRetriever(max_results=5, timeout=8)
            g.web_retriever = wr
            current_app.logger.info("✅ WebRetriever creato in fallback route")
        except Exception as e:
            current_app.logger.warning(f"WebRetriever fallback failed: {e}")
    
    if not rt:
        try:
            from utils.intent_router import IntentRouter
            rt = IntentRouter()
            g.router = rt
        except Exception as e:
            log.warning(f"Failed to create router: {e}")
    
    return ChatService(vector_store=vs, chat_model=cm, web_retriever=wr, router=rt)


# ----------------------
# Project id normalization
# ----------------------

def normalize_project_id(pid: str | None) -> str | None:
    """Normalize project identifiers coming from the frontend.

    Accepts either a Mongo ObjectId (string) or a human-readable site/code.
    If `pid` is not an ObjectId, we try to resolve it to the project's Mongo `_id`
    by looking up the project in Mongo.

    NOTE: In this repo, many UIs use the project `name` as a site/code (e.g. ROMA-54321).
    """
    if not pid:
        return None

    pid = str(pid).strip()

    # 1) If it's already a valid ObjectId string, keep it
    try:
        ObjectId(pid)
        return pid
    except Exception:
        pass

    # 2) Otherwise try to resolve to the Mongo `_id`
    try:
        qs = ProjectDoc.objects

        # Some deployments may have a dedicated `site_id` field; guard against missing schema.
        p = None
        if "site_id" in getattr(ProjectDoc, "_fields", {}):
            p = qs(site_id=pid).first()

        if not p:
            # In this repo the site/code often corresponds to `name`
            p = qs(name=pid).first()

        return str(p.id) if p else pid
    except Exception as e:
        log.warning(f"normalize_project_id failed for '{pid}': {e}")
        return pid


# ----------------------
# Lightweight DB-first intents (fast answers, no LLM)
# ----------------------

_RE_SPACE = re.compile(r"\s+")


def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    # remove common punctuation that breaks exact-match intents like "cantieri creati?"
    s = re.sub(r"[\?\!\.,:;]+", " ", s)
    s = _RE_SPACE.sub(" ", s).strip()
    return s


import collections

# --- Regexes for new DB-first chat patterns ---
_RE_WORKERS_ROLE_AVAIL = re.compile(
    r"\b(?P<quant>(quanti|numero))\s+(?P<role>.+?)(?:\s+sono)?\s+(disponibil[ei]?|liber[io]?)\b",
    re.IGNORECASE,
)
_RE_PROJECT_ASSIGN = re.compile(
    r"\bassegnat[ioa]*\b.*\b(cantiere|progetto)\b", re.IGNORECASE
)
_RE_QUOTED = re.compile(r"['\"]([^'\"]+)['\"]|“([^”]+)”")
_RE_AFTER_CANTIERE = re.compile(r"\b(?:cantiere|progetto)\s+([^\.]+)", re.IGNORECASE)

# --- Region extraction helpers ---
_IT_REGIONS = {
    "abruzzo", "basilicata", "calabria", "campania", "emilia-romagna", "emilia romagna",
    "friuli-venezia giulia", "friuli venezia giulia", "lazio", "liguria", "lombardia",
    "marche", "molise", "piemonte", "puglia", "sardegna", "sicilia", "toscana",
    "trentino-alto adige", "trentino alto adige", "umbria", "valle d'aosta", "valle d’aosta",
    "veneto",
}

_REGION_ALIASES = {
    "emilia romagna": "emilia-romagna",
    "friuli venezia giulia": "friuli-venezia giulia",
    "trentino alto adige": "trentino-alto adige",
    "valle d’aosta": "valle d'aosta",
}

_RE_IN_REGION = re.compile(
    r"\b(?:in|nel|nella|nelle|nei|sul|sulla)\s+(?P<place>[A-Za-zÀ-ÿ\-\'’\s]+)\b",
    re.IGNORECASE,
)

def _extract_region(message: str) -> str | None:
    """Estrae una regione italiana da frasi tipo '... in Sicilia' o '... nel Lazio'.
    Ritorna la regione normalizzata (es. 'emilia-romagna') oppure None.
    """
    if not message:
        return None

    # 1) prova match diretto dopo preposizione
    m = _RE_IN_REGION.search(message)
    if not m:
        return None

    place = (m.group("place") or "").strip().lower()
    place = _RE_SPACE.sub(" ", place)

    # riduci a max 3 token (evita di catturare troppo testo)
    toks = place.split()[:3]
    place = " ".join(toks).strip()

    # normalizza apostrofi
    place = place.replace("’", "'")

    # se già è una regione, ok
    if place in _IT_REGIONS:
        return _REGION_ALIASES.get(place, place)

    # prova versione con trattino/spazi
    place_dash = place.replace(" ", "-")
    if place_dash in _IT_REGIONS:
        return _REGION_ALIASES.get(place_dash, place_dash)

    # prova versione con spazi
    place_space = place.replace("-", " ")
    if place_space in _IT_REGIONS:
        return _REGION_ALIASES.get(place_space, place_space)

    return None

# --- City -> Region fallback (used when home_region is missing in DB) ---
_CITY_TO_REGION = {
    # Lazio
    "roma": "lazio",
    "latina": "lazio",
    "frosinone": "lazio",
    "rieti": "lazio",
    "viterbo": "lazio",

    # Sicilia
    "palermo": "sicilia",
    "catania": "sicilia",
    "messina": "sicilia",
    "siracusa": "sicilia",
    "ragusa": "sicilia",
    "trapani": "sicilia",
    "agrigento": "sicilia",
    "enna": "sicilia",
    "caltanissetta": "sicilia",

    # Lombardia
    "milano": "lombardia",
    "bergamo": "lombardia",
    "brescia": "lombardia",
    "como": "lombardia",
    "varese": "lombardia",
    "monza": "lombardia",
    "pavia": "lombardia",

    # Piemonte
    "torino": "piemonte",
    "novara": "piemonte",
    "alessandria": "piemonte",
    "asti": "piemonte",
    "cuneo": "piemonte",

    # Campania
    "napoli": "campania",
    "salerno": "campania",
    "caserta": "campania",
    "avellino": "campania",
    "benevento": "campania",

    # Veneto
    "venezia": "veneto",
    "verona": "veneto",
    "padova": "veneto",
    "treviso": "veneto",
    "vicenza": "veneto",

    # Emilia-Romagna
    "bologna": "emilia-romagna",
    "modena": "emilia-romagna",
    "parma": "emilia-romagna",
    "reggio emilia": "emilia-romagna",
    "rimini": "emilia-romagna",
    "ferrara": "emilia-romagna",

    # Toscana
    "firenze": "toscana",
    "pisa": "toscana",
    "livorno": "toscana",
    "siena": "toscana",
    "arezzo": "toscana",

    # Puglia
    "bari": "puglia",
    "lecce": "puglia",
    "taranto": "puglia",
    "foggia": "puglia",
    "brindisi": "puglia",

    # Calabria
    "reggio calabria": "calabria",
    "catanzaro": "calabria",
    "cosenza": "calabria",

    # Sardegna
    "cagliari": "sardegna",
    "sassari": "sardegna",

    # Liguria
    "genova": "liguria",
    "la spezia": "liguria",

    # Marche
    "ancona": "marche",

    # Umbria
    "perugia": "umbria",

    # Abruzzo
    "l'aquila": "abruzzo",
    "pescara": "abruzzo",
}

def _infer_region_from_city(city: str | None) -> str | None:
    if not city:
        return None
    c = str(city).strip().lower().replace("’", "'")
    c = _RE_SPACE.sub(" ", c)
    return _CITY_TO_REGION.get(c)

def _quick_db_answer(message: str, project_id: str | None = None):
    """Handle very common operational questions directly via Mongo.

    This improves chat UX: avoids generic 'no data' replies when DB already has data.
    Returns a response dict or None.
    """
    tl = _norm_text(message)

    # Avoid treating assignment questions as availability questions
    if any(w in tl for w in ["assegnat", "assegnati", "assegnato"]) and ("cantiere" in tl or "progetto" in tl):
        # let PROJECT_ASSIGNED_WORKERS handle it
        return None

    # Workers: total
    if any(k in tl for k in ["operai totali", "personale totale", "totale operai", "totale personale"]):
        try:
            db = get_db()
            total = int(db["workers"].count_documents({}))
            avail = int(db["workers"].count_documents({"available": True}))
            # Breakdown by role (top 8)
            pipeline = [
                {"$group": {"_id": {"$ifNull": ["$role", "(senza ruolo)"]}, "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 8},
            ]
            roles = list(db["workers"].aggregate(pipeline))
            roles_str = ", ".join([f"{r.get('_id')}: {int(r.get('count') or 0)}" for r in roles])
            ans = f"Personale totale: {total}. Disponibili ora: {avail}."
            if roles_str:
                ans += f"\nRuoli (top): {roles_str}"
            return {"INTENT_DB": "WORKERS_TOTAL", "answer": ans, "total": total, "available": avail}
        except Exception as e:
            log.warning(f"quick_db_answer WORKERS_TOTAL failed: {e}")

    # Workers: available / free
    if (
        ("operai" in tl or "personale" in tl or "lavoratori" in tl)
        and any(k in tl for k in ["disponibili", "liberi", "libero", "available"])
    ):
        try:
            db = get_db()
            region = _extract_region(message)

            base_query = {"available": True}
            region_filter_applied = False
            inferred_used = False

            if region:
                # Hybrid count: use home_region when present, otherwise infer from city
                region_filter_applied = True

                q_region = {
                    **base_query,
                    "home_region": {"$regex": f"^{re.escape(region)}$", "$options": "i"},
                }
                avail_region = int(db["workers"].count_documents(q_region))

                # Count workers with missing/empty home_region and infer from city
                missing_region_q = {
                    **base_query,
                    "$or": [
                        {"home_region": {"$exists": False}},
                        {"home_region": None},
                        {"home_region": ""},
                    ],
                }
                cur = db["workers"].find(missing_region_q, {"home_city": 1, "_id": 0})
                avail_inferred = 0
                for w in cur:
                    inf = _infer_region_from_city(w.get("home_city"))
                    if inf == region:
                        avail_inferred += 1
                inferred_used = avail_inferred > 0

                avail = avail_region + avail_inferred
            else:
                avail = int(db["workers"].count_documents(base_query))
            total = int(db["workers"].count_documents({}))

            if region and region_filter_applied:
                ans = f"Operai disponibili in {region.title()}: {avail} (totale azienda: {total})."
                if inferred_used:
                    ans += " (Regione stimata dalla città.)"
            else:
                ans = f"Operai disponibili: {avail} su {total}."

            return {
                "INTENT_DB": "WORKERS_AVAILABLE",
                "answer": ans,
                "available": avail,
                "total": total,
                "region": region,
                "region_filter_applied": bool(region_filter_applied),
                "inferred_region_used": bool(inferred_used),
            }
        except Exception as e:
            log.warning(f"quick_db_answer WORKERS_AVAILABLE failed: {e}")

    # Workers: available by role
    try:
        m = _RE_WORKERS_ROLE_AVAIL.search(message)
        if m:
            # Only trigger if message contains quanti/numero and disponibil/liber
            role_raw = m.group("role") or ""
            # Remove common filler words, articles, plurals
            fillers = [
                "sono", "gli", "i", "le", "l'", "lo", "la", "il", "dei", "degli", "delle", "del", "della",
                "operai", "lavoratori", "personale"
            ]
            role_norm = role_raw
            # Remove each filler if present at start
            for f in fillers:
                role_norm = re.sub(rf"^{f}\s+", "", role_norm, flags=re.IGNORECASE)
            # Remove each filler if present at end
            for f in fillers:
                role_norm = re.sub(rf"\s+{f}$", "", role_norm, flags=re.IGNORECASE)
            role_norm = role_norm.strip().lower()
            # Minimal plural -> singular mapping (case-insensitive)
            plural_map = {
                "muratori": "muratore",
                "elettricisti": "elettricista",
                "idraulici": "idraulico",
                "imbianchini": "imbianchino",
                "carpentieri": "carpentiere",
                "intonacatori": "intonacatore",
                "piastrellisti": "piastrellista",
                "cartongessisti": "cartongessista",
                "capi cantiere": "capo cantiere",
                "capicantiere": "capo cantiere",
            }
            for k, v in plural_map.items():
                if role_norm == k:
                    role_norm = v
            # Remove trailing/leading spaces again
            role_norm = role_norm.strip()
            if not role_norm:
                return None
            db = get_db()

            region = _extract_region(message)

            query = {
                "available": True,
                "role": {"$regex": f"^{re.escape(role_norm)}$", "$options": "i"},
            }

            inferred_used = False
            if region:
                region_filter_applied = True

                q_region = {
                    "available": True,
                    "role": query["role"],
                    "home_region": {"$regex": f"^{re.escape(region)}$", "$options": "i"},
                }
                count_region = int(db["workers"].count_documents(q_region))

                missing_region_q = {
                    "available": True,
                    "role": query["role"],
                    "$or": [
                        {"home_region": {"$exists": False}},
                        {"home_region": None},
                        {"home_region": ""},
                    ],
                }
                cur = db["workers"].find(missing_region_q, {"home_city": 1, "_id": 0})
                count_inferred = 0
                for w in cur:
                    inf = _infer_region_from_city(w.get("home_city"))
                    if inf == region:
                        count_inferred += 1
                inferred_used = count_inferred > 0

                count = count_region + count_inferred
            else:
                count = int(db["workers"].count_documents(query))

            # Pluralization: use singular label and "disponibile" if count==1, else plural and "disponibili"
            role_label = role_norm.capitalize()
            if region:
                if count == 1:
                    ans = f"{role_label} disponibile in {region.title()}: {count}."
                else:
                    ans = f"{role_label} disponibili in {region.title()}: {count}."
                if inferred_used:
                    ans += " (Regione stimata dalla città.)"
                region_filter_applied = True
            else:
                if count == 1:
                    ans = f"{role_label} disponibile: {count}."
                else:
                    ans = f"{role_label} disponibili: {count}."
                region_filter_applied = False

            return {
                "INTENT_DB": "WORKERS_AVAILABLE_BY_ROLE",
                "answer": ans,
                "role": role_norm,
                "available": count,
                "region": region,
                "region_filter_applied": bool(region_filter_applied),
                "inferred_region_used": bool(inferred_used) if region else False,
            }
    except Exception as e:
        log.warning(f"quick_db_answer WORKERS_AVAILABLE_BY_ROLE failed: {e}")

    # Projects: assigned workers
    try:
        if (
            any(w in tl for w in ["assegnat", "assegnati", "assegnato"])
            and ("cantiere" in tl or "progetto" in tl)
        ):
            db = get_db()
            target = None
            # Prefer quoted project name
            m = _RE_QUOTED.search(message)
            if m:
                target = m.group(1) or m.group(2)
            if not target:
                # Try after "cantiere" or "progetto"
                m2 = _RE_AFTER_CANTIERE.search(message)
                if m2:
                    target = m2.group(1)
                    # Remove trailing question marks, dots, etc.
                    target = target.strip().strip(".!?")
            if not target:
                return None
            target = target.strip()
            # Try to find project by id (exact match)
            project_doc = None
            project_name = None
            pid = None
            for coll in ["projects", "project_drafts"]:
                if coll in db.list_collection_names():
                    doc = db[coll].find_one({"id": target})
                    if doc:
                        project_doc = doc
                        pid = doc.get("id")
                        project_name = doc.get("name", pid)
                        break
            # If not found, try by name (case-insensitive regex)
            if not project_doc:
                regex = {"$regex": re.escape(target), "$options": "i"}
                for coll in ["projects", "project_drafts"]:
                    if coll in db.list_collection_names():
                        doc = db[coll].find_one({"name": regex})
                        if doc:
                            project_doc = doc
                            pid = doc.get("id")
                            project_name = doc.get("name", pid)
                            break
            if not project_doc:
                ans = f"Non trovo nessun cantiere o progetto con identificativo '{target}'."
                return {
                    "INTENT_DB": "PROJECT_ASSIGNED_WORKERS",
                    "answer": ans,
                    "project_id": None,
                    "project_name": target,
                    "assigned_count": 0,
                    "roles_breakdown": {},
                    "workers_preview": [],
                }
            # Find assignments
            worker_ids = set()
            if "assignments" in db.list_collection_names():
                # assignments collection: project_id -> worker_ids
                assign_docs = list(db["assignments"].find({"project_id": pid}))
                for ad in assign_docs:
                    wid = ad.get("worker_id") or ad.get("worker_ids")
                    if isinstance(wid, list):
                        worker_ids.update(wid)
                    elif wid:
                        worker_ids.add(wid)
            elif project_doc.get("assignments"):
                for a in project_doc.get("assignments", []):
                    wid = a.get("worker_id") or a.get("id")
                    if wid:
                        worker_ids.add(wid)
            elif project_doc.get("schedule"):
                for sch in project_doc.get("schedule", []):
                    assigned = sch.get("assigned")
                    if assigned and isinstance(assigned, dict):
                        for wid in assigned.values():
                            if wid:
                                worker_ids.add(wid)
            # Remove falsy ids
            worker_ids = {w for w in worker_ids if w}
            if not worker_ids:
                ans = f"Per il cantiere {project_name} non risultano operai assegnati."
                return {
                    "INTENT_DB": "PROJECT_ASSIGNED_WORKERS",
                    "answer": ans,
                    "project_id": pid,
                    "project_name": project_name,
                    "assigned_count": 0,
                    "roles_breakdown": {},
                    "workers_preview": [],
                }
            # Fetch workers
            workers = list(db["workers"].find({"id": {"$in": list(worker_ids)}}, {"id": 1, "name": 1, "role": 1, "available": 1}))
            roles_counter = collections.Counter()
            preview = []
            for w in workers:
                role = w.get("role", "(senza ruolo)")
                roles_counter[role] += 1
                preview.append(f"{w.get('name', 'N/D')} ({role}, {w.get('id', 'N/D')})")
            assigned_count = len(workers)
            # Short answer
            roles_str = ", ".join(f"{r}: {n}" for r, n in roles_counter.most_common())
            ans = f"Assegnati al cantiere {project_name}: {assigned_count} lavoratori."
            if roles_str:
                ans += f" Ruoli: {roles_str}."
            if preview:
                ans += "\nEsempi: " + "; ".join(preview[:10])
            return {
                "INTENT_DB": "PROJECT_ASSIGNED_WORKERS",
                "answer": ans,
                "project_id": pid,
                "project_name": project_name,
                "assigned_count": assigned_count,
                "roles_breakdown": dict(roles_counter),
                "workers_preview": preview[:10],
            }
    except Exception as e:
        log.warning(f"quick_db_answer PROJECT_ASSIGNED_WORKERS failed: {e}")

    # Projects: count
    if any(k in tl for k in ["cantieri", "cantiere", "progetti", "progetto"]):
        # Keep it strict: only short, direct questions about how many projects exist
        direct_q = tl in {
            "cantieri",
            "cantieri creati",
            "quanti cantieri",
            "numero cantieri",
            "elenco cantieri",
            "lista cantieri",
            "progetti",
            "progetti creati",
            "quanti progetti",
            "numero progetti",
            "elenco progetti",
            "lista progetti",
        }
        # Also allow the common "<something> creati" form
        if direct_q or tl.endswith("cantieri creati") or tl.endswith("progetti creati"):
            try:
                db = get_db()
                n_projects = int(db["projects"].count_documents({})) if "projects" in db.list_collection_names() else 0
                n_drafts = int(db["project_drafts"].count_documents({})) if "project_drafts" in db.list_collection_names() else 0
                total = n_projects + n_drafts
                ans = f"Cantieri/progetti presenti: {total} (Confermati: {n_projects}, Bozze: {n_drafts})."
                return {"INTENT_DB": "PROJECTS_COUNT", "answer": ans, "projects": n_projects, "drafts": n_drafts}
            except Exception as e:
                log.warning(f"quick_db_answer PROJECTS_COUNT failed: {e}")

    return None


# ----------------------
# Response post-processing (hide debug blocks, reduce noise)
# ----------------------

_RE_CODEBLOCK_JSON = re.compile(r"```json\s*[\s\S]*?```", re.IGNORECASE)
_RE_INLINE_CALC = re.compile(r"\[calc_json\]", re.IGNORECASE)
_RE_SOURCES_BLOCK = re.compile(
    r"\n?\s*Fonti interne:\s*(?:\(nessuna\)|—)?\s*\n\s*Fonti web:\s*(?:\(nessuna\)|—)?\s*\n?",
    re.IGNORECASE,
)
_RE_HO_RILEVATO = re.compile(r"\n?\s*Ho rilevato\s+\d+\s+lavorazioni\.[\s\S]*$", re.IGNORECASE)
_RE_URL = re.compile(r"(https?://[^\s\)]+|www\.[^\s\)]+)", re.IGNORECASE)


def _clean_answer_text(answer: str, has_items: bool) -> str:
    if not answer:
        return answer
    out = str(answer)
    out = _RE_INLINE_CALC.sub("", out)
    out = _RE_CODEBLOCK_JSON.sub("", out)
    # If no items/tables, drop boilerplate about detected works
    if not has_items:
        out = _RE_HO_RILEVATO.sub("", out)
    # If sources are empty, remove the empty sources block
    out = _RE_SOURCES_BLOCK.sub("\n", out)

    # If the model included web URLs but didn't format them under "Fonti web:", add a sources section.
    urls = list(dict.fromkeys(_RE_URL.findall(out)))  # preserve order, remove duplicates
    has_fonti_web = re.search(r"^\s*Fonti\s+web:\s*$", out, flags=re.IGNORECASE | re.MULTILINE) is not None
    if urls and not has_fonti_web:
        out = out.rstrip() + "\n\nFonti web:\n" + "\n".join([f"- {u}" for u in urls]) + "\n"

    # Normalize extra blank lines
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def _postprocess_response(resp: dict) -> dict:
    if not isinstance(resp, dict):
        return resp

    has_items = False
    if isinstance(resp.get("ui_tables"), dict):
        ui_items = resp["ui_tables"].get("items")
        has_items = bool(ui_items)
    if resp.get("items"):
        has_items = True

    if isinstance(resp.get("answer"), str):
        resp["answer"] = _clean_answer_text(resp.get("answer"), has_items)

    # Keep any debug payload but avoid exposing calc_json-like blobs inside the main answer
    return resp


@chat_bp.post("/chat")
def chat_route():
    """Main chat endpoint."""
    data = request.get_json(force=True) or {}
    message = data.get("message") or data.get("question")
    project_id = data.get("project_id") or data.get("site_id")
    
    # Compatibilità con enforced_pid
    enforced_pid = data.get("__enforced_pid")
    if enforced_pid:
        project_id = enforced_pid

    # Normalize project id so upload + chat use the same identifier
    project_id = normalize_project_id(project_id)
    
    if not message:
        return jsonify({"error": "Messaggio vuoto"}), 422

    quick = _quick_db_answer(message, project_id=project_id)
    if quick:
        return jsonify(quick), 200

    # Gestione Sessione
    if not session.get("sid"):
        session["sid"] = str(uuid.uuid4())
    
    try:
        service = get_chat_service()
        
        if not service:
            return jsonify({"error": "Chat service not available. Please configure AI dependencies."}), 503
        
        response = service.process_message(
            question=message,
            session_id=session["sid"],
            project_id=project_id,
            user_context={"user": g.get("user")}
        )
        response = _postprocess_response(response)
        return jsonify(response), 200
        
    except Exception as e:
        log.exception("Chat error")
        return jsonify({"error": str(e)}), 500

@chat_bp.post("/chat/project/<pid>")
def chat_project_route(pid):
    """Chat vincolata a un progetto."""
    data = request.get_json(force=True) or {}
    message = data.get("message") or data.get("question")
    
    if not message:
        return jsonify({"error": "Messaggio vuoto"}), 422
    
    pid = normalize_project_id(pid)

    quick = _quick_db_answer(message, project_id=pid)
    if quick:
        return jsonify(quick), 200
    
    # Gestione Sessione
    if not session.get("sid"):
        session["sid"] = str(uuid.uuid4())
    
    try:
        service = get_chat_service()
        if not service:
            return jsonify({"error": "Chat service not available. Please configure AI dependencies."}), 503
        
        response = service.process_message(
            question=message,
            session_id=session["sid"],
            project_id=pid,
            user_context={"user": g.get("user")}
        )
        response = _postprocess_response(response)
        return jsonify(response), 200
    except Exception as e:
        log.exception("Chat Project error")
        return jsonify({"error": str(e)}), 500