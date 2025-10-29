# models/chat_model.py
from typing import Dict, List
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser

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


class ChatModel:
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash", temperature: float = 0.1):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=api_key,
            convert_system_message_to_human=True,
        )
        self.sessions: Dict[str, ChatMessageHistory] = {}

    def get_or_create_history(self, session_id: str) -> ChatMessageHistory:
        if session_id not in self.sessions:
            self.sessions[session_id] = ChatMessageHistory()
        return self.sessions[session_id]

    def clear_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]

    def chat(self, vector_store, session_id: str, question: str):
        history = self.get_or_create_history(session_id)

        try:
            search_results = vector_store.search(question, limit=8)
        except Exception:
            search_results = []

        local_refs = _list_local_refs(search_results)
        local_blob = _pack_local_context(search_results, limit=8, clip=900)

        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="history"),
            ("system",
             "Domanda: {question}\n\n"
             "FONTI INTERNE DISPONIBILI:\n{local_refs}\n\n"
             "ESTRATTI INTERNI:\n{local_blob}\n\n"
             "Regole aggiuntive:\n"
             "- Usa SOLO le informazioni dei documenti interni.\n"
             "- Se non trovi risposta nei documenti, dillo chiaramente e specifica quali dati mancano.\n"
             "- Quando citi, usa le sigle [LOCAL i]."
            ),
            ("human", "{question}")
        ])

        chain = prompt | self.llm | StrOutputParser()

        response = chain.invoke({
            "history": getattr(history, "messages", []),
            "question": question,
            "local_refs": local_refs,
            "local_blob": local_blob,
        })

        history.add_user_message(question)
        history.add_ai_message(response)

        return {
            "answer": response,
            "source_documents": search_results
        }

    def answer_with_contexts(self, session_id: str, question: str, local_ctx: list, web_ctx: list, calc_json: dict | None = None) -> dict:
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser
        import json as _json

        local_refs = _list_local_refs(local_ctx)
        web_refs = _list_web_refs(web_ctx)
        local_blob = _pack_local_context(local_ctx, limit=8, clip=900)
        web_blob = _pack_web_context(web_ctx, limit=6, clip=600)

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

        chain = prompt | self.llm | StrOutputParser()
        history = self.get_or_create_history(session_id)

        answer = chain.invoke({
            "question": question,
            "local_refs": local_refs,
            "web_refs": web_refs,
            "local_blob": local_blob,
            "web_blob": web_blob,
            "calc_section": calc_section
        })

        history.add_user_message(question)
        history.add_ai_message(answer)

        local_sources = [
            {"title": (s.get("metadata") or {}).get("source", "Documento"),
             "snippet": (s.get("text") or (s.get("payload", {}) or {}).get("text", ""))[:220]}
            for s in (local_ctx or [])
        ]
        web_sources = [
            {"title": (s.get("title") or s.get("url")), "url": s.get("url"), "snippet": s.get("snippet", "")}
            for s in (web_ctx or [])
        ]

        return {"answer": answer, "local_sources": local_sources, "web_sources": web_sources, "used_calc_json": bool(calc_json)}