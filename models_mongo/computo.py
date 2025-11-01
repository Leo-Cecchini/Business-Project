# models_mongo/computo.py
from mongoengine import Document, StringField, DictField, DateTimeField, ListField
from datetime import datetime

class ComputoDoc(Document):
    """
    Rappresenta un singolo documento di Computo Metrico Estimativo (CME).
    Ogni documento vive in una collezione separata 'computi'.
    """
    meta = {
        "collection": "computi",
        "indexes": [
            "project_id", # Per cercare rapidamente tutti i computi di un progetto
            "created_at"
        ],
    }

    # ID primario (es. "CME-GEN-1234abcd")
    id = StringField(primary_key=True)
    
    # Riferimento (opzionale) al progetto a cui appartiene
    project_id = StringField()

    # Il JSON completo del computo metrico (estratto o generato)
    data = DictField()
    
    # Timestamp di quando è stato creato
    created_at = DateTimeField(default=datetime.utcnow)