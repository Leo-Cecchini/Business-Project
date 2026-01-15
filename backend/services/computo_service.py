# services/computo_service.py
import os
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional
from werkzeug.utils import secure_filename

# DB Models
from models_mongo.project import ProjectDoc, WorkItem, Address
from models_mongo.computo import ComputoDoc

# Utils
import utils.computo_processor as computo_processor

class ComputoService:
    """
    Gestisce la logica di business per i Computi Metrici:
    - Caricamento/Estrazione da PDF
    - Generazione da Descrizione (AI)
    - Pianificazione lavori da Computo (AI)
    - Generazione Report PDF
    """

    @staticmethod
    def _get_project_or_raise(project_id: str) -> ProjectDoc:
        p = ProjectDoc.objects(id=project_id).first()
        if not p:
            raise ValueError(f"Progetto {project_id} non trovato")
        return p

    @staticmethod
    def _ensure_dir(path: str):
        if not os.path.exists(path):
            os.makedirs(path)

    @staticmethod
    def process_pdf_upload(project_id: str, file_storage, ai_model) -> ComputoDoc:
        """
        Salva il PDF, estrae il computo con AI e crea il documento DB.
        """
        project = ComputoService._get_project_or_raise(project_id)
        
        # 1. Setup percorsi
        upload_dir = os.path.join("data", "projects", project_id, "computi_raw")
        ComputoService._ensure_dir(upload_dir)
        
        filename = secure_filename(file_storage.filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{timestamp}_{filename}"
        pdf_path = os.path.join(upload_dir, unique_filename)
        
        file_storage.save(pdf_path)
        
        # 2. Estrazione dati (usando il processor esistente)
        temp_id = str(uuid.uuid4())
        
        try:
            extracted_data = computo_processor.extract_computo_from_pdf(
                model=ai_model,
                pdf_path=pdf_path,
                document_id=temp_id
            )
        except Exception as e:
            # Rilanciamo come ValueError per essere catturato come 400/404 dalla route
            raise ValueError(f"Errore lettura PDF: {str(e)}")
        
        if not extracted_data:
            raise ValueError("Estrazione fallita o nessun dato trovato")

        # 3. Creazione ComputoDoc
        computo = ComputoDoc(
            project_id=project_id,
            computo_code=f"CME-{timestamp}", 
            metadata=extracted_data.get("metadata", {}),
            bill_of_quantities=extracted_data.get("bill_of_quantities", []),
            summary=extracted_data.get("summary", []),
            grand_total=float(extracted_data.get("grand_total") or 0.0)
        )
        computo.save()
        
        # 4. Link al Progetto (FIX: usa metric_computation_id al singolare)
        current_ids = list(project.metric_computation_id or [])
        current_ids.append(str(computo.id))
        project.metric_computation_id = current_ids
        
        # Aggiorna meta_extra per compatibilità frontend
        meta = dict(project.meta_extra or {})
        meta["computo_metrico"] = computo.to_dict() 
        project.meta_extra = meta
        
        project.save()
        
        return computo

    @staticmethod
    def generate_from_description(project_id: str, description: str, ai_model) -> ComputoDoc:
        """
        Genera un computo ex-novo partendo dalla descrizione testuale (AI).
        """
        project = ComputoService._get_project_or_raise(project_id)
        
        # Prepara metadata per il prompt
        # Gestione sicura indirizzo
        loc = project.city
        if not loc and project.addresses:
            loc = project.addresses.city
        if not loc:
            loc = ""

        meta_context = {
            "document_title": f"Stima {project.name}",
            "subject": description[:50] + "...",
            "client": getattr(project, "client_name", "Committente"),
            "location": loc,
            "date": datetime.now().strftime("%Y-%m-%d")
        }
        
        temp_id = str(uuid.uuid4())
        
        # Chiamata al processor
        generated_data = computo_processor.generate_computo_from_description(
            model=ai_model,
            project_description=description,
            metadata=meta_context,
            document_id=temp_id
        )
        
        if not generated_data:
            raise ValueError("Generazione AI fallita")

        # Creazione e Salvataggio
        timestamp = datetime.now().strftime("%Y%m%d")
        computo = ComputoDoc(
            project_id=project_id,
            computo_code=f"GEN-{timestamp}-{str(uuid.uuid4())[:4]}",
            metadata=generated_data.get("metadata", {}),
            bill_of_quantities=generated_data.get("bill_of_quantities", []),
            summary=generated_data.get("summary", []),
            grand_total=float(generated_data.get("grand_total") or 0.0)
        )
        computo.save()
        
        # Link Project (FIX: usa metric_computation_id)
        current_ids = list(project.metric_computation_id or [])
        current_ids.append(str(computo.id))
        project.metric_computation_id = current_ids
        
        meta = dict(project.meta_extra or {})
        meta["computo_metrico"] = computo.to_dict()
        project.meta_extra = meta
        project.save()
        
        return computo

    @staticmethod
    def plan_works_from_computo(project_id: str, start_date: str, ai_model) -> List[WorkItem]:
        """
        Usa l'ultimo computo associato per generare una pipeline lavori (Plan).
        """
        project = ComputoService._get_project_or_raise(project_id)
        
        # FIX: usa metric_computation_id
        if not project.metric_computation_id:
            raise ValueError("Nessun computo associato al progetto")
            
        latest_computo_id = project.metric_computation_id[-1]
        computo = ComputoDoc.objects(id=latest_computo_id).first()
        
        if not computo:
            raise ValueError("Documento computo non trovato nel DB")
            
        # Generazione pipeline tramite processor
        computo_data = computo.to_dict()

        # NOTE: anche senza chiave Google o con chiave non valida, il processor
        # è in grado di generare una pipeline *fallback*. Qui rendiamo robusto
        # il parsing per evitare errori/"piano vuoto".
        pipeline_json = computo_processor.generate_work_pipeline(
            model=ai_model,
            metric_data=computo_data,
            start_date=start_date,
        )

        # Alcune versioni possono restituire un dict (es. {items:[...]})
        if isinstance(pipeline_json, dict):
            pipeline_json = (
                pipeline_json.get("items")
                or pipeline_json.get("plan")
                or pipeline_json.get("works")
                or []
            )

        # Se ancora vuoto, prova fallback esplicito (se disponibile)
        if not pipeline_json:
            if hasattr(computo_processor, "generate_pipeline_fallback"):
                pipeline_json = computo_processor.generate_pipeline_fallback(computo_data, start_date)
            elif hasattr(computo_processor, "generate_pipeline_from_computo"):
                pipeline_json = computo_processor.generate_pipeline_from_computo(computo_data, start_date)

        if not pipeline_json:
            raise ValueError("Pipeline lavori vuota: genera prima la sequenza lavori (" \
                             "oppure configura GOOGLE_API_KEY per pianificazione AI)")
            
        # Conversione in WorkItem e salvataggio
        work_items = []
        for item in pipeline_json:
            if not isinstance(item, dict):
                # Evita crash se arriva una lista di stringhe/chiavi
                continue
            valid_fields = {k: v for k, v in item.items() if k in WorkItem._fields}
            
            # FIX: Converti le date stringa in oggetti date python se necessario
            # MongoEngine lo fa in automatico se assegni a DateField, ma per sicurezza:
            for d_field in ['start_date_planned', 'end_date_planned']:
                val = valid_fields.get(d_field)
                if val and isinstance(val, str):
                    try:
                        valid_fields[d_field] = datetime.strptime(val, "%Y-%m-%d").date()
                    except ValueError:
                         valid_fields[d_field] = None

            work_items.append(WorkItem(**valid_fields))
            
        project.works = work_items
        
        project.status = "In corso" if project.status == "Confermato" else project.status
        project.save()
        
        return work_items

    @staticmethod
    def get_latest_computo(project_id: str) -> Optional[ComputoDoc]:
        project = ComputoService._get_project_or_raise(project_id)
        # FIX: usa metric_computation_id
        if not project.metric_computation_id:
            return None
        return ComputoDoc.objects(id=project.metric_computation_id[-1]).first()

    @staticmethod
    def generate_pdf_report(project_id: str, computo_id: str = None) -> str:
        """
        Genera il PDF fisico del computo e ritorna il path.
        """
        if computo_id:
            computo = ComputoDoc.objects(id=computo_id).first()
        else:
            computo = ComputoService.get_latest_computo(project_id)
            
        if not computo:
            raise ValueError("Computo non trovato")
            
        output_dir = os.path.join("data", "projects", project_id, "computi_pdf")
        ComputoService._ensure_dir(output_dir)
        
        filename = f"Computo_{computo.computo_code or computo.id}.pdf"
        output_path = os.path.join(output_dir, filename)
        
        computo_processor.create_pdf_report(computo.to_dict(), output_path)
        
        return output_path
