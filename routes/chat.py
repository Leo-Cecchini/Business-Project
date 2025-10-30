# routes/chat.py
from __future__ import annotations
import uuid
import logging
import os
from flask import Blueprint, request, jsonify, session, g, current_app
import unicodedata


log = logging.getLogger("chat")

# --- DB helpers per risposte deterministiche (MongoEngine) ---
import re
from models_mongo.worker import WorkerDoc
from models_mongo.material import MaterialDoc
from models_mongo.project import ProjectDoc
from mongoengine.queryset.visitor import Q

chat_bp = Blueprint("chat", __name__)

HEADCOUNT_RE = re.compile(
    r"\b(quant\w*|quas\w*|numero|totale|tot)\b.*\b(impiegat\w*|opera\w*|dipendent\w*|personale|staff|lavorator\w*)\b",
    re.IGNORECASE
)

def try_headcount(text: str):
    if not HEADCOUNT_RE.search(text or ""):
        return None
    tot = WorkerDoc.objects.count()
    disp = WorkerDoc.objects(available=True).count()
    return {"INTENT_DB":"HEADCOUNT", "answer": f"Totale personale: {tot} (disponibili: {disp})."}

def try_role_of_person(text: str):
    m = re.search(r"che\s+lavoro\s+fa\s+(.+?)\??$", (text or "").strip(), re.IGNORECASE)
    if not m: return None
    name = m.group(1).strip()
    w = WorkerDoc.objects(name__iexact=name).first() or WorkerDoc.objects(name__icontains=name).first()
    if not w:
        return {"INTENT_DB":"ROLE_LOOKUP", "answer": f"Non trovo {name} nel personale."}
    return {"INTENT_DB":"ROLE_LOOKUP", "answer": f"{w.name} è {w.role}."}

 # --- List workers by role intent (robusto, senza duplicati) ---
ROLE_LIST_RE = re.compile(
    r"\b(chi\s+sono|elenco|lista|quali)\b.*\b(murator\w*|elettricist\w*|idraulic\w*|carpent\w*|piastrell\w*|imbianch\w*|falegn\w*|manoval\w*|opera\w*|impieg\w*)\b",
    re.IGNORECASE
)

ROLE_ROOTS = {
    "murator": "muratori",
    "elettric": "elettricisti",
    "idraul": "idraulici",
    "carpent": "carpentieri",
    "piastrell": "piastrellisti",
    "imbianch": "imbianchini",
    "falegn": "falegnami",
    "manoval": "manovali",
    "opera": "operai",
    "impieg": "impiegati",
}

def try_list_by_role(text: str):
    m = ROLE_LIST_RE.search(text or "")
    if not m:
        return None
    word = m.group(2).lower()
    root = next((r for r in ROLE_ROOTS if r in word), None)
    if not root:
        return None
    qs = WorkerDoc.objects(role__icontains=root)
    names = sorted({w.name for w in qs.only("name").limit(200)})
    if not names:
        return {"INTENT_DB": "ROLE_LIST", "answer": f"Nessun {ROLE_ROOTS[root]} trovato."}
    label = ROLE_ROOTS[root]
    first = names[:20]
    return {"INTENT_DB": "ROLE_LIST", "answer": f"Ecco {len(first)} {label}: " + ", ".join(first)}


UNIT_MAP = {"mq":"m2","m²":"m2","mc":"m3","m³":"m3","l":"lt","litri":"lt","pezzi":"pz","pezzo":"pz","cart":"pz","bomb":"pz"}

# Gruppi di sinonimi per materiali (OR tra sinonimi dello stesso concetto)
MATERIAL_SYNONYM_GROUPS = [
    {"cemento", "cem", "portland"},
    {"calcestruzzo", "cls"},
    {"malta", "premiscelato", "m5"},
    {"intonaco", "civile"},
    {"calce", "idrata", "idratazione"},
    {"cartongesso", "gkb", "lastra"},
    {"rete", "elettrosaldata", "rete6", "rete 6"},
    {"acciaio", "barra", "tondino", "b450", "b450c", "b450d"},
    {"pittura", "lavabile", "smalto", "idropittura"},
    {"stucco", "fughe"},
    {"primer", "bituminoso", "poliuretanico"},
    {"guaina", "bituminosa", "ardesiata", "epdm"},
    {"eps", "polistirene", "isolante"},
    {"xps", "polistirene", "isolante"},
    {"lana", "roccia", "isolante"},
    {"nastro", "butilico"},
    {"additivo", "antigelo", "fluidificante"},
    {"sabbia"},
    {"ghiaia", "pietrisco"},
    {"piastrella", "gres"},
    {"colla", "c2te", "adesivo"},
    {"vite"},
    {"tassello"},
    {"taglierino"},
    {"tubo", "corrugato"},
    {"cavo", "fg16or"},
    {"scatola", "503"},
    {"placca"},
    {"interruttore"},
    {"presa", "schuko"},
    {"quadro", "elettrico"},
    {"magnetotermico"},
    {"differenziale", "rcd"},
    {"multistrato", "raccordo", "press"},
    {"valvola", "sfera"},
    {"rubinetto", "lavabo", "piletta"},
    {"frattazzo", "spugna"},
    {"mazzetta"},
    {"detergente", "cementizio"},
    {"scopa", "industriale"},
]

