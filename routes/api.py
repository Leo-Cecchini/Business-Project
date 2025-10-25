# API routes

from flask import Blueprint, request, jsonify, session
from werkzeug.utils import secure_filename
import os

api_bp = Blueprint('api', __name__)

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

@api_bp.route('/upload', methods=['POST'])
def upload_files():
    """Upload and process documents"""
    from flask import current_app
    from app import vector_store, file_processor
    
    if vector_store is None or file_processor is None:
        return jsonify({"error": "Server not initialized"}), 500
    
    if 'files' not in request.files:
        return jsonify({"error": "No files provided"}), 400
    
    files = request.files.getlist('files')
    
    if not files or files[0].filename == '':
        return jsonify({"error": "No files selected"}), 400
    
    processed = 0
    errors = []
    
    for file in files:
        if not allowed_file(file.filename, current_app.config['ALLOWED_EXTENSIONS']):
            errors.append(f"{file.filename}: Invalid file type")
            continue
        
        try:
            filename = secure_filename(file.filename)
            file_data = file.read()
            
            chunks, metadatas = file_processor.process_file(file_data, filename)
            vector_store.add_documents(chunks, metadatas)
            processed += 1
            
        except Exception as e:
            errors.append(f"{file.filename}: {str(e)}")
    
    return jsonify({
        "success": True,
        "processed": processed,
        "errors": errors
    })

@api_bp.route('/documents', methods=['GET'])
def get_documents():
    """Get list of uploaded documents"""
    from app import vector_store
    
    if vector_store is None:
        return jsonify({"error": "Server not initialized"}), 500
    
    documents = vector_store.get_all_documents()
    
    return jsonify({"documents": documents})

@api_bp.route('/chat', methods=['POST'])
def chat():
    """Chat endpoint"""
    from app import vector_store, chat_model
    
    if vector_store is None or chat_model is None:
        return jsonify({"error": "Server not initialized"}), 500
    
    data = request.json
    question = data.get('question', '').strip()
    
    if not question:
        return jsonify({"error": "Question is required"}), 400
    
    # Get or create session ID
    if 'session_id' not in session:
        import uuid
        session['session_id'] = str(uuid.uuid4())
    
    session_id = session['session_id']
    
    try:
        response = chat_model.chat(vector_store, session_id, question)
        
        answer = response["answer"]
        source_docs = response.get("source_documents", [])
        
        sources = [
            {
                "source": doc["metadata"].get("source", "Unknown"),
                "text": doc["text"][:200] + "..."
            }
            for doc in source_docs
        ]
        
        return jsonify({
            "answer": answer,
            "sources": sources
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api_bp.route('/reset-chat', methods=['POST'])
def reset_chat():
    """Reset chat history"""
    from app import chat_model
    
    if chat_model is None:
        return jsonify({"error": "Server not initialized"}), 500
    
    if 'session_id' in session:
        chat_model.clear_session(session['session_id'])
        session.pop('session_id', None)
    
    return jsonify({"success": True})

@api_bp.route('/reset-db', methods=['POST'])
def reset_db():
    """Reset vector database"""
    from app import vector_store
    
    if vector_store is None:
        return jsonify({"error": "Server not initialized"}), 500
    
    try:
        vector_store.delete_all()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500