# Chat and conversation management (robust version)

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

# ------------------------ Helper di formattazione ------------------------

def _clip(text: str, n: int) -> str:
    if not text:
        return ""
    t = text.strip()
    return t[:n]

def _pack_local_context(search_results: List[Dict], limit: int = 8, clip: int = 900) -> str:
    """Converte i risultati locali in blocchi leggibili e citabili."""
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
    """Converte i risultati web in blocchi leggibili e citabili."""
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
        if score is not None:
            lines.append(f"[LOCAL {i}] {src} (score={round(float(score), 3)})")
        else:
            lines.append(f"[LOCAL {i}] {src}")
    return "\n".join(lines)

def _list_web_refs(web_hits: List[Dict]) -> str:
    if not web_hits:
        return "(nessuna)"
    lines = []
    for i, r in enumerate(web_hits, 1):
        title = r.get("title") or r.get("url") or f"Fonte {i}"
        lines.append(f"[WEB {i}] {title}")
    return "\n".join(lines)


# =============================== ChatModel ===============================

class ChatModel:
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash", temperature: float = 0.1):
        # temperatura bassa per ridurre creatività/vaghezza
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=api_key,
            convert_system_message_to_human=True,
        )
        self.sessions: Dict[str, ChatMessageHistory] = {}

    # --- Session & history ----------------------------------------------------
    def get_or_create_history(self, session_id: str) -> ChatMessageHistory:
        if session_id not in self.sessions:
            self.sessions[session_id] = ChatMessageHistory()
        return self.sessions[session_id]

    def clear_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]

    # --- Modalità "classica" con solo vector store ---------------------------
    def chat(self, vector_store, session_id: str, question: str):
        """
        Chat con contesto dal vector store (solo LOCAL). Migliorata con schema di output.
        vector_store.search(question, limit=N) deve restituire elementi con chiavi:
        - "text"
        - "metadata": {"source": ...}
        - facoltativo: "score"
        """
        history = self.get_or_create_history(session_id)

        # Recupero documenti (aumentiamo il contesto a 8, poi ritagliamo noi)
        search_results = vector_store.search(question, limit=8)

        # Prepara contesto locale
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
            "history": history.messages,
            "question": question,
            "local_refs": local_refs,
            "local_blob": local_blob,
        })

        # Aggiorna cronologia
        history.add_user_message(question)
        history.add_ai_message(response)

        return {
            "answer": response,
            "source_documents": search_results
        }

    # --- Modalità avanzata: LOCAL + WEB + calc_json --------------------------
    def answer_with_contexts(
        self,
        session_id: str,
        question: str,
        local_ctx: list,
        web_ctx: list,
        calc_json: dict | None = None,
    ) -> dict:
        """
        Genera una risposta usando contesti separati (LOCAL vs WEB) e, opzionalmente,
        un blocco di calcolo strutturato (calc_json) che il modello deve spiegare/tabellare.
        """
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser
        import json as _json

        # --- Prepara contesti (liste e blob) ---------------------------------
        local_refs = _list_local_refs(local_ctx)
        web_refs = _list_web_refs(web_ctx)
        local_blob = _pack_local_context(local_ctx, limit=8, clip=900)
        web_blob = _pack_web_context(web_ctx, limit=6, clip=600)

        # Blocchetto con il calcolo strutturato (se presente)
        calc_section = ""
        if calc_json:
            calc_section = "CALCOLO STRUTTURATO (calc_json):\n" + _json.dumps(
                calc_json, ensure_ascii=False, indent=2
            )

        # --- Prompt di sistema migliorato ------------------------------------
        system = (
            "Separa rigorosamente le informazioni provenienti dai documenti interni (LOCAL) "
            "da quelle provenienti dal web (WEB). "
            "Quando citi, usa le sigle [LOCAL i] o [WEB j]. "
            "Se non ci sono evidenze sufficienti, dillo chiaramente. "
            "Per i prezzi, specifica sempre l'unità (kg/m2) e indica la fonte quando non proviene da calc_json.\n\n"
            "Se è presente un CALCOLO STRUTTURATO (calc_json), devi:\n"
            "- Riassumerlo chiaramente, SENZA modificarne i numeri.\n"
            "- Produrre due tabelle sintetiche: Materiali e Manodopera, con colonne: codice/ruolo, descrizione, qty, unità, prezzo unitario, totale.\n"
            "- Un 'Quadro economico' con subtotali (materiali, manodopera) e totale.\n"
            "- Eventuali 'Note' e 'Compliance notes' in elenco puntato.\n"
            "- Non inventare voci che non sono nel calc_json; se servono assunzioni, dichiarale a parte.\n"
            "- Usa esattamente questi titoli di sezione per la risposta: "
            "'Materiali', 'Manodopera', 'Quadro economico', 'Note', 'Compliance', 'Fonti interne', 'Fonti web'.\n"
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
             "- Se usi info da una fonte, cita [LOCAL i] o [WEB j].\n"
             "- Se c'è calc_json, i numeri principali DEVONO venire da lì.\n"
             "- Chiudi sempre con due elenchi: 'Fonti interne:' e 'Fonti web:' con titoli/URL."
            ),
            ("human", "{question}")
        ])

        chain = prompt | self.llm | StrOutputParser()

        # Storia conversazione
        history = self.get_or_create_history(session_id)

        answer = chain.invoke({
            "question": question,
            "local_refs": local_refs,
            "web_refs": web_refs,
            "local_blob": local_blob,
            "web_blob": web_blob,
            "calc_section": calc_section
        })

        # Aggiorna cronologia
        history.add_user_message(question)
        history.add_ai_message(answer)

        # Prepara citazioni strutturate per la UI
        local_sources = [
            {
                "title": (s.get("metadata") or {}).get("source", "Documento"),
                "snippet": (s.get("text") or (s.get("payload", {}) or {}).get("text", ""))[:220]
            }
            for s in (local_ctx or [])
        ]
        web_sources = [
            {
                "title": (s.get("title") or s.get("url")),
                "url": s.get("url"),
                "snippet": s.get("snippet", "")
            }
            for s in (web_ctx or [])
        ]

        return {
            "answer": answer,
            "local_sources": local_sources,
            "web_sources": web_sources,
            "used_calc_json": bool(calc_json),
        }