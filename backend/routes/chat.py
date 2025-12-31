# routes/chat.py
from flask import Blueprint, request, jsonify, session, g, current_app
import uuid
from services.chat_service import ChatService

chat_bp = Blueprint("chat", __name__, url_prefix="/api")

def get_chat_service():
    """Factory per inizializzare il servizio con le dipendenze request-scoped."""
    # Recupera i componenti globali inizializzati in app.py
    vs = getattr(g, "vector_store", None)
    cm = getattr(g, "chat_model", None)
    wr = getattr(g, "web_retriever", None)
    
    if not vs or not cm:
        # In sviluppo potrebbe capitare, gestiamo gracefully
        pass
        
    return ChatService(vector_store=vs, chat_model=cm, web_retriever=wr)

@chat_bp.post("/chat")
def chat_route():
    data = request.get_json(force=True) or {}
    message = data.get("message") or data.get("question")
    project_id = data.get("project_id") or data.get("site_id")
    # Compatibilità con la vecchia route
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
        response = service.process_message(
            question=message,
            session_id=session["sid"],
            project_id=project_id,
            user_context={"user": g.get("user")}
        )
        return jsonify(response), 200
        
    except Exception as e:
        current_app.logger.exception("Chat error")
        return jsonify({"error": str(e)}), 500

@chat_bp.post("/chat/project/<pid>")
def chat_project_route(pid):
    """Chat vincolata a un progetto."""
    data = request.get_json(force=True) or {}
    message = data.get("message") or data.get("question")
    
    if not message:
        return jsonify({"error": "Messaggio vuoto"}), 422
    
    try:
        service = get_chat_service()
        response = service.process_message(
            question=message,
            session_id=session.get("sid") or str(uuid.uuid4()),
            project_id=pid
        )
        return jsonify(response), 200
    except Exception as e:
        current_app.logger.exception("Chat Project error")
        return jsonify({"error": str(e)}), 500