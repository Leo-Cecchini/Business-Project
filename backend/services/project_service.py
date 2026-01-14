# services/project_service.py
"""
Business logic per gestione progetti/cantieri.
"""
import os
from typing import Optional, List, Dict, Any
from datetime import datetime
from models_mongo.project import ProjectDoc
from werkzeug.utils import secure_filename
from models.vector_store import VectorStore
from utils.file_processor import FileProcessor
from bson import ObjectId
from mongoengine.connection import get_db


class ProjectService:
    """Service per operazioni CRUD e business logic sui progetti."""
    
    @staticmethod
    def create_project(data: Dict[str, Any]) -> ProjectDoc:
        """
        Crea nuovo progetto con validazione.
        
        Args:
            data: Dict con campi progetto
            
        Returns:
            ProjectDoc: Progetto creato
            
        Raises:
            ValueError: Se validazione fallisce
        """
        # Validazione base
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("Nome cantiere obbligatorio")
        
        # Normalizza status
        status = ProjectService._normalize_status(data.get("status"))
        
        # City opzionale
        city = (data.get("city") or "").strip() or None
        
        # Verifica unicità (name, city)
        if ProjectDoc.objects(name=name, city=city).first():
            raise ValueError("Esiste già un cantiere con lo stesso nome nella stessa città")
        
        # ✅ RIMOSSO: Non accettiamo più ID custom dal payload
        # MongoDB genera ObjectId automaticamente
                
        # Date stimate (opzionali)
        start_str = (data.get("start") or data.get("start_date_estimated") or "").strip()
        end_str = (data.get("end") or data.get("end_date_estimated") or "").strip()
        
        # Validazione date per progetti confermati
        if status == "Confermato":
            if not start_str or not end_str:
                raise ValueError("Per 'Confermato' sono obbligatorie le date inizio e fine")
            
            # Valida ordine date
            try:
                s = datetime.strptime(start_str, "%Y-%m-%d")
                e = datetime.strptime(end_str, "%Y-%m-%d")
                if e < s:
                    raise ValueError("La data di fine non può essere antecedente alla data di inizio")
            except ValueError as ve:
                if "does not match format" in str(ve):
                    raise ValueError("Formato data non valido. Usa YYYY-MM-DD")
                raise
        
        # Indirizzo normalizzato
        # Indirizzo strutturato (nuovo formato)
        address_data = data.get("addresses") or data.get("address")
        addresses_obj = None
        
        if address_data and isinstance(address_data, dict):
            # Crea oggetto Address strutturato
            from models_mongo.project import Address
            addresses_obj = Address(
                formatted=address_data.get("formatted"),
                street=address_data.get("street"),
                street_number=address_data.get("street_number"),
                city=address_data.get("city"),
                state=address_data.get("state"),
                postal_code=address_data.get("postal_code"),
            )
        
        # Fallback: indirizzo semplice (legacy)
        simple_address = None
        if not addresses_obj:
            simple_address = (data.get("project_address") or data.get("address") or "").strip() or None
        
        # Crea meta_extra
        meta_extra = {
            "created_at": datetime.utcnow().strftime("%Y-%m-%d")
        }
        
        if start_str or end_str:
            meta_extra["estimate"] = {
                "start": start_str or None,
                "end": end_str or None
            }
        
       # Crea documento
        project = ProjectDoc(
            name=name,
            status=status,
            city=city,  # Legacy field
            addresses=addresses_obj,  # Nuovo campo strutturato
            project_address=simple_address,  # Legacy fallback
            meta_extra=meta_extra
        )
        
        project.save()
        return project
    
    @staticmethod
    def get_project(project_id: str) -> Optional[ProjectDoc]:
        """Recupera progetto per ID (ora accetta ObjectId string)."""
        return ProjectDoc.objects(id=project_id).first()
    
    @staticmethod
    def list_projects(filters: Optional[Dict[str, Any]] = None, page: int = None, per_page: int = None) -> Dict[str, Any]:
        """
        Lista progetti con filtri e paginazione.
        Ritorna dict {items: list, total: int}.
        """
        query = ProjectDoc.objects
        
        if filters:
            if "status" in filters:
                query = query.filter(status__iexact=filters["status"])
            if "city" in filters:
                query = query.filter(city__icontains=filters["city"])
        
        # Ordinamento default: più recenti prima
        query = query.order_by("-id")
        
        total = query.count()
        
        if page is not None and per_page is not None:
            skip = (page - 1) * per_page
            items = list(query.skip(skip).limit(per_page))
        else:
            items = list(query)
            
        return {"items": items, "total": total}
   
    @staticmethod
    def update_project(project_id: str, data: dict):
        """
        Aggiorna un progetto esistente.
        
        Args:
            project_id: ObjectId string del progetto
            data: Dict con campi da aggiornare
            
        Returns:
            ProjectDoc aggiornato o None se non trovato
            
        Raises:
            ValueError: Se project_id invalido o update fallisce
        """
        
        # Converti project_id in ObjectId
        try:
            oid = ObjectId(project_id)
        except Exception as e:
            raise ValueError(f"project_id invalido: {project_id}")
        
        # Recupera progetto con mongoengine
        try:
            project = ProjectDoc.objects.get(id=oid)
        except ProjectDoc.DoesNotExist:
            return None
        
        # Campi aggiornabili
        allowed_fields = [
            'name', 'status', 'project_date', 'project_address', 
            'city', 'meta_extra'
        ]
        
        # Aggiorna solo campi consentiti
        updated = False
        for field in allowed_fields:
            if field in data:
                if field == 'meta_extra':
                    # Deep merge meta_extra invece di shallow merge
                    existing_meta = dict(project.meta_extra or {})
                    new_meta = data[field]
                    
                    # Assicurati che sia un dict
                    if not isinstance(new_meta, dict):
                        raise ValueError(f"meta_extra deve essere un dict, ricevuto {type(new_meta)}")
                    
                    # Deep merge usando helper method
                    merged_meta = ProjectService._deep_merge_dict(existing_meta, new_meta)
                    project.meta_extra = merged_meta
                    
                else:
                    setattr(project, field, data[field])
                updated = True
        
        if updated:
            try:
                project.save()
            except Exception as e:
                # Log error e raise
                import traceback
                print(f"ERROR saving project {project_id}:")
                print(traceback.format_exc())
                raise ValueError(f"Errore salvataggio progetto: {str(e)}")
        
        return project
    
    @staticmethod
    def _deep_merge_dict(base: dict, updates: dict) -> dict:
        """Deep merge ricorsivo di due dizionari."""
        result = dict(base)
        
        for key, value in updates.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Merge ricorsivo se entrambi sono dict
                result[key] = ProjectService._deep_merge_dict(result[key], value)
            else:
                # Sovrascrivi
                result[key] = value
        
        return result
    
    @staticmethod
    def delete_project(project_id: str) -> bool:
        """
        Elimina progetto.
        
        Args:
            project_id: ID progetto (ObjectId string)
        
        Returns:
            bool: True se eliminato, False se non trovato
        """
        result = ProjectDoc.objects(id=project_id).delete()
        return result > 0
    
    @staticmethod
    def toggle_status(project_id: str) -> Optional[ProjectDoc]:
        """
        Toggle status Preventivo ↔ Confermato.
        
        Args:
            project_id: ID progetto (ObjectId string)
        
        Returns:
            ProjectDoc aggiornato o None se non trovato
        """
        project = ProjectDoc.objects(id=project_id).first()
        if not project:
            return None
        
        current = ProjectService._normalize_status(project.status)
        new_status = "Preventivo" if current == "Confermato" else "Confermato"
        
        project.status = new_status
        project.save()
        
        return project
    
    @staticmethod
    def confirm_project(project_id: str, start_date: str, end_date: str) -> Optional[ProjectDoc]:
        """
        Conferma progetto con date stimate.
        
        Args:
            project_id: ID progetto (ObjectId string)
            start_date: Data inizio (YYYY-MM-DD)
            end_date: Data fine (YYYY-MM-DD)
            
        Returns:
            ProjectDoc aggiornato o None se non trovato
            
        Raises:
            ValueError: Se validazione date fallisce
        """
        project = ProjectDoc.objects(id=project_id).first()
        if not project:
            return None
        
        # Valida date
        try:
            s = datetime.strptime(start_date, "%Y-%m-%d")
            e = datetime.strptime(end_date, "%Y-%m-%d")
            if e < s:
                raise ValueError("La data di fine non può precedere la data di inizio")
        except ValueError as ve:
            if "does not match format" in str(ve):
                raise ValueError("Formato data non valido. Usa YYYY-MM-DD")
            raise
        
        # Aggiorna status e date
        project.status = "Confermato"
        
        meta = dict(project.meta_extra or {})
        meta["estimate"] = {
            "start": start_date,
            "end": end_date
        }
        project.meta_extra = meta
        
        project.save()
        return project
    
    @staticmethod
    def _normalize_status(status: Optional[str]) -> str:
        """
        Normalizza status a "Preventivo" o "Confermato".
        
        Args:
            status: Status da normalizzare
            
        Returns:
            str: "Preventivo" o "Confermato"
        """
        if not status:
            return "Preventivo"
        
        s_low = status.strip().lower()
        
        if s_low in {"confermato", "confirmed", "attivo", "active"}:
            return "Confermato"
        
        return "Preventivo"
    
    @staticmethod
    def get_stats() -> Dict[str, Any]:
        """Calcola statistiche progetti."""
        from mongoengine.connection import get_db
        db = get_db()
        
        # Totali per stato
        pipeline = [
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]
        status_counts = list(db["projects"].aggregate(pipeline))
        
        stats = {k: 0 for k in ["Preventivo", "Confermato", "In corso", "Completato", "Archiviato"]}
        total = 0
        
        for item in status_counts:
            st = ProjectService._normalize_status(item["_id"])
            stats[st] = stats.get(st, 0) + item["count"]
            total += item["count"]
            
        return {
            "total": total,
            "by_status": stats
        }

    @staticmethod
    def list_documents(project_id: str) -> List[Dict[str, str]]:
        """Lista i documenti fisici nella cartella del progetto."""
        docs_dir = os.path.join("data", "projects", project_id, "documents")
        if not os.path.exists(docs_dir):
            return []
        
        return [
            {"name": f, "path": os.path.join(docs_dir, f)}
            for f in os.listdir(docs_dir)
            if os.path.isfile(os.path.join(docs_dir, f))
        ]

    @staticmethod
    def upload_document(project_id: str, file_storage) -> Dict[str, Any]:
        """
        Salva il file su disco e lo indicizza su Qdrant.
        Accetta un oggetto FileStorage (da Flask request.files).
        """
        if not file_storage or not file_storage.filename:
            raise ValueError("File non valido")

        filename = secure_filename(file_storage.filename)
        
        # 1. Salvataggio su disco
        docs_dir = os.path.join("data", "projects", project_id, "documents")
        os.makedirs(docs_dir, exist_ok=True)
        filepath = os.path.join(docs_dir, filename)
        file_storage.save(filepath)
        
        # 2. Indicizzazione Qdrant (Logica AI incapsulata nel Service)
        indexed = False
        error_msg = None
        try:
            processor = FileProcessor()
            # Leggiamo il file appena salvato
            with open(filepath, 'rb') as f:
                file_data = f.read()
            
            chunks, metadatas = processor.process_file(file_data, filename, project_id=project_id)
            
            # Configura VectorStore (idealmente questi parametri verrebbero da config globale)
            # NOTE: usare SEMPRE la stessa variabile per la dimensione embeddings,
            # altrimenti Qdrant rifiuta upsert/search per mismatch dimensionale.
            emb_dim = int(os.getenv("EMBEDDING_DIMENSION") or os.getenv("EMBEDDING_DIM") or "768")
            vector_store = VectorStore(
                path=os.getenv("QDRANT_PATH", "./qdrant_data"),
                collection_name=os.getenv("QDRANT_COLLECTION", "documents"),
                embedding_model=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
                embedding_dim=emb_dim
            )
            vector_store.add_documents(chunks, metadatas)
            indexed = True
            
        except Exception as e:
            error_msg = str(e)
            # Non blocchiamo l'upload se fallisce l'indicizzazione, ma lo segnaliamo
        
        return {
            "success": True,
            "filename": filename,
            "indexed": indexed,
            "error": error_msg
        }