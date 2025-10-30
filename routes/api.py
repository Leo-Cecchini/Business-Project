# routes/api.py
# API routes (compatibile con app.extensions / g.*)
from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Optional, Tuple

from flask import Blueprint, request, jsonify, session, current_app, g
from werkzeug.utils import secure_filename

# --- Utils guardrail / web / comparator / prezzi ---
from utils.policy import decide_policy
from utils.price_extractor import extract_prices, pick_best
from utils.comparator import build_comparison

# --- Modelli MongoDB ---
from models_mongo.worker import WorkerDoc
from models_mongo.material import MaterialDoc

# --- LLM intent parser (staff) opzionale ---
from utils.intent_router import parse_intent_llm

# -----------------------------------------------------------------------------
# Blueprint
# -----------------------------------------------------------------------------

api_bp = Blueprint("api", __name__)

# =============================================================================
# 0) HELPERS ESTIMATE (preventivo/stima lavori)
# =============================================================================

ESTIMATE_MARKERS = [
    "stima", "preventivo", "computo", "computometrico",
    "ristrutturazione", "ristrutturare", "ristrutturazione completa",
    "mq", "metri quadri", "bagno", "bagni", "cucina",
    "punti luce", "punto luce", "prese", "prese elettriche",
    "impianto elettrico", "impianto di luce", "impianto idrico",
    "idraulico", "scarichi", "tubi", "boiler", "caldaia",
    "pavimento", "rivestimento", "gres", "60x120", "60x60", "posa piastrelle",
]

def _looks_like_estimate(q: str) -> bool:
    ql = (q or "").lower()
    return any(m in ql for m in ESTIMATE_MARKERS)

# =============================================================================
# 1) HELPERS STAFF (lingua + query)
# =============================================================================

# Canonici + alias per normalizzare i ruoli
ROLE_ALIASES = {
    "elettricista": ["elettricista", "elettrici", "elettrico"],
    "idraulico": ["idraulico", "idraulici", "impianto idrico", "impiantista idrico"],
    "muratore": ["muratore", "muratori"],
    "capo muratore": ["capo muratore", "capomuratore", "capo squadra muratori"],
    "carpentiere": ["carpentiere", "carpentieri", "carpenteria"],
    "cartongessista": ["cartongessista", "cartongesso", "lastre gesso"],
    "imbianchino": ["imbianchino", "pittore edile", "tinteggiatore"],
    "serramentista": ["serramentista", "posa serramenti", "infissi", "posatore serramenti"],
    "piastrellista": ["piastrellista", "pavimentista", "posa piastrelle"],
    "capocantiere": ["capocantiere", "capo cantiere"],
}

# Plurali e articoli determinativi corretti
PLURALS = {
    "elettricista": "elettricisti",
    "idraulico": "idraulici",
    "muratore": "muratori",
    "capo muratore": "capi muratori",
    "carpentiere": "carpentieri",
    "cartongessista": "cartongessisti",
    "imbianchino": "imbianchini",
    "serramentista": "serramentisti",
    "piastrellista": "piastrellisti",
    "capocantiere": "capicantiere",
}
ART_DEF_PL = {
    "elettricista": "Gli",
    "idraulico": "Gli",
    "muratore": "I",
    "capo muratore": "I",
    "carpentiere": "I",
    "cartongessista": "I",
    "imbianchino": "Gli",
    "serramentista": "I",
    "piastrellista": "I",
    "capocantiere": "I",
}
GENERIC_PLURAL = "operai"
GENERIC_ART_PL = "Gli"


def role_plural(role: Optional[str]) -> str:
    """Restituisce il nome del ruolo al plurale (fallback: 'operai')."""
    if not role:
        return GENERIC_PLURAL
    return PLURALS.get(role, role + "s")


def role_article_plural(role: Optional[str]) -> str:
    """Restituisce l’articolo determinativo plurale corretto (fallback: 'Gli')."""
    if not role:
        return GENERIC_ART_PL
    return ART_DEF_PL.get(role, "I")


def np_article_plus_plural(role: Optional[str]) -> str:
    """Articolo + nome plurale (es. 'Gli idraulici')."""
    return f"{role_article_plural(role)} {role_plural(role)}"


def _norm_role_from_text(q: str) -> Optional[str]:
    """Inferenza semplice del ruolo a partire dal testo utente."""
    ql = q.lower()

    # parole generiche che NON definiscono un ruolo specifico → ritorna None
    generic_terms = [
        "operaio", "operai", "dipendente", "dipendenti",
        "personale", "staff", "lavoratori", "team", "organico", "forza lavoro"
    ]
    if any(t in ql for t in generic_terms):
        return None

    for role, aliases in ROLE_ALIASES.items():
        if any(a in ql for a in aliases):
            return role
    return None


