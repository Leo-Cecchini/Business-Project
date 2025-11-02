# models/chat_model.py
from typing import Dict, List, Optional
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_message_histories import MongoDBChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.messages import AIMessage, ToolMessage  # NEW
from models_mongo.material import MaterialDoc
from models_mongo.worker import WorkerDoc
from mongoengine.queryset.visitor import Q

# NEW: imports per logging, cache e gestione errori
import logging
from functools import lru_cache
from datetime import datetime
import time

SYSTEM_PROMPT = """Sei un assistente per imprenditori edili.
- Rispondi in italiano tecnico ma chiaro.
- Se la domanda è poco specifica, fai al massimo 3 domande mirate (chi, cosa, quanto, dove).
- Se ci sono numeri, dai SEMPRE un riepilogo tabellare e UNA stima finale.
- Se usi fonti (documenti interni o web), elencale alla fine in “Fonti:”.
- Se non sei sicuro, di' cosa manca e proponi come stimarlo. Evita frasi vaghe.
- Preferisci unità del settore (m, m², m³, kg, €/m², ore/uomo).
- NON inventare prezzi: se non li hai, proponi fasce e il metodo di calcolo.

Formatta SEMPRE così:
1) Risultato sintetico (1–3 frasi con numeri)
2) Dettaglio (lista puntata o tabellina)
3) Ipotesi e limiti (se applicabile)
4) Prossimi passi (se applicabile)
5) Fonti (bullet con titoli/URL o nomi file)
"""

def _clip(text: str, n: int) -> str:
    return (text or "").strip()[:n]

def _pack_local_context(search_results: List[Dict], limit: int = 8, clip: int = 900) -> str:
    if not search_results:
        return "—"
    parts = []
    for i, r in enumerate(search_results[:limit], 1):
        md = (r.get("metadata") or {})
        src = md.get("source") or f"Documento {i}"
        body = r.get("text") or (r.get("payload", {}) or {}).get("text", "")
        parts.append(f"[LOCAL {i}] {src}\n{_clip(body, clip)}")
    return "\n---\n".join(parts)

def _pack_web_context(web_hits: List[Dict], limit: int = 6, clip: int = 600) -> str:
    if not web_hits:
        return "—"
    parts = []
    for i, r in enumerate(web_hits[:limit], 1):
        title = r.get("title") or r.get("url") or f"Fonte {i}"
        url = r.get("url") or ""
        body = r.get("text") or r.get("snippet") or ""
        parts.append(f"[WEB {i}] {title} ({url})\n{_clip(body, clip)}")
    return "\n---\n".join(parts)

def _list_local_refs(search_results: List[Dict]) -> str:
    if not search_results:
        return "(nessuna)"
    lines = []
    for i, r in enumerate(search_results, 1):
        md = (r.get("metadata") or {})
        src = md.get("source") or f"Documento {i}"
        score = r.get("score")
        lines.append(f"[LOCAL {i}] {src}" + (f" (score={round(float(score),3)})" if score is not None else ""))
    return "\n".join(lines)


def _list_web_refs(web_hits: List[Dict]) -> str:
    if not web_hits:
        return "(nessuna)"
    return "\n".join([f"[WEB {i}] {r.get('title') or r.get('url') or f'Fonte {i}'}" for i, r in enumerate(web_hits, 1)])


# --- Safety & caching helpers (NEW) ---

def safe_invoke(llm_or_chain, payload):
    """
    Invoca il modello in modo sicuro: non alza eccezioni ma ritorna un AIMessage con errore.
    Accetta sia un LLM (self.llm / self.llm_with_tools) sia un chain/array di messaggi.
    """
    try:
        return llm_or_chain.invoke(payload)
    except Exception as e:
        # ritorna un AIMessage, così il flusso a valle non rompe
        return AIMessage(content=f"[ERRORE LLM] {type(e).__name__}: {str(e)[:180]}")

@lru_cache(maxsize=256)
def cached_db_hints(question: str) -> str:
    """Cache dei suggerimenti DB per ridurre round-trip su query ripetute."""
    return _quick_db_hints(question, limit=6)


