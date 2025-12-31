# services/company_service.py
import os
from werkzeug.utils import secure_filename
from flask import current_app

# Models
from models_mongo.worker import WorkerDoc
from models_mongo.project import ProjectDoc
from models_mongo.material import MaterialDoc
from mongoengine.connection import get_db

# Config
try:
    from config.company import get_company_info
except ImportError:
    # Fallback se il file config non esiste
    def get_company_info():
        return {"name": "Edilizia Demo", "piva": "00000000000"}

class CompanyService:
    """
    Gestisce informazioni globali dell'azienda, dashboard KPI e documenti corporate.
    """

    @staticmethod
    def _ensure_dir(path: str):
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)

    @staticmethod
    def get_overview() -> dict:
        """Calcola KPI globali per la dashboard principale."""
        db = get_db()
        
        # 1. Company Info
        company = get_company_info()
        
        # 2. Counts
        workers_total = WorkerDoc.objects.count()
        active_workers = WorkerDoc.objects(available=True).count()
        
        projects_total = ProjectDoc.objects.count()
        active_projects = ProjectDoc.objects(status__iexact="Confermato").count()
        
        materials_total = MaterialDoc.objects.count()
        
        # 3. Documents Count
        docs_dir = os.path.join("data", "documents")
        documents_total = 0
        if os.path.exists(docs_dir):
            documents_total = len([
                f for f in os.listdir(docs_dir) 
                if os.path.isfile(os.path.join(docs_dir, f))
            ])
            
        # 4. Roles Breakdown (Aggregazione)
        roles_agg = list(db["workers"].aggregate([
            {"$group": {"_id": "$role", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]))
        roles_breakdown = {r["_id"]: r["count"] for r in roles_agg if r.get("_id")}
        
        # 5. Active Projects List (Preview)
        active_projects_list = [
            {"id": str(p.id), "name": p.name, "city": p.city}
            for p in ProjectDoc.objects(status__iexact="Confermato").only("id", "name", "city")
        ]
        
        return {
            "company": company,
            "stats": {
                "workers_total": workers_total,
                "active_workers": active_workers,
                "projects_total": projects_total,
                "active_projects": active_projects,
                "materials_total": materials_total,
                "documents_total": documents_total,
            },
            "roles_breakdown": roles_breakdown,
            "active_projects": active_projects_list,
        }

    @staticmethod
    def list_documents() -> list:
        """Lista documenti nella cartella aziendale globale."""
        docs_dir = os.path.join("data", "documents")
        if not os.path.exists(docs_dir):
            return []
            
        return [
            {"name": f, "path": os.path.join(docs_dir, f)}
            for f in os.listdir(docs_dir)
            if os.path.isfile(os.path.join(docs_dir, f))
        ]

    @staticmethod
    def upload_document(file_storage) -> dict:
        """Salva documento aziendale e lo indicizza (RAG Globale)."""
        if not file_storage or not file_storage.filename:
            raise ValueError("File non valido")
            
        filename = secure_filename(file_storage.filename)
        docs_dir = os.path.join("data", "documents")
        CompanyService._ensure_dir(docs_dir)
        
        filepath = os.path.join(docs_dir, filename)
        file_storage.save(filepath)
        
        # Indexing (Best Effort)
        indexed = False
        error = None
        try:
            from utils.file_processor import FileProcessor
            from models.vector_store import VectorStore
            
            # Recupera parametri da env o usa default
            q_path = os.getenv("QDRANT_PATH", "./qdrant_data")
            q_col = os.getenv("QDRANT_COLLECTION", "documents")
            emb_model = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
            emb_dim = int(os.getenv("EMBEDDING_DIM", "384"))

            processor = FileProcessor()
            with open(filepath, 'rb') as f:
                file_data = f.read()
            
            # project_id="GLOBAL" indica documenti aziendali trasversali
            chunks, metadatas = processor.process_file(file_data, filename, project_id="GLOBAL")
            
            vector_store = VectorStore(
                path=q_path,
                collection_name=q_col,
                embedding_model=emb_model,
                embedding_dim=emb_dim
            )
            vector_store.add_documents(chunks, metadatas)
            indexed = True
            
        except Exception as e:
            error = str(e)
            # Loggare l'errore ma non bloccare l'upload fisico
            # print(f"Indexing error: {e}")

        return {
            "success": True,
            "filename": filename,
            "indexed": indexed,
            "error": error
        }