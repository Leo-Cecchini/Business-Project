# routes/chat.py
from flask import Blueprint, request, jsonify, session, g, current_app
import uuid

from utils.numparse import quick_extract, parse_prices
from models.estimators import pick_and_estimate  # calcolatori baseline se DB non applicabile

chat_bp = Blueprint("chat", __name__)

def _normalize_intent(raw: str) -> str:
    """Mappa varianti su etichette stabili per la UI."""
    r = (raw or "").strip().lower()
    if r in ("stima", "estimate", "preventivo"):
        return "STIMA"
    if r in ("staff", "personale"):
        return "STAFF"
    if r in ("documento", "document", "doc"):
        return "DOCUMENTO"
    return "none"

def _format_estimate_text(calc: dict | None) -> str:
    """
    Converte una stima strutturata (calc_json) in un blocco testuale sintetico
    da passare al prompt come contesto aggiuntivo.
    """
    if not calc or not isinstance(calc, dict):
        return ""

    lines = ["\n\n[STIMA CALCOLATA]",
             "- Questa sezione contiene la stima strutturata calcolata (non modificarne i numeri)."]

    # Quadro economico
    budget = (calc.get("project") or {}).get("budget") or {}
    if budget:
        m = budget.get("materials")
        l = budget.get("labor")
        t = budget.get("total")
        lines.append(f"- Quadro economico: Materiali={m} €, Manodopera={l} €, Totale={t} €")

    # Chunks (prime 2-3 righe)
    chunks = calc.get("chunks") or []
    for ch in chunks[:3]:
        scope = ch.get("scope", "voce")
        sm = ch.get("subtotal_materials")
        sl = ch.get("subtotal_labor")
        lines.append(f"- {scope}: materiali={sm} €, manodopera={sl} €")

    return "\n".join(lines)

@chat_bp.route("/api/chat", methods=["POST"])
def chat_route():
    """Gestisce la chat principale dell’assistente edile usando i componenti creati in app.py."""
    try:
        data = request.get_json(force=True) or {}
        q = (data.get("message") or "").strip()
        if not q:
            return jsonify({"error": "Domanda vuota"}), 422

        # Sessione conversazione
        sid = session.get("sid") or str(uuid.uuid4())
        session["sid"] = sid

        # Dipendenze inizializzate in app.py -> _init_components()
        vector_store = getattr(g, "vector_store", None)
        chat_model   = getattr(g, "chat_model", None)
        web_retriever = getattr(g, "web_retriever", None)
        router = current_app.extensions.get("deps", {}).get("router")  # se lo aggiungi in app.py

        if not vector_store or not chat_model:
            return jsonify({"error": "Componenti non inizializzati (vector_store/chat_model)"}), 500

        # 1) Intent routing
        intent_raw = "none"
        entities = {}

        if router is not None:
            routed = router.route(q)
            intent_raw = routed.get("intent", "none")
            entities = routed.get("entities", {}) or {}
        else:
            # Fallback minimale
            low = q.lower()
            if any(k in low for k in ("confronta", "analizza", "estrai", "capitolato", "computo", "pdf", "allegato", "excel", "file")):
                intent_raw = "documento"
            elif any(k in low for k in ("stima", "preventivo", "quanto costa", "costo", "budget", "analisi prezzi")):
                intent_raw = "stima"
            else:
                intent_raw = "stima"
        intent = _normalize_intent(intent_raw)

        # 2) Fallback numerico: completa qty/unit/spessori/formati se mancano
        ex = quick_extract(q)
        if entities.get("qty") is None and ex["qty"] is not None:
            entities["qty"] = ex["qty"]
        if not entities.get("unit") and ex["unit"]:
            entities["unit"] = ex["unit"]
        if not entities.get("spessori_mm") and ex["thickness_mm"]:
            entities["spessori_mm"] = ex["thickness_mm"]
        if not entities.get("dimensioni") and ex["dimensions"]:
            entities["dimensioni"] = ex["dimensions"]

        # 3) Recupero documenti locali (RAG con rerank)
        local_ctx = vector_store.search(q, limit=12)

        # 3.1) Estrai “price hints” dai chunk locali (ancora numeri reali)
        price_hints = []
        for i, chunk in enumerate(local_ctx[:6], start=1):
            txt = (chunk.get("text") or "")
            hits = parse_prices(txt)
            if not hits:
                continue
            src = (chunk.get("metadata") or {}).get("source", f"Documento {i}")
            for p in hits[:2]:  # max 2 per sorgente
                price_hints.append(f"- {src}: {p['value']} {p['unit']}")
        hints_block = ("\n\n[DATI ESTRATTI DAI DOCUMENTI]\n" + "\n".join(price_hints)) if price_hints else ""

        # 4) Recupero web opzionale (segue config dell'app)
        enable_web = bool(current_app.config.get("ENABLE_WEB_RETRIEVAL", False))
        web_ctx = []
        if enable_web and intent in ("STIMA", "DOCUMENTO") and web_retriever:
            web_ctx = web_retriever.search_and_fetch(q, max_results=5)

        # 5) Parametri riconosciuti → aiutano il LLM ad essere più preciso
        entities_hint = []
        if entities.get("qty") is not None and entities.get("unit"):
            entities_hint.append(f"qty={entities['qty']} {entities['unit']}")
        if entities.get("spessori_mm"):
            entities_hint.append(f"spessore={entities['spessori_mm']} mm")
        if entities.get("dimensioni"):
            entities_hint.append(f"formato={', '.join(map(str, entities['dimensioni']))}")
        if entities.get("luogo"):
            entities_hint.append(f"luogo={entities['luogo']}")
        meta_hint = ("\n\n[PARAMETRI RICONOSCIUTI] " + "; ".join(entities_hint)) if entities_hint else ""

        # 5.bis) STIMA AUTOMATICA (prima DB-based, poi fallback baseline)
        auto_estimate = None
        try:
            if intent == "STIMA" and entities.get("qty") and entities.get("unit"):
                # 1) Prova con i prezzi reali da DB (routes/estimate.py)
                from routes.estimate import estimate_from_entities as _db_estimate_from_entities
                auto_estimate = _db_estimate_from_entities(entities)

                # 2) Se non applicabile, usa il fallback baseline (models/estimators.py)
                if not auto_estimate:
                    auto_estimate = pick_and_estimate(entities)
        except Exception:
            auto_estimate = None

        # 6) Generazione risposta finale con domanda arricchita
        estimate_block = _format_estimate_text(auto_estimate) if auto_estimate else ""
        augmented_question = q + meta_hint + hints_block + estimate_block

        res = chat_model.answer_with_contexts(
            sid,
            augmented_question,
            local_ctx,
            web_ctx,
            calc_json=auto_estimate  # passa la stima strutturata (se presente)
        )

        # 7) Metadati per la UI
        res["intent"] = intent
        res["entities"] = entities
        res["price_hints"] = price_hints
        res["auto_estimate"] = auto_estimate

        return jsonify(res), 200

    except Exception as e:
        # Errori sempre in JSON
        return jsonify({"error": str(e)}), 500