# --- DB hints helper ---
def _quick_db_hints(question: str, limit: int = 6) -> str:
    """Ritorna un breve testo con top materiali/operai pertinenti per dare ancore al modello."""
    lines = []

    # materiali (aliases->name->text)
    try:
        base = MaterialDoc.objects
        m = list(base.filter(aliases__icontains=question).only("name","sku","unit","supplier").limit(limit))
        if not m:
            m = list(base.filter(name__icontains=question).only("name","sku","unit","supplier").limit(limit))
        if not m:
            m = list(base.search_text(question).only("name","sku","unit","supplier").order_by("$text_score").limit(limit))
        if m:
            lines.append("Materiali suggeriti:")
            for x in m:
                lines.append(f"- {x.name} (SKU: {getattr(x,'sku',None)}, unit: {getattr(x,'unit',None)}, supplier: {getattr(x,'supplier',None)})")
    except Exception:
        pass

    # operai (aliases->role/name->text)
    try:
        wq = WorkerDoc.objects
        w = list(wq.filter(aliases__icontains=question).only("name","role","available").limit(limit))
        if not w:
            w = list(wq.filter(Q(role__icontains=question)|Q(name__icontains=question)).only("name","role","available").limit(limit))
        if not w:
            w = list(wq.search_text(question).only("name","role","available").order_by("$text_score").limit(limit))
        if w:
            lines.append("Operai suggeriti:")
            for x in w:
                stato = "disponibile" if x.available else "occupato"
                lines.append(f"- {x.name} ({x.role}, {stato})")
    except Exception:
        pass

    return "\n".join(lines) if lines else ""


