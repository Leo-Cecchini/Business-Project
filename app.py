from flask import Flask
from config import Config
from models.vector_store import VectorStore
from models.chat_model import ChatModel
from utils.file_processor import FileProcessor
from routes.api import api_bp
from routes.views import views_bp
import os

# Global instances
vector_store = None
chat_model = None
file_processor = None

def init_components(app):
    """Initialize components"""
    global vector_store, chat_model, file_processor
    
    vector_store = VectorStore(
        path=app.config['QDRANT_PATH'],
        collection_name=app.config['QDRANT_COLLECTION'],
        embedding_model=app.config['EMBEDDING_MODEL'],
        embedding_dim=app.config['EMBEDDING_DIMENSION']
    )
    
    chat_model = ChatModel(
        api_key=app.config['GOOGLE_API_KEY'],
        model_name=app.config['MODEL_NAME'],
        temperature=app.config['TEMPERATURE']
    )
    
    file_processor = FileProcessor(
        chunk_size=app.config['CHUNK_SIZE'],
        chunk_overlap=app.config['CHUNK_OVERLAP']
    )

def create_app(config_class=Config):
    """Application factory"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Validate configuration
    Config.validate()
    
    # Create upload folder
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize components
    # Only skip if we're in reloader process AND debug is True
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        with app.app_context():
            init_components(app)
    
    # Register blueprints
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    
    return app