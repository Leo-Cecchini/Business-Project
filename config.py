import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    #SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
    
    # Qdrant settings
    QDRANT_PATH = os.getenv('QDRANT_PATH', './qdrant_data')  # Local folder for Qdrant
    QDRANT_COLLECTION = 'documents'
    
    # Upload settings
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'md'}
    
    # LLM settings
    CHUNK_SIZE = 1000
    CHUNK_OVERLAP = 200
    SEARCH_LIMIT = 4
    MODEL_NAME = 'gemini-2.5-flash'
    TEMPERATURE = 0.3
    
    @staticmethod
    def validate():
        """Validate required configuration"""
        if not Config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY not found in environment variables")
