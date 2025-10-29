# routes/chat.py
from __future__ import annotations
import uuid
import logging
import os
from flask import Blueprint, request, jsonify, session, g, current_app
import unicodedata

chat_bp = Blueprint("chat", __name__, url_prefix="/api")

log = logging.getLogger("chat")

# --- DB helpers per risposte deterministiche (numeri certi) ---
import re, sqlite3

def _db_path():
    # Prefer Flask config, then env var, then local fallback
    uri = (current_app.config.get("SQLALCHEMY_DATABASE_URI")
           or os.getenv("DATABASE_URL", "sqlite:///data.db"))
    if uri.startswith("sqlite:////"):
        path = uri.replace("sqlite:////", "/", 1)
    elif uri.startswith("sqlite:///"):
        path = uri.replace("sqlite:///", "", 1)
    elif uri.startswith("sqlite://"):
        path = uri.replace("sqlite://", "", 1)
    else:
        path = uri
    log.warning("[chat.py] DB path in use: %s", path)
    return path

def _q(sql, params=()):
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    with con:
        return con.execute(sql, params).fetchall()

def _table_exists(name: str) -> bool:
    try:
        return bool(_q("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)))
    except Exception:
        return False

# ----- import opzionali con fallback -----------------------------------------
try:
    from utils.numparse import quick_extract, parse_prices
except Exception:
    # fallback minimi
    def quick_extract(q: str):
        return {"qty": None, "unit": None, "thickness_mm": None, "dimensions": None}
    def parse_prices(text: str):
        return []

try:
    # calcolatori baseline (opzionali)
    from models.estimators import pick_and_estimate
except Exception:
    def pick_and_estimate(_entities):  # fallback: nessuna stima
        return None

# ------------------------ Helpers --------------------------------------------
def _normalize_intent(raw: str) -> str:
    r = (raw or "").strip().lower()
    if r in ("stima", "estimate", "preventivo"):
        return "STIMA"
    if r in ("staff", "personale"):
        return "STAFF"
    if r in ("documento", "document", "doc"):
        return "DOCUMENTO"
    return "none"

def _format_estimate_text(calc: dict | None) -> str:
    if not calc or not isinstance(calc, dict):
        return ""
    lines = [
        "\n\n[STIMA CALCOLATA]",
        "- Questa sezione contiene la stima strutturata calcolata (non modificarne i numeri).",
    ]
    budget = (calc.get("project") or {}).get("budget") or {}
    if budget:
        m = budget.get("materials"); l = budget.get("labor"); t = budget.get("total")
        lines.append(f"- Quadro economico: Materiali={m} €, Manodopera={l} €, Totale={t} €")
    for ch in (calc.get("chunks") or [])[:3]:
        scope = ch.get("scope", "voce")
        sm = ch.get("subtotal_materials"); sl = ch.get("subtotal_labor")
        lines.append(f"- {scope}: materiali={sm} €, manodopera={sl} €")
    return "\n".join(lines)

# --- Helpers normalizzazione testo per materiali ---
STOP_WORDS = {"dimmi","il","lo","la","i","gli","le","del","dello","della","dei","degli","delle","di","da","in","su","per","con","tra","fra","quanto","costa","prezzo","costo","fammi","vedere","mostra"}
def _normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    # rimuovi accenti
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    # sostituisci separatori/punteggiatura con spazio
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        elif ch in ".,/-_+":
            out.append(" ")
        else:
            out.append(" ")
    s = " ".join(" ".join(out).split())
    return s
def _like_from_tokens(text: str) -> str:
    tokens = [t for t in text.split() if t and t not in STOP_WORDS]
    if not tokens:
        return "%"
    return "%" + "%".join(tokens) + "%"

# ------------------------ Route principale -----------------------------------
@chat_bp.post("/chat")
def chat_route():
    """Chat dell’assistente edile (Gemini 2.5) con RAG locale, web (opzionale) e calc_json."""
    data = request.get_json(force=True) or {}
    try:
        # ---- input -----------------------------------------------------------
        q = (data.get("message") or data.get("question") or "").strip()
        if not q:
            return jsonify({"error": "Domanda vuota"}), 422

        # ----- Intent aziendali con risposta dal DB (prima del RAG) -----
        m = q.lower()

        # Quanti <ruolo> liberi/disponibili?
        if re.search(r"\b(liber[oi]|disponibil[ei])\b", m):
            # mappa ruoli comuni a radici per match robusto
            role_roots = [
                "elettric", "murator", "idraul", "carpent", "piastrell",
                "imbianch", "falegn", "manoval", "opera"
            ]
            role_term = None
            for root in role_roots:
                if root in m:
                    role_term = root
                    break
            if role_term:
                try:
                    sql = f"""
                    SELECT COUNT(*) AS c
                    FROM workers
                    WHERE (
                      CASE
                        WHEN typeof(available)='integer' THEN available
                        WHEN typeof(available)='real'    THEN CAST(available AS INTEGER)
                        WHEN typeof(available)='text'    THEN
                          CASE lower(trim(available))
                            WHEN '1' THEN 1
                            WHEN 'true' THEN 1
                            WHEN 'si' THEN 1
                            WHEN 'sì' THEN 1
                            WHEN 'yes' THEN 1
                            WHEN 'y' THEN 1
                            ELSE 0
                          END
                        ELSE 0
                      END
                    ) = 1
                    AND role IS NOT NULL AND lower(role) LIKE ?
                    ;
                    """
                    cnt = _q(sql, (f"%{role_term}%",))[0]["c"]
                except Exception:
                    cnt = 0
                log.warning("INTENT_DB → %s liberi: %s (db=%s)", role_term, int(cnt), _db_path())
                # formato risposta naturale
                ruolo_label = {
                    "elettric": "elettricisti",
                    "murator": "muratori",
                    "idraul": "idraulici",
                    "carpent": "carpentieri",
                    "piastrell": "piastrellisti",
                    "imbianch": "imbianchini",
                    "falegn": "falegnami",
                    "manoval": "manovali",
                    "opera": "operai",
                }.get(role_term, f"{role_term} (liberi)")
                return jsonify({"answer": f"Ci sono {int(cnt)} {ruolo_label} disponibili."}), 200

        # Prezzo di un materiale (es: "prezzo/costo del cemento ...")
        if re.search(r"\b(prezzo|costo|costa)\b", m):
            mat_norm = _normalize_text(m)
            like_pat = _like_from_tokens(mat_norm)
            # Check tabella materials presente e popolata
            try:
                if not _table_exists("materials"):
                    log.warning("INTENT_DB → materials table NOT FOUND (db=%s)", _db_path())
                    return jsonify({"answer": "Nel database in uso la tabella 'materials' non esiste. Assicurati di puntare al DB corretto e di aver importato i materiali."}), 200
                cnt_row = _q("SELECT COUNT(*) AS c FROM materials")
                if cnt_row and int(cnt_row[0]["c"]) == 0:
                    log.warning("INTENT_DB → materials table EMPTY (db=%s)", _db_path())
                    return jsonify({"answer": "Il database materiali è vuoto. Importa il CSV dei materiali e riprova."}), 200
            except Exception as _e:
                log.warning("INTENT_DB → materials precheck failed: %s", _e)
            try:
                row = _q(
                    """
                    SELECT name, unit, unit_price_eur_2025 AS price
                    FROM materials
                    WHERE lower(name) LIKE ?
                    ORDER BY CASE WHEN lower(name) = ? THEN 0 ELSE LENGTH(name) END, name
                    LIMIT 1
                    """,
                    (like_pat, mat_norm,)
                )
                if row:
                    r = row[0]
                    price = r.get("price")
                    unit = r.get("unit") or "unità"
                    name = r.get("name")
                    if price is not None:
                        return jsonify({"answer": f"{name}: {price:.2f} € / {unit}"}), 200
                    else:
                        return jsonify({"answer": f"Per {name} non è presente un prezzo."}), 200
            except Exception:
                pass
            # fallback: suggerimenti (top 5 simili)
            try:
                sugg = _q(
                    """
                    SELECT name FROM materials
                    WHERE lower(name) LIKE ?
                    ORDER BY LENGTH(name) ASC
                    LIMIT 5
                    """,
                    (like_pat,)
                )
                if sugg:
                    opts = ", ".join(r["name"] for r in sugg)
                    return jsonify({"answer": f"Non ho trovato una corrispondenza esatta. Potresti intendere: {opts}?"}), 200
            except Exception:
                pass
            return jsonify({"answer": "Nel database materiali non ho trovato una voce compatibile. Se hai appena importato, verifica che la voce esista e abbia un prezzo."}), 200

        # Quanti operai/dipendenti?
        # Nota: regex più permissiva per intercettare qualsiasi frase che citi "operai" o "dipendenti"
        if re.search(r"(operai|dipendenti)", m):
            try:
                tot = _q("SELECT COUNT(*) AS c FROM workers")[0]["c"]
            except Exception:
                tot = 0
            try:
                # Conteggio "liberi" robusto a prescindere dal tipo della colonna `available` (INTEGER/TEXT)
                free_sql = """
                SELECT COUNT(*) AS c
                FROM workers
                WHERE (
                  CASE
                    WHEN typeof(available)='integer' THEN available
                    WHEN typeof(available)='real'    THEN CAST(available AS INTEGER)
                    WHEN typeof(available)='text'    THEN
                      CASE lower(trim(available))
                        WHEN '1' THEN 1
                        WHEN 'true' THEN 1
                        WHEN 'si' THEN 1
                        WHEN 'sì' THEN 1
                        WHEN 'yes' THEN 1
                        WHEN 'y' THEN 1
                        ELSE 0
                      END
                    ELSE 0
                  END
                ) = 1;
                """
                lib = _q(free_sql)[0]["c"]
            except Exception:
                lib = 0
            log.warning("INTENT_DB → operai (tot=%s, liberi=%s) db=%s", int(tot), int(lib), _db_path())
            return jsonify({"answer": f"In totale ci sono {int(tot)} operai, di cui {int(lib)} liberi."}), 200

        # Quanti cantieri?
        if re.search(r"\b(quanti|numero)\b.*\b(cantieri)\b", m):
            try:
                if _table_exists("projects"):
                    tot = _q("SELECT COUNT(*) AS c FROM projects")[0]["c"]
                    # Consideriamo attivi 'Confermato' o 'In corso' (adatta se diverso)
                    att = _q("SELECT COUNT(*) AS c FROM projects WHERE status IN ('Confermato','In corso')")[0]["c"]
                else:
                    tot, att = 0, 0
            except Exception:
                tot, att = 0, 0
            log.warning("INTENT_DB → cantieri (tot=%s, attivi=%s) db=%s", int(tot), int(att), _db_path())
            return jsonify({"answer": f"Ci sono {int(tot)} cantieri in totale, {int(att)} attivi."}), 200
        # ----- /Intent DB ---------------------------------------------------

        project_id = data.get("project_id")
        where = {"project_id": int(project_id)} if project_id is not None else None

        # ---- deps da app.py --------------------------------------------------
        vector_store = getattr(g, "vector_store", None)
        chat_model   = getattr(g, "chat_model", None)
        web_retriever = getattr(g, "web_retriever", None)
        router = current_app.extensions.get("deps", {}).get("router")

        if not vector_store or not chat_model:
            return jsonify({"error": "Componenti non inizializzati (vector_store/chat_model)"}), 500

        # ---- session ---------------------------------------------------------
        sid = session.get("sid") or str(uuid.uuid4())
        session["sid"] = sid

        # ---- intent routing --------------------------------------------------
        intent_raw = "none"; entities = {}
        try:
            if router is not None:
                routed = router.route(q)
                intent_raw = routed.get("intent", "none")
                entities = routed.get("entities", {}) or {}
            else:
                low = q.lower()
                if any(k in low for k in ("confronta","analizza","estrai","capitolato","computo","pdf","allegato","excel","file")):
                    intent_raw = "documento"
                elif any(k in low for k in ("stima","preventivo","quanto costa","costo","budget","analisi prezzi")):
                    intent_raw = "stima"
                else:
                    intent_raw = "stima"
        except Exception as e:
            log.warning("Router intent fallito: %s", e, exc_info=True)
            intent_raw = "stima"
            entities = {}

        intent = _normalize_intent(intent_raw)

        # ---- estrazione numerica minima -------------------------------------
        try:
            ex = quick_extract(q)
        except Exception:
            ex = {"qty": None, "unit": None, "thickness_mm": None, "dimensions": None}

        if entities.get("qty") is None and ex.get("qty") is not None:
            entities["qty"] = ex["qty"]
        if not entities.get("unit") and ex.get("unit"):
            entities["unit"] = ex["unit"]
        if not entities.get("spessori_mm") and ex.get("thickness_mm"):
            entities["spessori_mm"] = ex["thickness_mm"]
        if not entities.get("dimensioni") and ex.get("dimensions"):
            entities["dimensioni"] = ex["dimensions"]

        # ---- RAG locale con filtro cantiere ---------------------------------
        try:
            local_ctx = vector_store.search(q, limit=12, where=where)
        except TypeError:
            # compat per vecchie firme senza 'where'
            local_ctx = vector_store.search(q, limit=12)

        # ---- price hints dai documenti --------------------------------------
        price_hints = []
        try:
            for i, chunk in enumerate(local_ctx[:6], start=1):
                txt = (chunk.get("text") or "")
                hits = parse_prices(txt)
                if not hits: 
                    continue
                src = (chunk.get("metadata") or {}).get("source", f"Documento {i}")
                for p in hits[:2]:
                    price_hints.append(f"- {src}: {p['value']} {p['unit']}")
        except Exception:
            price_hints = []

        # ---- web retrieval (opzionale) --------------------------------------
        web_ctx = []
        if bool(current_app.config.get("ENABLE_WEB_RETRIEVAL", False)) and web_retriever and intent in ("STIMA","DOCUMENTO"):
            try:
                web_ctx = web_retriever.search_and_fetch(q, max_results=5)
            except Exception as e:
                log.warning("Web retriever fallito: %s", e)

        # ---- stima automatica (DB → fallback baseline) ----------------------
        auto_estimate = None
        if intent == "STIMA" and entities.get("qty") and entities.get("unit"):
            try:
                from routes.estimate import estimate_from_entities as _by_db
                auto_estimate = _by_db(entities) or pick_and_estimate(entities)
            except Exception as e:
                log.info("estimate_from_entities non disponibile/errore: %s", e)
                try:
                    auto_estimate = pick_and_estimate(entities)
                except Exception:
                    auto_estimate = None

        # ---- domanda arricchita per il modello ------------------------------
        parts = []
        if entities.get("qty") and entities.get("unit"):
            parts.append(f"[PARAMETRI RICONOSCIUTI] qty={entities['qty']} {entities['unit']}")
        if entities.get("spessori_mm"):
            parts.append(f"spessore={entities['spessori_mm']} mm")
        if entities.get("dimensioni"):
            parts.append(f"formato={', '.join(map(str, entities['dimensioni']))}")
        if project_id is not None:
            parts.append(f"project_id={project_id}")
        meta_hint = ("\n\n" + "; ".join(parts)) if parts else ""

        hints_block = ("\n\n[DATI ESTRATTI DAI DOCUMENTI]\n" + "\n".join(price_hints)) if price_hints else ""
        estimate_block = _format_estimate_text(auto_estimate) if auto_estimate else ""
        augmented_question = q + meta_hint + hints_block + estimate_block

        # ---- chiamata al modello --------------------------------------------
        res = chat_model.answer_with_contexts(
            sid,
            augmented_question,
            local_ctx,
            web_ctx,
            calc_json=auto_estimate
        )

        # ---- payload UI ------------------------------------------------------
        res["intent"] = intent
        res["entities"] = entities
        res["price_hints"] = price_hints
        res["auto_estimate"] = auto_estimate

        # retro-compat: lista “sources” semplice
        local_sources = [
            {
                "source": (c.get("metadata") or {}).get("source", "Documento"),
                "text": (c.get("text") or (c.get("payload", {}) or {}).get("text", ""))[:300]
            }
            for c in (local_ctx or [])
        ]
        web_sources = [
            {
                "source": (c.get("title") or c.get("url") or "Fonte web"),
                "text": (c.get("text") or c.get("snippet") or "")[:300]
            }
            for c in (web_ctx or [])
        ]
        res["sources"] = local_sources + web_sources

        return jsonify(res), 200

    except Exception as e:
        log.exception("Errore /api/chat")
        return jsonify({"error": str(e)}), 500