_SYNONYM_TO_ROOT = {}
for group in MATERIAL_SYNONYM_GROUPS:
    root = sorted(group, key=len)[0]
    for s in group:
        _SYNONYM_TO_ROOT[s] = root

def _normalize_material_tokens(text: str) -> list[list[str]]:
    """Converte il testo in gruppi di sinonimi. Ogni gruppo è una lista di varianti (OR)."""
    if not text:
        return []
    cleaned = re.sub(r"(?i)\b(prezzo|quanto|costa|al|allo|alla|per|unit(a|à)|sku[:\s]*[A-Z0-9\-]+)\b", " ", text)
    raw_tokens = re.findall(r"[A-Za-z]+|\d+(?:[.,]\d+)?[A-Za-z]?", cleaned.lower())
    raw_tokens = [t.strip().replace(",", ".") for t in raw_tokens if len(t.strip()) >= 2]

    groups: list[list[str]] = []
    seen = set()
    for tok in raw_tokens:
        variants = {tok}
        m = re.match(r"^(\d+(?:\.\d+)?)([a-z])$", tok)
        if m:
            variants.add(f"{m.group(1)} {m.group(2)}")
        root = _SYNONYM_TO_ROOT.get(tok)
        if root:
            syns = {v for v, r in _SYNONYM_TO_ROOT.items() if r == root}
            variants |= syns
        norm = sorted({" ".join(v.split()) for v in variants})
        key = tuple(norm)
        if key in seen:
            continue
        seen.add(key)
        groups.append(norm)
    return groups

def _material_answer(mdoc: MaterialDoc) -> dict:
    price = mdoc.unit_price_eur_2025 if mdoc.unit_price_eur_2025 is not None else 0.0
    return {
        "INTENT_DB": "MATERIAL_PRICE",
        "answer": (
            f"{mdoc.name}: {price:.2f} €/ {mdoc.unit} (SKU {mdoc.sku}). "
            f"Stock: {int(mdoc.stock_qty or 0)}, Lead time: {int(mdoc.lead_time_days or 0)} gg, IVA: {int(mdoc.vat_rate or 0)}%."
        ),
    }

def try_material_price(text: str):
    if not text:
        return None

    # 1) unità (sinonimi)
    unit = None
    for u in ["kg","m2","m3","pz","lt","m","mq","m²","mc","m³","l","litri","pezzi","pezzo","cart","bomb"]:
        if re.search(rf"\b{re.escape(u)}\b", text, re.IGNORECASE):
            unit = UNIT_MAP.get(u, u)
            break

    # 2) SKU realistico (es. CEM325R) — '32.5R' NON è SKU
    sku_match = re.search(r"\b([A-Z]{2,}[0-9]{2,}[A-Z0-9]*)\b", text.upper())
    if sku_match:
        mdoc = MaterialDoc.objects(sku=sku_match.group(1)).first()
        if mdoc:
            return _material_answer(mdoc)

    # 3) Token + sinonimi: AND tra concetti, OR dentro ciascun gruppo
    groups = _normalize_material_tokens(text)
    if not groups:
        return None

    q = None
    for variants in groups:
        q_or = None
        for v in variants:
            cond = Q(name__icontains=v)
            q_or = cond if q_or is None else (q_or | cond)
        q = q_or if q is None else (q & q_or)

    qs = MaterialDoc.objects
    if q is not None:
        qs = qs.filter(q)
    if unit:
        qs = qs.filter(unit=unit)

    mdoc = qs.order_by("name").first()
    if not mdoc and unit:
        # ultimo tentativo senza vincolo unità
        qs2 = MaterialDoc.objects
        if q is not None:
            qs2 = qs2.filter(q)
        mdoc = qs2.order_by("name").first()

    if not mdoc:
        return None
    return _material_answer(mdoc)

TRUTHY_TEXT = {"1", "true", "si", "sì", "yes", "y"}

def _is_truthy_available_filter():
    """Costruisce un filtro Mongo per interpretare 'available' come vero in vari formati."""
    return {
        "$or": [
            {"available": True},
            {"available": 1},
            {"available": "1"},
            {"available": "true"},
            {"available": "True"},
            {"available": "si"},
            {"available": "sì"},
            {"available": "yes"},
            {"available": "y"},
        ]
    }

