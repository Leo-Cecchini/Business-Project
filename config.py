import os
from dotenv import load_dotenv

# Carica le variabili da .env se presente
load_dotenv()

class Config:
    # Chiave segreta Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # API Key Google
    GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
    
    # Qdrant (vector store locale)
    QDRANT_PATH = os.getenv('QDRANT_PATH', './qdrant_data')
    QDRANT_COLLECTION = 'documents'
    
    # Embedding model
    EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'all-mpnet-base-v2')
    EMBEDDING_DIMENSION = 768  # per all-mpnet-base-v2
    
    # Upload settings
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'md','csv'}
    
    # LLM settings
    CHUNK_SIZE = 1500
    CHUNK_OVERLAP = 300
    SEARCH_LIMIT = 6
    MODEL_NAME = os.getenv('MODEL_NAME', 'gemini-2.0-flash')
    TEMPERATURE = float(os.getenv('TEMPERATURE', '0.3'))
    
    # ✅ Web retrieval settings (corretto)
    ENABLE_WEB_RETRIEVAL = os.getenv("ENABLE_WEB_RETRIEVAL", "false").lower() == "true"
    WEB_TIMEOUT_SEC = int(os.getenv("WEB_TIMEOUT_SEC", "8"))

    # Database URL
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data.db')
    
    @staticmethod
    def validate():
        """Controlla che le variabili essenziali siano definite"""
        if not Config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY non trovata nelle variabili d'ambiente")