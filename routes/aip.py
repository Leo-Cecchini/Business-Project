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
    
    if 'files' not in request.files:
        return jsonify({"error": "No files provided"}), 400
    
    files = request.files.getlist('files')
    
    if not files or files[0].filename == '':
        return jsonify({"error": "No files selected"}), 400
    
    vector_store = current_app.config['VECTOR_STORE']
    file_processor = current_app.config['FILE_PROCESSOR']
    
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
    from flask import current_app
    
    vector_store = current_app.config['VECTOR_STORE']
    documents = vector_store.get_all_documents()
    
    return jsonify({"documents": documents})

@api_bp.route('/chat', methods=['POST'])
def chat():
    """Chat endpoint"""
    from flask import current_app
    
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
        vector_store = current_app.config['VECTOR_STORE']
        chat_model = current_app.config['CHAT_MODEL']
        
        qa_chain = chat_model.create_qa_chain(vector_store, session_id)
        response = qa_chain({"question": question})
        
        answer = response["answer"]
        source_docs = response.get("source_documents", [])
        
        sources = [
            {
                "source": doc.metadata.get("source", "Unknown"),
                "text": doc.page_content[:200] + "..."
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
    from flask import current_app
    
    if 'session_id' in session:
        chat_model = current_app.config['CHAT_MODEL']
        chat_model.clear_session(session['session_id'])
        session.pop('session_id', None)
    
    return jsonify({"success": True})

@api_bp.route('/reset-db', methods=['POST'])
def reset_db():
    """Reset vector database"""
    from flask import current_app
    
    try:
        vector_store = current_app.config['VECTOR_STORE']
        vector_store.delete_all()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500