def _workers_count(role_icontains: str | None = None) -> int:
    if not WorkerDoc:
        return 0
    q = WorkerDoc.objects
    if role_icontains:
        q = q.filter(role__icontains=role_icontains)
    return q.count()

def _workers_available_count(role_icontains: str | None = None) -> int:
    if not WorkerDoc:
        return 0
    raw = _is_truthy_available_filter()
    if role_icontains:
        q = WorkerDoc.objects(__raw__=raw).filter(role__icontains=role_icontains)
    else:
        q = WorkerDoc.objects(__raw__=raw)
    return q.count()

def _materials_exists_and_nonempty() -> tuple[bool, int]:
    if not MaterialDoc:
        return False, 0
    try:
        c = MaterialDoc.objects.count()
        return (c > 0), c
    except Exception:
        return False, 0

def _materials_best_match(name_like_norm: str):
    """Ritorna il materiale con match migliore su name/category/subcategory."""
    if not MaterialDoc:
        return None
    if not name_like_norm:
        return None
    # Primo tentativo: name contains
    rows = list(MaterialDoc.objects(name__icontains=name_like_norm).order_by("name"))
    if not rows:
        # Secondo tentativo: category/subcategory
        rows = list(MaterialDoc.objects(__raw__={
            "$or": [
                {"category": {"$regex": name_like_norm, "$options": "i"}},
                {"subcategory": {"$regex": name_like_norm, "$options": "i"}},
            ]
        }).order_by("category", "subcategory", "name"))
        if not rows:
            return None
    # Semplice scoring: esatto > startswith > contains
    nl = name_like_norm.lower()
    def _score(m):
        name_l = (getattr(m, "name", "") or "").lower()
        s = 0
        if name_l == nl: s += 10
        if name_l.startswith(nl): s += 5
        if nl in name_l: s += 2
        return s
    rows.sort(key=_score, reverse=True)
    return rows[0]

def _projects_counts() -> tuple[int, int]:
    if not ProjectDoc:
        return 0, 0
    try:
        tot = ProjectDoc.objects.count()
        att = ProjectDoc.objects(status__in=["Confermato", "In corso", "Attivo", "Active"]).count()
        return int(tot), int(att)
    except Exception:
        return 0, 0

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

# --- Headcount helper: intercetta richieste generiche totali (impiegati/staff/operai/dipendenti) ---
def _is_generic_headcount(q: str) -> bool:
    ql = (q or "").lower()
    return (
        any(t in ql for t in [
            "impiegat", "operai", "dipendenti", "personale", "staff", "lavoratori", "forza lavoro", "organico"
        ])
        and any(t in ql for t in ["quanti", "numero", "quanta", "quante", "totali", "totale"])
    )

# ------------------------ Route principale -----------------------------------
@chat_bp.post("/chat")
def chat_route():
    """Chat dell’assistente edile (Gemini 2.5) con RAG locale, web (opzionale) e calc_json."""
    data = request.get_json(force=True) or {}
    try:
        # ---- input -----------------------------------------------------------
        q = (data.get("message") or data.get("question") or "").strip()
        # ---- DB-first intents (minimal, deterministic) --------------------
        for _fn in (try_headcount, try_role_of_person, try_list_by_role, try_material_price):
            _res = _fn(q)
            if _res:
                return jsonify(_res), 200
        # -------------------------------------------------------------------
        if not q:
            return jsonify({"error": "Domanda vuota"}), 422

        # ----- Intent aziendali con risposta dal DB (prima del RAG) -----
        m = q.lower()

        # Quanti <ruolo> liberi/disponibili?
        if re.search(r"\b(liber[oi]|disponibil[ei])\b", m):
            # mappa ruoli comuni a radici per match robusto
            role_roots = [
                        "elettric", "murator", "idraul", "carpent", "piastrell",
                        "imbianch", "falegn", "manoval", "opera", "impieg"
            ]
            role_term = None
            for root in role_roots:
                if root in m:
                    role_term = root
                    break
            if role_term:
                cnt = _workers_available_count(role_term)
                log.warning("INTENT_DB → %s liberi: %s", role_term, int(cnt))
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
                    "impieg": "impiegati",
                }.get(role_term, f"{role_term} (liberi)")
                return jsonify({"answer": f"Ci sono {int(cnt)} {ruolo_label} disponibili."}), 200

        # Quanti cantieri?
        if re.search(r"\b(quanti|numero)\b.*\b(cantieri)\b", m):
            tot, att = _projects_counts()
            log.warning("INTENT_DB → cantieri (tot=%s, attivi=%s)", int(tot), int(att))
            return jsonify({"answer": f"Ci sono {int(tot)} cantieri in totale, {int(att)} attivi."}), 200
        # ----- /Intent DB ---------------------------------------------------

        project_id = data.get("project_id")
        where = None
        if project_id is not None:
            try:
                where = {"project_id": int(project_id)}
            except (TypeError, ValueError):
                where = None

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