class ChatModel:
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash", temperature: float = 0.1):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=api_key,
            convert_system_message_to_human=True,
            request_timeout=40,   # NEW: timeout di rete
        )

        # NEW: logger base
        self.logger = logging.getLogger("ChatModel")
        if not self.logger.handlers:
            self.logger.setLevel(logging.INFO)
        # ✨ Memoria persistente su MongoDB
        self.mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.mongo_db = os.getenv("MONGODB_DB", "business_project")
        self.mongo_collection = os.getenv("CHAT_COLLECTION", "chat_sessions")

        # 🔧 Bind tools (se disponibili)
        self.tools = []
        try:
            # Richiede i file: agents/worker_tools.py, models/tools.py, services/workers_service.py
            from agents.worker_tools import create_worker_tool, remove_worker_tool
            self.tools = [create_worker_tool, remove_worker_tool]
            self.llm_with_tools = self.llm.bind_tools(self.tools)
        except Exception:
            # Fallback: nessun tool → il modello funziona comunque
            self.llm_with_tools = self.llm

    def _scoped_session_id(self, base_session_id: str, site_id: Optional[str]) -> str:
        """
        Namespacizza la sessione per cantiere:
        - site_id valorizzato  -> "<base>::<site_id>"
        - site_id assente      -> "<base>::GLOBAL-CHAT"
        Questo isola la memoria conversazionale tra cantieri e chat aziendale.
        """
        suffix = site_id if site_id else "GLOBAL-CHAT"
        return f"{base_session_id}::{suffix}"

    # ---------- Memoria persistente ----------
    def get_or_create_history(self, session_id: str) -> MongoDBChatMessageHistory:
        return MongoDBChatMessageHistory(
            connection_string=self.mongo_uri,
            database_name=self.mongo_db,
            collection_name=self.mongo_collection,
            session_id=session_id
        )

    def clear_session(self, session_id: str):
        history = self.get_or_create_history(session_id)
        try:
            history.clear()
        except Exception:
            pass

    # ---------- Rolling summary ----------
    def _should_summarize(self, history: MongoDBChatMessageHistory) -> bool:
        try:
            return len(getattr(history, "messages", [])) > 20
        except Exception:
            return False

    def _summarize(self, history: MongoDBChatMessageHistory):
        """Compatta la history in un memo strutturato preservando i fatti chiave."""
        try:
            msgs = list(getattr(history, "messages", []))[-40:]
            if not msgs:
                return
            lines = []
            for m in msgs:
                role = getattr(m, "type", None) or getattr(m, "role", None) or "user"
                content = getattr(m, "content", "") or ""
                lines.append(f"{role.upper()}: {content}")
            transcript = "\n".join(lines)

            prompt = (
                "Riassumi i punti e le decisioni chiave della chat per un contesto edile.\n"
                "- Restituisci 10–12 bullet concisi con valori e vincoli quando presenti.\n"
                "- Aggiungi sezioni: 'Vincoli', 'TODO'.\n"
                "- NON inventare; usa solo il transcript.\n\n"
                "Transcript:\n" + transcript
            )

            resp = self.llm.invoke(prompt)
            summary_text = getattr(resp, "content", resp)
            history.clear()
            history.add_ai_message(f"[MEMO] {summary_text}")
        except Exception:
            pass

    # ---------- Esecuzione tools & finalizzazione ----------
    def _execute_tool_calls(self, ai_msg: AIMessage):
        """Esegue eventuali tool-calls ritornando (messages_flow, pending_confirmation_msg | None)"""
        tool_calls = getattr(ai_msg, "tool_calls", []) or []
        messages_flow = [ai_msg]
        if not tool_calls:
            return messages_flow, None

        # Mappa nome -> tool
        tools_map = {t.name: t for t in self.tools} if self.tools else {}

        for tc in tool_calls:
            name = tc.get("name")
            args = tc.get("args", {}) or {}

            # Sicurezza: remove richiede conferma esplicita
            if name == "remove_worker" and not args.get("confirm"):
                confirm_text = (
                    f"Confermi l'eliminazione di worker_id={args.get('worker_id')}? "
                    "Rispondi testualmente: 'Confermo eliminazione' per procedere."
                )
                return [ai_msg], confirm_text

            tool_fn = tools_map.get(name)
            if not tool_fn:
                # Se il tool non è disponibile, ignora con messaggio
                messages_flow.append(ToolMessage(tool_call_id=tc.get("id", name), content=f"Tool '{name}' non disponibile"))
                continue

            # Esegue il tool lato server (LangChain Tool wrapper espone .invoke)
            result = tool_fn.invoke(args)
            messages_flow.append(ToolMessage(tool_call_id=tc.get("id", name), content=str(result)))

        return messages_flow, None

    # ---------- Chat con memoria persistente ----------
    def chat(self, vector_store, session_id: str, question: str, site_id: str | None = None):
        scoped_session = self._scoped_session_id(session_id, site_id)
        history = self.get_or_create_history(scoped_session)

        if self._should_summarize(history):
            self._summarize(history)

        try:
            where = {"project_id": {"$in": [site_id, "GLOBAL"]}} if site_id else None
            search_results = vector_store.search(question, limit=8, where=where)
        except Exception:
            search_results = []

        local_refs = _list_local_refs(search_results)
        local_blob = _pack_local_context(search_results, limit=8, clip=900)
        db_hints = cached_db_hints(question)  # usa la cache
        self.logger.info(f"[chat] sid={session_id} q={question[:80]}")
        if db_hints:
            self.logger.debug(f"[db_hints] {db_hints[:120]}")

        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="history"),
            ("system",
             "Domanda: {question}\n\n"
             "FONTI INTERNE DISPONIBILI:\n{local_refs}\n\n"
             "ESTRATTI INTERNI:\n{local_blob}\n\n"
             "SUGGERIMENTI DB (non vincolanti):\n{db_hints}\n\n"
             "Regole aggiuntive:\n"
             "- Usa SOLO le informazioni dei documenti interni.\n"
             "- Se non trovi risposta nei documenti, dillo chiaramente e specifica quali dati mancano.\n"
             "- Quando citi, usa le sigle [LOCAL i]."
            ),
            ("human", "{question}")
        ])

        # Usa il modello con tools (fallback automatico se non disponibili)
        chain = prompt | self.llm_with_tools
        _t0 = time.perf_counter()
        latency_ms = None
        ai_msg = safe_invoke(chain, {
            "history": getattr(history, "messages", []),
            "question": question,
            "local_refs": local_refs,
            "local_blob": local_blob,
            "db_hints": db_hints,
        })

        # Gestione tool-calls
        messages_flow, needs_confirm = self._execute_tool_calls(ai_msg if isinstance(ai_msg, AIMessage) else AIMessage(content=str(ai_msg)))
        if needs_confirm:
            history.add_user_message(question)
            history.add_ai_message(needs_confirm)
            return {"answer": needs_confirm, "source_documents": search_results}

        # Se abbiamo eseguito tools, chiedi al modello la risposta finale
        if len(messages_flow) > 1:
            final = safe_invoke(self.llm, messages_flow)
            response = getattr(final, "content", str(final))
        else:
            response = getattr(ai_msg, "content", str(ai_msg))

        if isinstance(response, str) and response.startswith("[ERRORE LLM]"):
            self.logger.warning(response)

        history.add_user_message(question)
        history.add_ai_message(response)
        try:
            latency_ms = int((time.perf_counter() - _t0) * 1000)
            db = WorkerDoc._get_db()
            db["chat_analytics"].insert_one({
                "session_id": session_id,
                "question": question,
                "answer": response[:500],
                "tokens_in": len(question.split()),
                "tokens_out": len(response.split()),
                "tools_used": [t.name for t in getattr(self, "tools", [])],
                "timestamp": datetime.utcnow(),
                "latency_ms": latency_ms,
                "site_id": site_id,
                "had_error": isinstance(response, str) and response.startswith("[ERRORE LLM]"),
            })
        except Exception:
            pass

        return {
            "answer": response,
            "source_documents": search_results,
            "meta": {
                "session_id": session_id,
                "site_id": site_id,
                "latency_ms": latency_ms
            }
        }

    # ---------- Chat con contesti multipli ----------
    def answer_with_contexts(self, session_id: str, question: str, local_ctx: list, web_ctx: list, calc_json: dict | None = None, site_id: str | None = None) -> dict:
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser
        import json as _json

        history = self.get_or_create_history(self._scoped_session_id(session_id, site_id))

        if self._should_summarize(history):
            self._summarize(history)

        local_refs = _list_local_refs(local_ctx)
        web_refs = _list_web_refs(web_ctx)
        local_blob = _pack_local_context(local_ctx, limit=8, clip=900)
        web_blob = _pack_web_context(web_ctx, limit=6, clip=600)

        self.logger.info(f"[ctx] sid={session_id} q={question[:80]} local={len(local_ctx)} web={len(web_ctx)}")

        calc_section = ""
        if calc_json:
            calc_section = "CALCOLO STRUTTURATO (calc_json):\n" + _json.dumps(calc_json, ensure_ascii=False, indent=2)

        system = (
            "Separa rigorosamente le informazioni provenienti dai documenti interni (LOCAL) "
            "da quelle provenienti dal web (WEB). "
            "Quando citi, usa le sigle [LOCAL i] o [WEB j]. "
            "Se non ci sono evidenze sufficienti, dillo chiaramente. "
            "Per i prezzi, specifica sempre l'unità e indica la fonte quando non proviene da calc_json.\n\n"
            "Se è presente un CALCOLO STRUTTURATO (calc_json), devi:\n"
            "- Riassumerlo senza modificare i numeri.\n"
            "- Produrre tabelle per Materiali e Manodopera (codice/ruolo, descrizione, qty, unità, €/unit, totale).\n"
            "- Un Quadro economico (materiali, manodopera, totale).\n"
            "- Note e Compliance.\n"
            "- Non inventare voci fuori da calc_json; eventuali assunzioni le separi.\n"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             system + "\n\n"
             "Domanda: {question}\n\n"
             "FONTI INTERNE DISPONIBILI:\n{local_refs}\n\n"
             "ESTRATTI INTERNI:\n{local_blob}\n\n"
             "FONTI WEB DISPONIBILI:\n{web_refs}\n\n"
             "ESTRATTI WEB:\n{web_blob}\n\n"
             "{calc_section}\n\n"
             "Regole di output:\n"
             "- Risposta concisa e pratica per il contesto edile.\n"
             "- Cita [LOCAL i] o [WEB j] quando usi una fonte.\n"
             "- Se c'è calc_json, i numeri chiave vengono da lì.\n"
             "- Chiudi con due elenchi: 'Fonti interne:' e 'Fonti web:'."
            ),
            ("human", "{question}")
        ])

        chain = prompt | self.llm_with_tools
        _t0 = time.perf_counter()
        latency_ms = None
        ai_msg = safe_invoke(chain, {
            "question": question,
            "local_refs": local_refs,
            "web_refs": web_refs,
            "local_blob": local_blob,
            "web_blob": web_blob,
            "calc_section": calc_section
        })

        messages_flow, needs_confirm = self._execute_tool_calls(ai_msg if isinstance(ai_msg, AIMessage) else AIMessage(content=str(ai_msg)))
        if needs_confirm:
            history.add_user_message(question)
            history.add_ai_message(needs_confirm)
            return {"answer": needs_confirm, "local_sources": [], "web_sources": [], "used_calc_json": bool(calc_json)}

        if len(messages_flow) > 1:
            final = safe_invoke(self.llm, messages_flow)
            answer = getattr(final, "content", str(final))
        else:
            answer = getattr(ai_msg, "content", str(ai_msg))

        history.add_user_message(question)
        history.add_ai_message(answer)
        try:
            latency_ms = int((time.perf_counter() - _t0) * 1000)
            db = WorkerDoc._get_db()
            db["chat_analytics"].insert_one({
                "session_id": session_id,
                "site_id": site_id,
                "question": question,
                "answer": answer[:500],
                "tokens_in": len(question.split()),
                "tokens_out": len(answer.split()),
                "tools_used": [t.name for t in getattr(self, "tools", [])],
                "timestamp": datetime.utcnow(),
                "latency_ms": latency_ms,
                "had_error": isinstance(answer, str) and answer.startswith("[ERRORE LLM]"),
            })
        except Exception:
            pass

        local_sources = [
            {"title": (s.get("metadata") or {}).get("source", "Documento"),
             "snippet": (s.get("text") or (s.get("payload", {}) or {}).get("text", ""))[:220]}
            for s in (local_ctx or [])
        ]
        web_sources = [
            {"title": (s.get("title") or s.get("url")), "url": s.get("url"), "snippet": s.get("snippet", "")}
            for s in (web_ctx or [])
        ]

        return {
            "answer": answer,
            "local_sources": local_sources,
            "web_sources": web_sources,
            "used_calc_json": bool(calc_json),
            "meta": {
                "session_id": session_id,
                "site_id": site_id,
                "latency_ms": latency_ms
            }
        }