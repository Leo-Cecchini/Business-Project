# Chat and conversation management

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from typing import Dict, List

class ChatModel:
    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash", temperature: float = 0.3):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=api_key,
            convert_system_message_to_human=True
        )
        self.sessions = {}
    
    def get_or_create_history(self, session_id: str) -> ChatMessageHistory:
        """Get or create message history for a session"""
        if session_id not in self.sessions:
            self.sessions[session_id] = ChatMessageHistory()
        return self.sessions[session_id]
    
    def clear_session(self, session_id: str):
        """Clear session history"""
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def chat(self, vector_store, session_id: str, question: str):
        """Chat with context from vector store"""
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.runnables import RunnablePassthrough
        
        # Get chat history
        history = self.get_or_create_history(session_id)
        
        # Search for relevant documents
        search_results = vector_store.search(question, limit=4)
        
        # Format context
        context = "\n\n".join([
            f"[Documento: {r['metadata']['source']}]\n{r['text']}"
            for r in search_results
        ])
        
        # Create prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Sei un assistente utile che risponde a domande basandoti sui documenti forniti.
            
Usa il seguente contesto per rispondere alla domanda. Se la risposta non è nel contesto, dillo chiaramente.

Contesto:
{context}"""),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{question}")
        ])
        
        # Create chain
        chain = prompt | self.llm | StrOutputParser()
        
        # Get response
        response = chain.invoke({
            "context": context,
            "history": history.messages,
            "question": question
        })
        
        # Save to history
        history.add_user_message(question)
        history.add_ai_message(response)
        
        return {
            "answer": response,
            "source_documents": search_results
        }

    def answer_with_contexts(self, session_id: str, question: str,
                             local_ctx: list, web_ctx: list) -> dict:
        """
        Genera una risposta usando contesti separati (LOCAL vs WEB) e restituisce citazioni separate.
        local_ctx: [{ "text": ..., "metadata": {...}, "score": ... }, ...]
        web_ctx:   [{ "title": ..., "url": ..., "text": ..., "snippet": ... }, ...]
        """
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        # Helpers di formattazione fonti
        def _fmt_local_refs(srcs):
            if not srcs:
                return "(nessuna)"
            lines = []
            for i, s in enumerate(srcs, 1):
                title = (s.get("metadata") or {}).get("source") or f"Documento {i}"
                score = s.get("score")
                if score is not None:
                    lines.append(f"[LOCAL {i}] {title} (score={round(score,3)})")
                else:
                    lines.append(f"[LOCAL {i}] {title}")
            return "\n".join(lines)

        def _fmt_web_refs(srcs):
            if not srcs:
                return "(nessuna)"
            lines = []
            for i, s in enumerate(srcs, 1):
                title = s.get("title") or s.get("url") or f"Fonte {i}"
                lines.append(f"[WEB {i}] {title}")
            return "\n".join(lines)

        def _pack_texts(items, key="text", limit=4, clip=900):
            if not items:
                return ""
            parts = []
            for it in items[:limit]:
                txt = it.get(key) or (it.get("payload", {}) or {}).get("text") or ""
                if txt:
                    parts.append(txt[:clip])
            return "\n---\n".join(parts)

        local_refs = _fmt_local_refs(local_ctx)
        web_refs   = _fmt_web_refs(web_ctx)
        local_blob = _pack_texts(local_ctx, key="text")
        web_blob   = _pack_texts(web_ctx, key="text")

        system = (
            "Separa rigorosamente le informazioni provenienti dai documenti interni (LOCAL) "
            "da quelle provenienti dal web (WEB). "
            "Quando citi, usa le sigle [LOCAL i] o [WEB j]. "
            "Se non ci sono evidenze sufficienti, dillo chiaramente. "
            "Per i prezzi, specifica sempre l'unità (kg/m3) e indica la fonte."
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             system + "\n\n"
             "Domanda: {question}\n\n"
             "FONTI INTERNE DISPONIBILI:\n{local_refs}\n\n"
             "ESTRATTI INTERNI:\n{local_blob}\n\n"
             "FONTI WEB DISPONIBILI:\n{web_refs}\n\n"
             "ESTRATTI WEB:\n{web_blob}\n\n"
             "Regole di output:\n"
             "- Risposta concisa e pratica per il contesto edile.\n"
             "- Se usi info da una fonte, cita [LOCAL i] o [WEB j].\n"
             "- Chiudi con due elenchi: 'Fonti interne:' e 'Fonti web:' con titoli/URL."
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
        })

        # Aggiorna history
        history.add_user_message(question)
        history.add_ai_message(answer)

        # Prepara citazioni strutturate per la UI
        local_sources = [
            {
                "title": (s.get("metadata") or {}).get("source", "Documento"),
                "snippet": (s.get("text") or (s.get("payload", {}) or {}).get("text",""))[:220]
            }
            for s in (local_ctx or [])
        ]
        web_sources = [
            {
                "title": (s.get("title") or s.get("url")),
                "url": s.get("url"),
                "snippet": s.get("snippet","")
            }
            for s in (web_ctx or [])
        ]

        return {
            "answer": answer,
            "local_sources": local_sources,
            "web_sources": web_sources
        }