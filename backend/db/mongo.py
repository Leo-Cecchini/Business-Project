# db/mongo.py
import os
from mongoengine import connect

def init_mongo():
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    dbname = os.getenv("MONGODB_DB", "business_project")
    connect(db=dbname, host=uri, uuidRepresentation="standard")

def ensure_mongo_indexes():
    """
    Ensure MongoDB indexes are created.
    
    Note: With ObjectId migration, we let MongoEngine handle index creation
    automatically from model definitions. This function now only handles
    special cases like text indexes and TTL indexes.
    """
    from pymongo import TEXT
    from models_mongo.worker import WorkerDoc
    from models_mongo.material import MaterialDoc
    from models_mongo.project import ProjectDoc

    db = WorkerDoc._get_db()

    # Text index for workers (full-text search)
    try:
        db["workers"].create_index(
            [("name", TEXT), ("role", TEXT), ("aliases", TEXT)],
            name="workers_text_search",
            default_language="italian",
            weights={"role": 10, "aliases": 8, "name": 3}
        )
    except Exception:
        pass  # Index might already exist

    # Text index for materials (full-text search)
    try:
        db["materials"].create_index(
            [("name", TEXT), ("aliases", TEXT), ("category", TEXT)],
            name="materials_text_search",
            default_language="italian",
            weights={"aliases": 10, "name": 7, "category": 3}
        )
    except Exception:
        pass  # Index might already exist

    # TTL index for chat_sessions (expire after 7 days)
    try:
        db["chat_sessions"].create_index(
            [("createdAt", 1)],
            expireAfterSeconds=7 * 24 * 3600,
            name="chat_sessions_ttl_7d"
        )
    except Exception:
        pass  # Collection might not exist yet


# Backward-compatible alias
def ensure_indexes_safely():
    return ensure_mongo_indexes()