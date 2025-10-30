# db/mongo.py
import os
from mongoengine import connect

def init_mongo():
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    dbname = os.getenv("MONGODB_DB", "business_project")
    # ✅ usa lo stesso schema ovunque
    connect(db=dbname, host=uri, uuidRepresentation="standard")

def ensure_mongo_indexes():
    from pymongo import ASCENDING, TEXT
    from models_mongo.worker import WorkerDoc
    from models_mongo.material import MaterialDoc
    from models_mongo.project import ProjectDoc

    # usa le collection native per indici
    db = WorkerDoc._get_db()
    W = db["workers"]
    M = db["materials"]
    P = db["projects"]

    # Workers
    W.create_index([("name", ASCENDING)], name="w_name")
    W.create_index([("role", ASCENDING)], name="w_role")
    W.create_index([("available", ASCENDING)], name="w_available")
    try:
        W.create_index([("name", TEXT), ("role", TEXT)], name="w_text", default_language="italian")
    except Exception:
        pass

    # Materials
    M.create_index([("name", ASCENDING)], name="m_name")
    M.create_index([("sku", ASCENDING)], name="m_sku", unique=True)
    M.create_index([("category", ASCENDING)], name="m_category")
    M.create_index([("subcategory", ASCENDING)], name="m_subcategory")
    M.create_index([("unit", ASCENDING)], name="m_unit")
    try:
        M.create_index([("name", TEXT)], name="m_text", default_language="italian")
    except Exception:
        pass

    # Projects
    P.create_index([("name", ASCENDING)], name="p_name")
    P.create_index([("status", ASCENDING)], name="p_status")