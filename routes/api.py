# routes/api.py
# API routes (compatibile con app.extensions / g.*)
from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Optional, Tuple

from flask import Blueprint, request, jsonify, session, current_app, g
from werkzeug.utils import secure_filename

# --- Estensioni / DB ---
from models import db

# --- Utils guardrail / web / comparator / prezzi ---
from utils.policy import decide_policy
from utils.price_extractor import extract_prices, pick_best
from utils.comparator import build_comparison

# --- Modelli DB ---
from sqlalchemy import or_, func
from models.worker import Worker
from models.material import Material

# --- LLM intent parser (staff) opzionale ---
from utils.intent_router import parse_intent_llm

# -----------------------------------------------------------------------------
# Blueprint
# -----------------------------------------------------------------------------
api_bp = Blueprint("api", __name__)

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
    """Costruisce la query dei dipendenti a partire dall’intent."""
    q = Worker.query
    if intent.get("role"):
        q = q.filter(Worker.role.ilike(f"%{intent['role']}%"))
    if intent.get("free_only"):
        thr = intent.get("free_hours_threshold", 20.0)
        q = (
            q.filter(or_(Worker.availability.is_(None), Worker.availability != "OFF"))
             .filter(or_(Worker.current_load.is_(None), Worker.current_load < thr))
        )
    q = q.order_by(Worker.role.asc(), Worker.name.asc())
    return q


def _remember_staff_ctx(intent: dict) -> None:
    """Memorizza l’ultimo intent staff nel contesto conversazionale."""
    session["staff_last"] = {
        "topic": "staff",
        "intent": {
            "operation": intent.get("operation", "list"),
            "role": intent.get("role"),
            "free_only": bool(intent.get("free_only", False)),
            "limit": int(intent.get("limit", 25)),
            "free_hours_threshold": float(intent.get("free_hours_threshold", 20.0)),
        },
    }


def _run_staff_intent(intent: dict) -> dict:
    """
    Esegue l’intent 'staff':
    - operation: "count" | "list" | "where" | "clarify" | "roles"
    """
    op = intent.get("operation", "list")
    role = intent.get("role") or None

    # Se manca il ruolo ma c’era nel turno precedente, riusalo
    if not role and session.get("staff_last") and session["staff_last"].get("intent", {}).get("role"):
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
        rows = q.limit(intent.get("limit", 25)).all()
        if not rows:
            free_part = " liberi" if intent.get("free_only") else ""
            answer = f"Non ho trovato {role_plural(role)}{free_part}."
            _remember_staff_ctx(intent)
            return {"handled": True, "answer": answer, "sources_internal": [], "sources_web": [],
                    "staff_intent": intent, "staff": []}

        items = [{
            "id": w.id,
            "name": w.name,
            "role": w.role,
            "home_city": w.home_city,
            "availability": w.availability,
            "current_load": w.current_load,
            "hourly_rate": w.hourly_rate,
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
            roles_counts = (
                db.session.query(Worker.role, func.count(Worker.id))
                .group_by(Worker.role)
                .order_by(Worker.role.asc())
                .all()
            )
            if not roles_counts:
                answer = "Non ci sono ruoli registrati nel database dei dipendenti."
            else:
                parts = [f"{(r or 'Senza ruolo').lower()}: {c}" for r, c in roles_counts]
                answer = "Ruoli presenti tra i dipendenti: " + ", ".join(parts) + "."
        except Exception as e:
            print(f"[staff roles error] {e}")
            answer = "Errore durante il recupero dei ruoli dal database."
        _remember_staff_ctx(intent)
        return {"handled": True, "answer": answer, "sources_internal": [], "sources_web": [],
                "staff_intent": intent}

    # LIST (default)
    rows = q.limit(intent.get("limit", 25)).all()
    if not rows:
        free_part = " liberi" if intent.get("free_only") else ""
        answer = f"Non ho trovato {role_plural(role)}{free_part}."
        _remember_staff_ctx(intent)
        return {"handled": True, "answer": answer, "sources_internal": [], "sources_web": [],
                "staff_intent": intent, "staff": []}

    items = [{
        "id": w.id,
        "name": w.name,
        "role": w.role,
        "home_city": w.home_city,
        "availability": w.availability,
        "current_load": w.current_load,
        "hourly_rate": w.hourly_rate,
    } for w in rows]

    names = ", ".join(i["name"] for i in items)
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
    """Heuristica per capire se la domanda riguarda prezzi materiali."""
    ql = q.lower()
    # Evita collisione con il ruolo "cartongessista/i"
    if "cartongessist" in ql:
        return False
    return any(t in ql for t in MATERIAL_PRICE_TRIGGERS)


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


def _lookup_material_in_db(name_like: str, unit: Optional[str]) -> Tuple[Optional[Material], int]:
    """Cerca il materiale nel DB e ritorna (best_match, numero_corrispondenze)."""
    if not name_like:
        return None, 0
    q = Material.query.filter(Material.name.ilike(f"%{name_like}%"))
    if unit:
        q = q.filter(Material.unit.ilike(unit))
    rows = q.order_by(Material.name.asc()).all()
    if not rows:
        return None, 0

    nl = name_like.lower()

    def _score(m: Material) -> int:
        s = 0
        if m.name.lower() == nl:
            s += 2
        if unit and (m.unit or "").lower() == (unit or "").lower():
            s += 1
        if m.name.lower().startswith(nl):
            s += 1
        return s

    rows.sort(key=_score, reverse=True)
    return rows[0], len(rows)


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
            "free_hours_threshold": 20.0,
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

            price = m.unit_price_eur_2025
            unit_label = m.unit or unit or ""
            if price is None:
                return jsonify({
                    "handled": True,
                    "answer": f"‘{m.name}’ è presente nel database ma non ha un prezzo impostato.",
                    "material": m.to_dict(),
                    "found": True,
                    "matches": matches,
                }), 200

            return jsonify({
                "handled": True,
                "answer": f"Il prezzo di {m.name} è {price:.2f} €/{unit_label}.",
                "material": m.to_dict(),
                "price": price,
                "unit": unit_label,
                "found": True,
                "matches": matches,
            }), 200
    except Exception as e:
        print(f"[API.chat][materials-routing] error: {e}")

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