def _looks_like_anaphora(q: str) -> bool:
    """Individua follow-up anaforici (es. 'e loro?', 'come prima?')."""
    ql = q.lower()
    hints = [
        "e loro", "loro?", "gli stessi", "quegli", "quelli",
        "come prima", "di prima", "quei", "gli stessi di prima",
        "e quelli", "e questi", "e i precedenti", "ancora loro", "sempre loro",
    ]
    return any(h in ql for h in hints)


def _query_workers(intent: dict):
    """Costruisce la queryset Mongo dei dipendenti a partire dall’intent."""
    q = WorkerDoc.objects
    role = intent.get("role")
    if role:
        q = q.filter(role__icontains=role)

    if intent.get("free_only"):
        # Usa il campo booleano 'available'
        q = q.filter(available=True)

    return q.order_by("role", "name")


def _remember_staff_ctx(intent: dict) -> None:
    """Memorizza l’ultimo intent staff nel contesto conversazionale."""
    session["staff_last"] = {
        "topic": "staff",
        "intent": {
            "operation": intent.get("operation", "list"),
            "role": intent.get("role"),
            "free_only": bool(intent.get("free_only", False)),
            "limit": int(intent.get("limit", 25)),
            "load_threshold_hours": float(intent.get("load_threshold_hours", intent.get("free_hours_threshold", 20.0))),
        },
    }


def _run_staff_intent(intent: dict) -> dict:
    """
    Esegue l’intent 'staff':
    - operation: "count" | "list" | "where" | "clarify" | "roles"
    """
    op = intent.get("operation", "list")
    role = intent.get("role") or None

    # Se manca il ruolo ma c’era nel turno precedente, riusalo SOLO se la query è anaforica
    if not role and session.get("staff_last") and session["staff_last"].get("intent", {}).get("role"):
        if _looks_like_anaphora(intent.get("question", "")) or intent.get("operation") == "clarify":
            role = session["staff_last"]["intent"]["role"]
            intent["role"] = role

    q = _query_workers(intent)

    # COUNT
    if op == "count":
        count = q.count()
        free_part = " liberi" if intent.get("free_only") else ""
        answer = f"Ci sono {count} {role_plural(role)}{free_part}."
        _remember_staff_ctx(intent)
        return {"handled": True, "answer": answer, "sources_internal": [], "sources_web": [],
                "staff_intent": intent, "staff_count": count}

    # WHERE (località sintetizzata)
    if op == "where":
        rows = q.limit(intent.get("limit", 25))
        rows = list(rows)
        if not rows:
            free_part = " liberi" if intent.get("free_only") else ""
            answer = f"Non ho trovato {role_plural(role)}{free_part}."
            _remember_staff_ctx(intent)
            return {"handled": True, "answer": answer, "sources_internal": [], "sources_web": [],
                    "staff_intent": intent, "staff": []}

        items = [{
            "id": str(getattr(w, "id", "")),
            "name": getattr(w, "name", None),
            "role": getattr(w, "role", None),
            "home_city": getattr(w, "home_city", None),
            "availability": getattr(w, "availability", None),
            "current_load": getattr(w, "current_load", None),
            "hourly_rate": getattr(w, "hourly_rate", None),
        } for w in rows]

        cities = {i["home_city"] for i in items if i.get("home_city")}
        city_str = (list(cities)[0] if len(cities) == 1
                    else (", ".join(sorted(cities)) if cities else "non specificato"))
        free_part = " liberi" if intent.get("free_only") else ""
        answer = f"{np_article_plus_plural(role)}{free_part} si trovano a: {city_str}."
        _remember_staff_ctx(intent)
        return {"handled": True, "answer": answer, "sources_internal": [], "sources_web": [],
                "staff_intent": intent, "staff": items}

    # CLARIFY (spiega la risposta precedente)
    if op == "clarify":
        last = session.get("staff_last", {})
        if last.get("topic") == "staff":
            prev = last.get("intent", {})
            role_prev = prev.get("role")
            count = None
            try:
                count = _query_workers(prev).count()
            except Exception:
                pass
            if count is not None:
                role_part = role_plural(role_prev) if role_prev else "persone"
                comment = "una bella squadra" if count >= 5 else "una squadra piccola ma efficiente"
                answer = f"Mi riferivo al conteggio di {count} {role_part}; direi che è {comment}."
            else:
                role_part = f" {role_prev}" if role_prev else ""
                free_part = " liberi" if prev.get("free_only") else ""
                answer = f"Mi riferivo al conteggio{role_part}{free_part} richiesto in precedenza."
            _remember_staff_ctx(prev)
            return {"handled": True, "answer": answer, "sources_internal": [], "sources_web": [],
                    "staff_intent": prev}

    # ROLES (elenco ruoli con conteggi)
    if op == "roles":
        try:
            roles_counts = list(WorkerDoc.objects.aggregate([
                {"$group": {"_id": "$role", "count": {"$sum": 1}}},
                {"$sort": {"_id": 1}}
            ]))
            if not roles_counts:
                answer = "Non ci sono ruoli registrati nel database dei dipendenti."
            else:
                parts = [f"{(r.get('_id') or 'Senza ruolo').lower()}: {int(r.get('count', 0))}" for r in roles_counts]
                answer = "Ruoli presenti tra i dipendenti: " + ", ".join(parts) + "."
        except Exception as e:
            print(f"[staff roles error] {e}")
            answer = "Errore durante il recupero dei ruoli dal database."
        _remember_staff_ctx(intent)
        return {"handled": True, "answer": answer, "sources_internal": [], "sources_web": [],
                "staff_intent": intent}

    # LIST (default)
    rows = list(q.limit(intent.get("limit", 25)))
    if not rows:
        free_part = " liberi" if intent.get("free_only") else ""
        answer = f"Non ho trovato {role_plural(role)}{free_part}."
        _remember_staff_ctx(intent)
        return {"handled": True, "answer": answer, "sources_internal": [], "sources_web": [],
                "staff_intent": intent, "staff": []}

    items = [{
        "id": str(getattr(w, "id", "")),
        "name": getattr(w, "name", None),
        "role": getattr(w, "role", None),
        "home_city": getattr(w, "home_city", None),
        "availability": getattr(w, "availability", None),
        "current_load": getattr(w, "current_load", None),
        "hourly_rate": getattr(w, "hourly_rate", None),
    } for w in rows]

    names = ", ".join(i["name"] for i in items if i.get("name"))
    free_part = " liberi" if intent.get("free_only") else ""
    answer = f"Ecco i primi {len(items)} {role_plural(role)}{free_part}: {names}."
    _remember_staff_ctx(intent)
    return {"handled": True, "answer": answer, "sources_internal": [], "sources_web": [],
            "staff_intent": intent, "staff": items}

