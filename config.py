import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
    
    # Qdrant settings
    QDRANT_PATH = os.getenv('QDRANT_PATH', './qdrant_data')  # Local folder for Qdrant
    QDRANT_COLLECTION = 'documents'
    
    # Embedding settings
    EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'all-mpnet-base-v2')
    EMBEDDING_DIMENSION = 768  # Dimension for all-mpnet-base-v2
    
    # Upload settings
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'md'}
    
    # LLM settings
    CHUNK_SIZE = 1500
    CHUNK_OVERLAP = 300
    SEARCH_LIMIT = 6
    MODEL_NAME = 'gemini-2.0-flash'
    TEMPERATURE = 0.3
    
    @staticmethod
    def validate():
        """Validate required configuration"""
        if not Config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables")