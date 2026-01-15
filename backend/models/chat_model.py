# models/chat_model.py
from typing import Dict, List, Optional
import os
import logging
from functools import lru_cache
from datetime import datetime, timezone
import time

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_message_histories import MongoDBChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, ToolMessage
from pymongo import MongoClient

from models_mongo.material import MaterialDoc
from models_mongo.worker import WorkerDoc
from mongoengine.queryset.visitor import Q

SYSTEM_PROMPT = """Sei un assistente per imprenditori edili.
- Rispondi in italiano tecnico ma chiaro.
- Se la domanda è poco specifica, fai al massimo 3 domande mirate (chi, cosa, quanto, dove).
- Se ci sono numeri e la domanda richiede calcoli/stime, fornisci un risultato numerico e un dettaglio (lista o tabella) + una stima finale.
- Se usi fonti, separale sempre:
  - "Fonti interne:" (solo se hai davvero fonti LOCAL)
  - "Fonti web:" (solo se hai davvero fonti WEB)
  Se non hai fonti per una categoria, NON scrivere quella sezione.
- Non inventare prezzi: se non li hai, proponi fasce e metodo di calcolo.

Stile:
- Niente formato fisso numerato: rispondi in modo naturale, diretto e utile.
"""

# --- CLASSE CUSTOM PER EVITARE RESOURCE LEAK ---
class SharedMongoDBChatMessageHistory(MongoDBChatMessageHistory):
    """
    Versione ottimizzata che accetta un client MongoDB esistente
    invece di crearne uno nuovo ogni volta (che causava il blocco).
    """
    def __init__(self, client: MongoClient, session_id: str, database_name: str, collection_name: str):
        self.client = client
        self.session_id = session_id
        self.database_name = database_name
        self.collection_name = collection_name
        self.db = self.client[database_name]
        self.collection = self.db[collection_name]

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

def safe_invoke(llm_or_chain, payload):
    try:
        return llm_or_chain.invoke(payload)
    except Exception as e:
        return AIMessage(content=f"[ERRORE LLM] {type(e).__name__}: {str(e)[:180]}")

@lru_cache(maxsize=256)
def cached_db_hints(question: str) -> str:
    return _quick_db_hints(question, limit=6)

def _quick_db_hints(question: str, limit: int = 6) -> str:
    lines = []
    try:
        base = MaterialDoc.objects
        m = list(base.filter(aliases__icontains=question).only("name","sku","unit").limit(limit))
        if not m:
            m = list(base.filter(name__icontains=question).only("name","sku","unit").limit(limit))
        if not m:
            m = list(base.search_text(question).only("name","sku","unit").order_by("$text_score").limit(limit))
        if m:
            lines.append("Materiali suggeriti:")
            for x in m:
                lines.append(f"- {x.name} (SKU: {getattr(x,'sku',None)}, unit: {getattr(x,'unit',None)})")
    except Exception:
        pass

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
    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash-exp", temperature: float = 0.1):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=api_key,
            convert_system_message_to_human=True,
            request_timeout=40,
        )

        self.logger = logging.getLogger("ChatModel")
        if not self.logger.handlers:
            self.logger.setLevel(logging.INFO)
            
        self.mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.mongo_db = os.getenv("MONGODB_DB", "business_project")
        self.mongo_collection = os.getenv("CHAT_COLLECTION", "chat_sessions")

        # FIX: Inizializza UN SOLO client MongoDB condiviso
        self.shared_client = MongoClient(self.mongo_uri)

        self.tools = []
        try:
            from agents.worker_tools import create_worker_tool, remove_worker_tool
            self.tools = [create_worker_tool, remove_worker_tool]
            self.llm_with_tools = self.llm.bind_tools(self.tools)
        except Exception:
            self.llm_with_tools = self.llm

    def _scoped_session_id(self, base_session_id: str, site_id: Optional[str]) -> str:
        suffix = site_id if site_id else "GLOBAL-CHAT"
        return f"{base_session_id}::{suffix}"

    def get_or_create_history(self, session_id: str) -> MongoDBChatMessageHistory:
        return SharedMongoDBChatMessageHistory(
            client=self.shared_client,
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

    def _should_summarize(self, history: MongoDBChatMessageHistory) -> bool:
        try:
            msgs = getattr(history, "messages", [])
            return len(msgs) > 20
        except Exception:
            return False

    def _summarize(self, history: MongoDBChatMessageHistory):
        try:
            msgs = getattr(history, "messages", [])
            if len(msgs) <= 20:
                return
            
            history_text = "\n".join([f"{m.type}: {m.content[:200]}" for m in msgs])
            summary_prompt = f"Riassumi questa conversazione in 3-5 punti chiave:\n{history_text}"
            
            summary = safe_invoke(self.llm, [("human", summary_prompt)])
            summary_text = getattr(summary, "content", "Conversazione precedente")
            
            history.clear()
            history.add_ai_message(f"[RIASSUNTO CONVERSAZIONE]\n{summary_text}")
        except Exception as e:
            self.logger.warning(f"Summarize failed: {e}")

    def _execute_tool_calls(self, ai_msg: AIMessage) -> tuple:
        if not hasattr(ai_msg, "tool_calls") or not ai_msg.tool_calls:
            return [ai_msg], None
        
        messages = [ai_msg]
        for tc in ai_msg.tool_calls:
            if tc["name"] == "create_worker_tool":
                return messages, "Per favore conferma i dati del nuovo lavoratore prima di crearlo."
            elif tc["name"] == "remove_worker_tool":
                return messages, "Per favore conferma la rimozione del lavoratore."
        
        return messages, None

    def answer(self, session_id: str, question: str, search_results: list = None, site_id: str = None) -> dict:
        history = self.get_or_create_history(self._scoped_session_id(session_id, site_id))

        if self._should_summarize(history):
            self._summarize(history)

        search_results = search_results or []
        local_refs = _list_local_refs(search_results)
        local_blob = _pack_local_context(search_results, limit=8, clip=900)
        db_hints = cached_db_hints(question)

        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="history"),
            ("system",
             "Domanda: {question}\n\n"
             "FONTI INTERNE DISPONIBILI:\n{local_refs}\n\n"
             "ESTRATTI INTERNI:\n{local_blob}\n\n"
             "SUGGERIMENTI DB (non vincolanti):\n{db_hints}\n\n"
             "Regole aggiuntive:\n"
             "- Dai priorità alle informazioni dei documenti interni (LOCAL).\n"
             "- Se non trovi risposta nei documenti, puoi rispondere con conoscenza generale, indicando chiaramente che non proviene da LOCAL.\n"
             "- Se non trovi risposta nei documenti, dillo chiaramente e specifica quali dati mancano.\n"
             "- Quando citi, usa le sigle [LOCAL i]."
            ),
            ("human", "{question}")
        ])

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

        messages_flow, needs_confirm = self._execute_tool_calls(ai_msg if isinstance(ai_msg, AIMessage) else AIMessage(content=str(ai_msg)))
        if needs_confirm:
            history.add_user_message(question)
            history.add_ai_message(needs_confirm)
            return {"answer": needs_confirm, "source_documents": search_results}

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
                "timestamp": datetime.now(timezone.utc),
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

    def answer_with_contexts(self, session_id: str, question: str, local_ctx: list, web_ctx: list, calc_json: dict | None = None, site_id: str | None = None) -> dict:
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
             "- Mostra le sezioni \"Fonti interne:\" e/o \"Fonti web:\" SOLO se hai effettivamente fonti da elencare; se una categoria è vuota, non stamparla."
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
                "timestamp": datetime.now(timezone.utc),
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