# =============================================================================
# 2) HELPERS MATERIALI (price lookup DB-first, fallback web)
# =============================================================================

MATERIAL_PRICE_TRIGGERS = [
    "quanto costa", "prezzo", "costo", "quanto viene", "quanto è",
    "€/kg", "€/m2", "€/m³", "€/m3", "eur/kg",
    "nel database", "dal database", "nel dataset", "dal dataset",
    "nel database materiali", "dal database materiali",
]


def _looks_like_material_query(q: str) -> bool:
    ql = q.lower()
    # trigger prezzo/costo
    has_price = any(t in ql for t in ["quanto costa", "prezzo", "costo", "quanto viene", "quanto è", "€/","eur/"])
    # parole tipiche materiali + categorie opzionali
    is_material = any(t in ql for t in [
        "cemento","cartongesso","piastrel","gres","intonaco","colla","stucco","sabbia","calce",
        "rame","ferro","acciaio","bitume",
        # categorie opzionali
        "leganti","premiscelati"
    ])
    # collisione con "cartongessista": se c'è "cartongesso" consideralo materiale
    if "cartongesso" in ql:
        return has_price or is_material
    # evita collisione col ruolo "cartongessista/i" solo quando NON sta chiedendo prezzo
    if "cartongessist" in ql and not has_price:
        return False
    return has_price or is_material


