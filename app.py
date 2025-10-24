from flask import Flask
from config import Config
from models.vector_store import VectorStore
from models.chat_model import ChatModel
from utils.file_processor import FileProcessor
from routes.api import api_bp
from routes.views import views_bp
import os

def create_app(config_class=Config):
    """Application factory"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Validate configuration
    Config.validate()
    
    # Create upload folder
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize components
    app.config['VECTOR_STORE'] = VectorStore(
        path=app.config['QDRANT_PATH'],
        collection_name=app.config['QDRANT_COLLECTION'],
        api_key=app.config['GOOGLE_API_KEY']
    )
    
    app.config['CHAT_MODEL'] = ChatModel(
        api_key=app.config['GOOGLE_API_KEY'],
        model_name=app.config['MODEL_NAME'],
        temperature=app.config['TEMPERATURE']
    )
    
    app.config['FILE_PROCESSOR'] = FileProcessor(
        chunk_size=app.config['CHUNK_SIZE'],
        chunk_overlap=app.config['CHUNK_OVERLAP']
    )
    
    # Register blueprints
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    
    return app