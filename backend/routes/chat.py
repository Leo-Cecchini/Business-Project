# routes/chat.py
import os
import uuid
import logging
from flask import Blueprint, request, jsonify, session, g, current_app

from services.chat_service import ChatService

log = logging.getLogger("chat")
chat_bp = Blueprint("chat", __name__, url_prefix="/api")

def get_chat_service():
    """Factory per inizializzare il servizio con le dipendenze request-scoped."""
    vs = getattr(g, "vector_store", None)
    cm = getattr(g, "chat_model", None)
    wr = getattr(g, "web_retriever", None)
    rt = getattr(g, "router", None)
    
    # Fallback mode: crea istanze basic se mancanti
    if not cm:
        log.warning("chat_model missing, creating fallback instance")
        try:
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY")
            if api_key:
                from models.chat_model import ChatModel
                cm = ChatModel(
                    api_key=api_key,
                    model_name=os.getenv("MODEL_NAME", "gemini-2.0-flash-exp"),
                    temperature=0.1
                )
                g.chat_model = cm
            else:
                log.error("No API key found (GOOGLE_API_KEY or OPENAI_API_KEY)")
                return None
        except Exception as e:
            log.error(f"Failed to create fallback chat_model: {e}")
            return None
    
    if not vs:
        log.warning("vector_store missing, creating fallback instance")
        try:
            from models.vector_store import VectorStore
            vs = VectorStore(
                path=os.getenv("QDRANT_PATH", "./qdrant_data"),
                collection_name=os.getenv("QDRANT_COLLECTION", "documents"),
                embedding_model=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
                embedding_dim=int(os.getenv("EMBEDDING_DIMENSION", "384"))
            )
            g.vector_store = vs
        except Exception as e:
            log.warning(f"Failed to create fallback vector_store: {e}")
    
    if not wr:
        try:
            from utils.web_retriever import WebRetriever
            wr = WebRetriever(max_results=5, timeout=8)
            g.web_retriever = wr
            current_app.logger.info("✅ WebRetriever creato in fallback route")
        except Exception as e:
            current_app.logger.warning(f"WebRetriever fallback failed: {e}")
    
    if not rt:
        try:
            from utils.intent_router import IntentRouter
            rt = IntentRouter()
            g.router = rt
        except Exception as e:
            log.warning(f"Failed to create router: {e}")
    
    return ChatService(vector_store=vs, chat_model=cm, web_retriever=wr, router=rt)


@chat_bp.post("/chat")
def chat_route():
    """Main chat endpoint."""
    data = request.get_json(force=True) or {}
    message = data.get("message") or data.get("question")
    project_id = data.get("project_id") or data.get("site_id")
    
    # Compatibilità con enforced_pid
    enforced_pid = data.get("__enforced_pid")
    if enforced_pid:
        project_id = enforced_pid
    
    if not message:
        return jsonify({"error": "Messaggio vuoto"}), 422

    # Gestione Sessione
    if not session.get("sid"):
        session["sid"] = str(uuid.uuid4())
    
    try:
        service = get_chat_service()
        
        if not service:
            return jsonify({"error": "Chat service not available. Please configure AI dependencies."}), 503
        
        response = service.process_message(
            question=message,
            session_id=session["sid"],
            project_id=project_id,
            user_context={"user": g.get("user")}
        )
        return jsonify(response), 200
        
    except Exception as e:
        log.exception("Chat error")
        return jsonify({"error": str(e)}), 500

@chat_bp.post("/chat/project/<pid>")
def chat_project_route(pid):
    """Chat vincolata a un progetto."""
    data = request.get_json(force=True) or {}
    message = data.get("message") or data.get("question")
    
    if not message:
        return jsonify({"error": "Messaggio vuoto"}), 422
    
    # Gestione Sessione
    if not session.get("sid"):
        session["sid"] = str(uuid.uuid4())
    
    try:
        service = get_chat_service()
        if not service:
            return jsonify({"error": "Chat service not available. Please configure AI dependencies."}), 503
        
        response = service.process_message(
            question=message,
            session_id=session["sid"],
            project_id=pid,
            user_context={"user": g.get("user")}
        )
        return jsonify(response), 200
    except Exception as e:
        log.exception("Chat Project error")
        return jsonify({"error": str(e)}), 500