def _normalize_text(s: str) -> str:
    """Rende robusto il parsing: niente accenti, compattazione spazi, lowercase."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_unit_from_text(q: str) -> Optional[str]:
    """Estrae unità (kg, m2, m3, pz) da testo naturale."""
    qn = _normalize_text(q)
    if re.search(r"\b(eur|€)?/?kg\b", qn) or re.search(r"\b(al|a)\s+kg\b", qn):
        return "kg"
    if (re.search(r"\b(eur|€)?/?m2\b", qn) or re.search(r"\b(eur|€)?/?mq\b", qn)
            or re.search(r"\b(al|a)\s+m2\b", qn) or re.search(r"\b(al|a)\s+mq\b", qn)):
        return "m2"
    if (re.search(r"\b(eur|€)?/?m3\b", qn) or re.search(r"\b(eur|€)?/?mc\b", qn)
            or re.search(r"\bmetro\s+cubo\b", qn) or re.search(r"\bmetri\s+cubi\b", qn)
            or re.search(r"\b(al|a)\s+m3\b", qn) or re.search(r"\b(al|a)\s+mc\b", qn)):
        return "m3"
    if re.search(r"\b(eur|€)?/?pz\b", qn) or re.search(r"\b(al|a)\s+pezzo\b", qn):
        return "pz"
    return None


def _material_name_guess(q: str) -> str:
    """Tenta di isolare il nome del materiale (tolti verbi, articoli, valuta/unità)."""
    qn = _normalize_text(q)
    stopwords = [
        "quanto", "costa", "costo", "prezzo", "viene", "vale",
        "nel", "dal", "del", "della", "dei", "degli", "delle",
        "database", "dataset", "materiali", "materiale",
        "il", "lo", "la", "i", "gli", "le",
        "in", "al", "a", "di", "da", "per", "con", "su",
        "al kg", "al m2", "al mq", "al m3", "al mc",
        "a kg", "a m2", "a mq", "a m3", "a mc",
        "eur/kg", "eur/m2", "eur/mq", "eur/m3", "eur/mc",
    ]
    for sw in stopwords:
        pat = r"\b" + re.escape(_normalize_text(sw)) + r"\b"
        qn = re.sub(pat, " ", qn)

    qn = re.sub(r"[€?/]", " ", qn)
    qn = re.sub(r"\s+", " ", qn).strip()
    return qn

def _extract_sku_from_text(q: str) -> Optional[str]:
    """
    Se l'utente scrive un codice tipo CEM425R, catturarlo.
    Regola semplice: 3–12 caratteri alfanumerici, almeno una lettera e un numero.
    """
    m = re.search(r"\b(?=[A-Z0-9]{3,12}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])[A-Z0-9]+\b", q.upper())
    return m.group(0) if m else None

def _lookup_material_in_db(name_like: str, unit: Optional[str]) -> Tuple[Optional[MaterialDoc], int]:
    """Cerca il materiale in MongoDB e ritorna (best_match, numero_corrispondenze).
    Priorità: SKU esatto (case-insensitive), poi nome; bonus se categoria/subcategoria sono citate nel testo.
    """
    # 0) Se nell'input c'è uno SKU, prova match diretto
    #    (recuperiamo anche l'unit perché arriva già calcolata a monte)
    sku = _extract_sku_from_text(name_like or "")
    if sku:
        hit = MaterialDoc.objects(sku__iexact=sku).first()
        if hit:
            # 1 solo match, ritorna subito
            return hit, 1

    # 1) Fallback: match per nome (case-insensitive, contains)
    if not name_like:
        return None, 0

    q = MaterialDoc.objects(name__icontains=name_like)
    if unit:
        q = q.filter(unit__iexact=unit)
    rows = list(q.order_by("name"))
    if not rows:
        # Seconda chance: cerca su category/subcategory se il nome è vago
        q2 = MaterialDoc.objects(__raw__={
            "$or": [
                {"category": {"$regex": name_like, "$options": "i"}},
                {"subcategory": {"$regex": name_like, "$options": "i"}},
            ]
        })
        if unit:
            q2 = q2.filter(unit__iexact=unit)
        rows = list(q2.order_by("category", "subcategory", "name"))
        if not rows:
            return None, 0

    nl = (name_like or "").lower()

    def _score(m: MaterialDoc) -> int:
        s = 0
        name_lower = (getattr(m, "name", "") or "").lower()
        unit_m = (getattr(m, "unit", "") or "").lower()
        cat_l = (getattr(m, "category", "") or "").lower()
        sub_l = (getattr(m, "subcategory", "") or "").lower()
        sku_l = (getattr(m, "sku", "") or "").lower()

        # Priorità a match forti
        if sku and sku_l == sku.lower(): s += 100  # già gestito sopra, ma keep per coerenza
        if name_lower == nl: s += 10
        if name_lower.startswith(nl): s += 5
        if nl in name_lower: s += 2

        # Bonus se la query “somiglia” a categoria/subcategoria (es. "leganti", "premiscelati")
        if nl and nl in cat_l: s += 2
        if nl and nl in sub_l: s += 2

        # Bonus se l'unità combacia
        if unit and unit_m == (unit or "").lower(): s += 1

        return s

    rows.sort(key=_score, reverse=True)
    return rows[0], len(rows)

# =============================================================================
# 2b) MATERIALS: quick lookup endpoints (debug/test)
# =============================================================================

@api_bp.route("/materials/search", methods=["GET"])
def materials_search():
    """
    Ricerca rapida materiali senza passare dalla chat.
    Esempi:
      /materials/search?q=cemento%2042.5r&unit=kg
      /materials/search?q=leganti&unit=kg
    """
    q = (request.args.get("q") or "").strip()
    unit = (request.args.get("unit") or "").strip() or None
    if not q:
        return jsonify({"error": "q is required"}), 400

    m, matches = _lookup_material_in_db(q, unit)
    if not m:
        return jsonify({
            "found": False,
            "matches": 0,
            "query": {"q": q, "unit": unit},
        }), 200

    mat = m.to_mongo().to_dict() if hasattr(m, "to_mongo") else {}
    return jsonify({
        "found": True,
        "matches": matches,
        "material": mat,
    }), 200


@api_bp.route("/materials/sku/<sku>", methods=["GET"])
def materials_by_sku(sku: str):
    """
    Fetch diretto per SKU (case-insensitive).
    Esempio: /materials/sku/CEM325R
    """
    if not sku:
        return jsonify({"error": "sku is required"}), 400
    hit = MaterialDoc.objects(sku__iexact=sku.strip().upper()).first()
    if not hit:
        return jsonify({"found": False, "sku": sku}), 200

    return jsonify({
        "found": True,
        "material": hit.to_mongo().to_dict() if hasattr(hit, "to_mongo") else {},
    }), 200

# =============================================================================
# 2c) HEALTH CHECKS
# =============================================================================

@api_bp.route("/health/app", methods=["GET"])
def health_app():
    """Liveness semplice dell'app."""
    return jsonify({"ok": True}), 200


