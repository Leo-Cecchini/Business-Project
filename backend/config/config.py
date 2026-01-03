import os
from dotenv import load_dotenv
from pathlib import Path

# Carica le variabili da .env se presente
load_dotenv()

class Config:
    """Base configuration class."""
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
    TESTING = False
    
    # MongoDB
    MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
    MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
    MONGO_DB = os.getenv("MONGO_DB", "business_project")
    MONGO_URI = os.getenv("MONGO_URI", f"mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}")
    
    # API Keys
    GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
    GEOAPIFY_KEY = os.getenv('GEOAPIFY_KEY')  # Optional, per autocomplete indirizzi
    
    # Qdrant (vector store locale)
    QDRANT_PATH = os.getenv('QDRANT_PATH', './qdrant_data')
    QDRANT_COLLECTION = os.getenv('QDRANT_COLLECTION', 'documents')    
    
    # Embedding model
    EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')
    EMBEDDING_DIMENSION = int(os.getenv('EMBEDDING_DIMENSION', '768'))    
    
    # Upload settings
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
    MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64MB
    ALLOWED_EXTENSIONS = {'txt', 'pdf', 'md', 'csv'}
    
    # LLM settings
    CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', '1200'))
    CHUNK_OVERLAP = int(os.getenv('CHUNK_OVERLAP', '120'))
    SEARCH_LIMIT = int(os.getenv('SEARCH_LIMIT', '6'))
    MODEL_NAME = os.getenv('MODEL_NAME', 'gemini-2.5-flash')
    TEMPERATURE = float(os.getenv('TEMPERATURE', '0.1'))
    
    # Web retrieval settings
    #ENABLE_WEB_RETRIEVAL = os.getenv("ENABLE_WEB_RETRIEVAL", "false").lower() == "true"
    ENABLE_WEB_RETRIEVAL = True
    #WEB_TIMEOUT_SEC = int(os.getenv("WEB_TIMEOUT_SEC", "8"))
    WEB_TIMEOUT_SEC = 8
    
    # Bootstrap & Seeding
    BOOTSTRAP_DB = os.getenv("BOOTSTRAP_DB", "1") == "1"
    EXPORT_MISSING_SEED = os.getenv("EXPORT_MISSING_SEED", "0") == "1"
    AUTO_GENERATE_PRICELISTS = os.getenv("AUTO_GENERATE_PRICELISTS", "1") == "1"
    
    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")
    
    # Legacy (compatibility)
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data.db')
    
    # Paths
    BASE_DIR = Path(__file__).parent.parent
    DATA_DIR = BASE_DIR / "data"
    SEED_DIR = DATA_DIR / "db_seed"
    
    @staticmethod
    def validate():
        """Controlla che le variabili essenziali siano definite."""
        if not Config.GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY non trovata nelle variabili d'ambiente")
    
    @classmethod
    def init_app(cls, app):
        """Initialize app-specific settings."""
        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(cls.QDRANT_PATH, exist_ok=True)
        os.makedirs(cls.DATA_DIR, exist_ok=True)
        os.makedirs(cls.SEED_DIR, exist_ok=True)


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    
    @classmethod
    def init_app(cls, app):
        super().init_app(app)
        if not cls.GOOGLE_API_KEY:
            app.logger.warning("GOOGLE_API_KEY not set - AI features disabled")
        if cls.SECRET_KEY == "dev-secret-key-change-in-production":
            app.logger.error("SECRET_KEY not changed - SECURITY RISK!")


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    DEBUG = True
    MONGO_DB = "business_project_test"


def get_config(env=None):
    """Get configuration for specified environment."""
    if env is None:
        env = os.getenv('FLASK_ENV', 'development')
    
    configs = {
        'development': DevelopmentConfig,
        'production': ProductionConfig,
        'testing': TestingConfig,
    }
    
    return configs.get(env, DevelopmentConfig)