@api_bp.route("/health/db", methods=["GET"])
def health_db():
    """Ping a MongoDB via mongoengine."""
    try:
        from mongoengine.connection import get_db
        db = get_db()
        db.command("ping")
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@api_bp.route("/health/qdrant", methods=["GET"])
def health_qdrant():
    """
    Verifica la connettività con Qdrant:
    - prova g.qdrant_client se presente
    - altrimenti prova g.vector_store (se espone un client o un metodo di lista collezioni)
    """
    try:
        qc = getattr(g, "qdrant_client", None)
        if qc is not None:
            # API standard python-client: get_collections()
            _ = qc.get_collections()
            return jsonify({"ok": True, "via": "g.qdrant_client"}), 200

        vs = getattr(g, "vector_store", None)
        if vs is None:
            return jsonify({"ok": False, "error": "No qdrant_client or vector_store on g"}), 500

        # Tentativi comuni sui wrapper
        if hasattr(vs, "client") and hasattr(vs.client, "get_collections"):
            _ = vs.client.get_collections()
            return jsonify({"ok": True, "via": "vector_store.client"}), 200

        # Alcuni wrapper espongono direttamente un metodo
        for meth in ("get_collections", "list_collections", "collections"):
            if hasattr(vs, meth) and callable(getattr(vs, meth)):
                _ = getattr(vs, meth)()
                return jsonify({"ok": True, "via": f"vector_store.{meth}()"}), 200

        return jsonify({"ok": False, "error": "Cannot detect Qdrant connectivity methods"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# =============================================================================
# 3) Upload / Documenti (RAG)
# =============================================================================

def allowed_file(filename, allowed_extensions):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions


@api_bp.route("/upload", methods=["POST"])
def upload_files():
    """Upload e indicizzazione documenti nel vector store."""
    vector_store = getattr(g, "vector_store", None)
    file_processor = getattr(g, "file_processor", None)

    if vector_store is None or file_processor is None:
        return jsonify({"error": "Server not initialized"}), 500

    if "files" not in request.files:
        return jsonify({"error": "No files provided"}), 400

    files = request.files.getlist("files")
    if not files or files[0].filename == "":
        return jsonify({"error": "No files selected"}), 400

    processed, errors = 0, []
    for file in files:
        if not allowed_file(file.filename, current_app.config["ALLOWED_EXTENSIONS"]):
            errors.append(f"{file.filename}: Invalid file type")
            continue
        try:
            filename = secure_filename(file.filename)
            file_data = file.read()
            chunks, metadatas = file_processor.process_file(file_data, filename)
            vector_store.add_documents(chunks, metadatas)
            processed += 1
        except Exception as e:
            errors.append(f"{file.filename}: {str(e)}")

    return jsonify({"success": True, "processed": processed, "errors": errors})


@api_bp.route("/documents", methods=["GET"])
def get_documents():
    """Lista dei documenti caricati nel vector store."""
    vector_store = getattr(g, "vector_store", None)
    if vector_store is None:
        return jsonify({"error": "Server not initialized"}), 500
    documents = vector_store.get_all_documents()
    return jsonify({"documents": documents})

# =============================================================================
# 4) CHAT (routing staff/materiali, RAG, web)
# =============================================================================

@api_bp.route("/chat", methods=["POST"])
def chat():
    """
    Chat endpoint con:
    - Routing staff con intent LLM + fallback euristico (short-circuit su DB)
    - Routing materiali DB-first (fallback web opzionale)
    - RAG locale
    - Web retrieval controllato
    - Comparator generico
    """
    vector_store = getattr(g, "vector_store", None)
    chat_model = getattr(g, "chat_model", None)
    web_ret = getattr(g, "web_retriever", None)

    if vector_store is None or chat_model is None:
        return jsonify({"error": "Server not initialized"}), 500

    data = request.get_json(force=True)
    question = (data.get("question") or data.get("message") or "").strip()
    if not question:
        return jsonify({"error": "Question is required"}), 400

    # Pre-inizializzazioni sicure per evitare NameError
    local_ctx, web_ctx = [], []
    price_suggestion, price_sources = None, []
    requested_mode = (data.get("source_mode") or data.get("sourceMode") or "local")
    mode = requested_mode.lower()
    web_focus = None
    ql = question.lower()

    # ------------------- ESTIMATE ROUTING (short-circuit) -------------------
    if _looks_like_estimate(ql):
        try:
            from routes.estimate import make_estimate_from_text
        except Exception as e:
            return jsonify({
                "handled": False,
                "topic": "estimate",
                "answer": "Modulo di stima non disponibile (routes/estimate.py).",
                "error": str(e),
            }), 200

        # Supporta sia make_estimate_from_text(text) sia varianti con kwargs
        try:
            res = make_estimate_from_text(question)
        except TypeError:
            # Fallback per versioni che accettano parametri espliciti
            res = make_estimate_from_text(
                question=question,
                materials_model=MaterialDoc,
                workers_model=WorkerDoc,
            )
        except Exception as e:
            return jsonify({
                "handled": False,
                "topic": "estimate",
                "answer": "Errore durante la generazione della stima.",
                "error": str(e),
            }), 200

        # Confeziona la risposta (compatibile col frontend)
        total = None
        try:
            total = (res or {}).get("project", {}).get("budget", {}).get("total")
        except Exception:
            total = None
        total_str = (f" ~ {float(total):.2f} €" if isinstance(total, (int, float)) else "")

        payload = {
            "handled": True,
            "topic": "estimate",
            "answer": (res.get("summary") or res.get("answer") or ("Stima generata" + total_str)) if isinstance(res, dict) else ("Stima generata" + total_str),
            "estimate": res,
        }
        return jsonify(payload), 200

    # ------------------- STAFF ROUTING -------------------
    last_ctx = session.get("staff_last")
    try:
        parsed = parse_intent_llm(chat_model.llm, question, last_ctx)
    except Exception:
        parsed = None

    def _ana(txt: str) -> bool:
        t = (txt or "").strip().lower()
        return any(kw in t for kw in [
            "e loro", "gli stessi", "gli stessi?", "e quelli", "e questi",
            "e gli altri", "e i precedenti", "quelli di prima", "gli stessi di prima",
            "come prima", "come quelli", "ancora loro", "sempre loro",
        ])

    # 1a) Parser LLM riuscito
    if parsed and getattr(parsed, "topic", None) == "staff" and getattr(parsed, "staff", None):
        intent = parsed.staff.dict()
        if last_ctx and last_ctx.get("topic") == "staff":
            if _ana(question):
                prev = dict(last_ctx.get("intent", {}))
                for k, v in intent.items():
                    if v not in (None, "", [], False):
                        prev[k] = v
                intent = prev
            else:
                if not intent.get("role"):
                    intent["role"] = None
        intent.setdefault("operation", "list")
        result = _run_staff_intent(intent)
        return jsonify(result), 200

    # 1b) Fallback euristico staff
    is_staffish = (
        any(w in ql for w in [
            "dipendenti", "dipendente", "operai", "staff", "personale",
            "lavoratori", "team", "impiegati", "impiegato", "organico", "forza lavoro",
            "ruolo", "ruoli",
        ]) or (_norm_role_from_text(ql) is not None)
    )
    is_ana = _looks_like_anaphora(question)

    if is_staffish or is_ana:
        last = session.get("staff_last", {})
        last_intent = (last.get("intent") or {}) if last.get("topic") == "staff" else {}

        # Heuristics base
        op = "list"
        if any(w in ql for w in ["quanti", "quante", "numero", "totale", "totali", "conta", "quanti abbiamo"]):
            op = "count"
        elif any(w in ql for w in ["dove", "in che città", "dove si trovano", "dove sono"]):
            op = "where"
        elif any(w in ql for w in ["ruoli", "mansioni", "che ruoli"]):
            op = "roles"
        elif is_ana:
            op = "clarify"

        role = _norm_role_from_text(ql) or last_intent.get("role")
        free_only = any(w in ql for w in ["liberi", "disponibili", "non occupati", "non assegnati"]) or bool(last_intent.get("free_only"))

        # -------- Guardrail come in intent_router --------
        # 1) Se ha individuato "roles" ma c'è un ruolo specifico o disponibilità → forza list
        if op == "roles" and (role or free_only):
            op = "list"

        # 2) Comandi telegrafici: "solo ..." → list
        if ql.startswith("solo ") or ql.startswith("solo gli ") or ql.startswith("solo i "):
            op = "list"
            # se il ruolo non è stato colto, ritenta un parse semplice
            if not role:
                role = _norm_role_from_text(ql)

        # 3) Se chiede disponibilità e non è count/where/clarify → list + free_only
        if free_only and op not in ("count", "where", "clarify"):
            op = "list"
            free_only = True

        intent = {
            "operation": op,
            "role": role,
            "free_only": free_only,
            "limit": 25,
            "load_threshold_hours": 20.0,
        }

        # follow-up
        if is_ana and not _norm_role_from_text(ql) and last_intent:
            intent.setdefault("operation", "clarify")

        result = _run_staff_intent(intent)
        return jsonify(result), 200

    # ---------------- MATERIALS ROUTING (DB-first) ----------------
    try:
        if _looks_like_material_query(question):
            unit = _extract_unit_from_text(question)
            name_like = _material_name_guess(question)

            # fallback: se la frase è generica, riusa l’ultimo materiale cercato
            if not name_like and session.get("material_last"):
                prev = session["material_last"]
                name_like = prev.get("name_like") or ""
                unit = unit or prev.get("unit")

            m, matches = _lookup_material_in_db(name_like, unit)

            # salva memoria ultimo lookup
            session["material_last"] = {"topic": "materials", "name_like": name_like, "unit": unit}

            if not m:
                unit_part = f" ({unit})" if unit else ""
                # Fallback web se abilitato
                if current_app.config.get("ENABLE_WEB_RETRIEVAL", False) and g.get("web_retriever"):
                    try:
                        web_hits = g.web_retriever.search(question, focus="price")
                    except Exception:
                        web_hits = []
                    if web_hits:
                        all_prices = []
                        for w in web_hits:
                            prices = extract_prices(w.get("text", ""))
                            if prices:
                                best = pick_best(prices, prefer_unit=unit or "kg")
                                if best:
                                    all_prices.append({
                                        "value": best["value"], "unit": best["unit"],
                                        "title": w.get("title"), "url": w.get("url"),
                                    })
                        if all_prices:
                            vals = sorted(p["value"] for p in all_prices)
                            mid = len(vals) // 2
                            med = vals[mid] if len(vals) % 2 == 1 else (vals[mid - 1] + vals[mid]) / 2
                            unit_web = all_prices[0]["unit"]
                            return jsonify({
                                "handled": True,
                                "answer": f"Nel database non trovo '{name_like}'{unit_part}. Dal web, prezzo indicativo ~ {med:.2f} €/{unit_web}.",
                                "found": False,
                                "matches": 0,
                                "price_suggestion": {"suggested": round(med, 2), "unit": unit_web},
                                "price_sources": all_prices[:5],
                            }), 200

                return jsonify({
                    "handled": True,
                    "answer": f"Nel database materiali non trovo '{name_like}'{unit_part}.",
                    "material_query": {"name_like": name_like, "unit": unit},
                    "found": False,
                    "matches": 0,
                }), 200

            price = getattr(m, "unit_price_eur_2025", None)
            unit_label = getattr(m, "unit", None) or unit or ""
            if price is None:
                return jsonify({
                    "handled": True,
                    "answer": f"‘{getattr(m, 'name', 'Materiale')}’ è presente nel database ma non ha un prezzo impostato.",
                    "material": m.to_mongo().to_dict() if hasattr(m, "to_mongo") else {},
                    "found": True,
                    "matches": matches,
                }), 200

            mat_dict = m.to_mongo().to_dict() if hasattr(m, "to_mongo") else {}
            stock = mat_dict.get("stock_qty")
            lead = mat_dict.get("lead_time_days")
            vat = mat_dict.get("vat_rate")

            extra_bits = []
            if isinstance(stock, (int, float)):
                extra_bits.append(f"stock: {int(stock)} {unit_label}")
            if isinstance(lead, (int, float)):
                extra_bits.append(f"lead time: {int(lead)} giorni")
            if isinstance(vat, (int, float)):
                extra_bits.append(f"IVA: {int(vat)}%")

            extra_str = (" (" + ", ".join(extra_bits) + ")") if extra_bits else ""

            return jsonify({
                "handled": True,
                "answer": f"Il prezzo di {m.name} è {price:.2f} €/{unit_label}{extra_str}.",
                "material": mat_dict,
                "price": price,
                "unit": unit_label,
                "found": True,
                "matches": matches,
            }), 200
    except Exception as e:
        return jsonify({
            "handled": False,
            "topic": "materials",
            "answer": "Errore durante il recupero del materiale dal database.",
            "error": str(e),
        }), 200

    # -------------------- RAG / WEB GENERICO --------------------
    pol = decide_policy(question)

    # Rispetta la config per l’uso web
    if not current_app.config.get("ENABLE_WEB_RETRIEVAL", False) and mode in ("web", "both"):
        mode = "local"

    if pol.blocked:
        return jsonify({
            "answer": f"Richiesta bloccata dalla policy: {pol.reason}",
            "policy_reason": pol.reason,
            "sources_internal": [],
            "sources_web": [],
        }), 200

    # 3a) Retrieval locale
    if pol.allow_local or mode in ("local", "both"):
        try:
            hits = vector_store.search(question, limit=6)
        except Exception:
            hits = []
        local_ctx = [{"text": h.get("text", ""), "metadata": h.get("metadata", {}), "score": h.get("score", 0.0)} for h in hits]
    internal_poor = len(local_ctx) == 0

    # 3b) Web retrieval se ammesso/utile
    wants_price = any(k in ql for k in [
        "prezzo", "costo", "€/", "eur/", "listino", "quotazione",
        "cemento", "calcestruzzo", "cls", "acciaio", "bitume", "rame", "ferro",
    ])
    web_enabled = current_app.config.get("ENABLE_WEB_RETRIEVAL", False)
    should_use_web = (
        web_enabled and web_ret is not None and
        (pol.allow_web or mode in ("web", "both") or wants_price or internal_poor)
    )
    if should_use_web:
        focus = "price" if wants_price else None
        if "Meteo ammesso" in pol.reason:
            focus = "weather"
        web_focus = focus
        try:
            web_hits = web_ret.search(question, focus=focus)
        except Exception:
            web_hits = []
        web_ctx = [{"title": w.get("title"), "url": w.get("url"), "text": w.get("text", ""), "snippet": w.get("snippet", "")} for w in web_hits]

    # 3c) Estrazione prezzi dal web (se utile)
    if web_ctx and wants_price:
        all_prices = []
        for w in web_ctx:
            prices = extract_prices(w.get("text", ""))
            if prices:
                best = pick_best(prices, prefer_unit="kg") or pick_best(prices, prefer_unit="m3")
                if best:
                    all_prices.append({
                        "value": best["value"], "unit": best["unit"],
                        "title": w.get("title"), "url": w.get("url"),
                    })
        if all_prices:
            vals = sorted(p["value"] for p in all_prices)
            mid = len(vals) // 2
            med = vals[mid] if len(vals) % 2 == 1 else (vals[mid - 1] + vals[mid]) / 2
            unit_ = all_prices[0]["unit"]
            price_suggestion = {"suggested": round(med, 2), "unit": unit_}
            price_sources = [{"title": p["title"], "url": p["url"], "value": p["value"], "unit": p["unit"]} for p in all_prices]

    # 3d) Comparator generico
    generic_comparison = build_comparison(question, local_ctx, web_ctx)

    # 3e) Generazione risposta con il modello
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    session_id = session["session_id"]

    try:
        if hasattr(chat_model, "answer_with_contexts"):
            res = chat_model.answer_with_contexts(session_id, question, local_ctx, web_ctx)
            answer = res.get("answer", "")
            sources_internal = res.get("local_sources", [])
            sources_web = res.get("web_sources", [])
        else:
            response = chat_model.chat(vector_store, session_id, question)
            answer = response.get("answer", "")
            source_docs = response.get("source_documents", [])
            sources_internal = [{
                "title": d.get("metadata", {}).get("source", "Documento"),
                "snippet": (d.get("text", "")[:220] + "...") if d.get("text") else "",
            } for d in source_docs]
            sources_web = [{"title": w.get("title"), "url": w.get("url"), "snippet": w.get("snippet", "")} for w in web_ctx]
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not answer and not local_ctx and not web_ctx:
        return jsonify({
            "answer": "Non ho trovato evidenze nei documenti interni e la ricerca web non ha restituito risultati affidabili.",
            "sources_internal": [],
            "sources_web": [],
            "policy_reason": pol.reason,
        })

    payload = {
        "answer": answer,
        "sources_internal": sources_internal,
        "sources_web": sources_web,
        "policy_reason": pol.reason,
        "mode_requested": requested_mode,
        "mode_effective": mode,
        "web_focus": web_focus,
    }
    if price_suggestion:
        payload["price_suggestion"] = price_suggestion
        payload["price_sources"] = price_sources
    if generic_comparison:
        payload["comparison"] = generic_comparison

    return jsonify(payload)

# =============================================================================
# 5) RESET
# =============================================================================

@api_bp.route("/reset-chat", methods=["POST"])
def reset_chat():
    """Reset storico chat e memorie conversazionali."""
    chat_model = getattr(g, "chat_model", None)
    if chat_model is None:
        return jsonify({"error": "Server not initialized"}), 500
    if "session_id" in session:
        chat_model.clear_session(session["session_id"])
        session.pop("session_id", None)
    session.pop("staff_last", None)
    session.pop("material_last", None)
    return jsonify({"success": True})


@api_bp.route("/reset-db", methods=["POST"])
def reset_db():
    """Svuota il vector store (non tocca i dati in SQL)."""
    vector_store = getattr(g, "vector_store", None)
    if vector_store is None:
        return jsonify({"error": "Server not initialized"}), 500
    try:
        vector_store.delete_all()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500