# models_mongo/project.py
"""
Project model - MongoDB native ObjectId (no custom ID).
"""
from mongoengine import (
    Document, EmbeddedDocument, StringField, DateField, 
    FloatField, ListField, DictField, EmbeddedDocumentField,
    EmbeddedDocumentListField
)


class Address(EmbeddedDocument):
    """Structured address object."""
    formatted = StringField(max_length=500)  # "Via Roma, 56126 Pisa PI, Italia"
    street = StringField(max_length=200)
    street_number = StringField(max_length=20)
    city = StringField(max_length=100)
    state = StringField(max_length=100)
    postal_code = StringField(max_length=20)


class WorkItem(EmbeddedDocument):
    """Embedded work item within project."""
    work_name = StringField(required=True)
    status = StringField(default="planned")
    start_date_planned = DateField()
    end_date_planned = DateField()
    start_date_actual = DateField()  # ✅ Aggiungi campo actual
    end_date_actual = DateField()    # ✅ Aggiungi campo actual
    duration_estimated_hours = FloatField()
    duration_actual_hours = FloatField()  # ✅ Aggiungi campo actual
    number_of_workers = FloatField()
    workers = ListField(StringField(), default=list)  # List of worker ObjectIds as strings


class ProjectDoc(Document):
    """
    Project document.
    
    Note: Uses MongoDB native ObjectId (_id field auto-generated).
    Computo is embedded in meta_extra.computo_metrico for frontend compatibility.
    """
    meta = {
        'collection': 'projects',
        'strict': False,  # ✅ Ignora campi extra non definiti
        # Indici base (senza conflitti)
        'indexes': [
            'name',
            'status',
        ]
    }
    
    # Basic info
    name = StringField(required=True, max_length=200)
    project_date = DateField()
    status = StringField(default="Preventivo", max_length=50)
    
    # Address (structured object)
    addresses = EmbeddedDocumentField(Address)  # Singolo oggetto (non array)
    
    # Legacy fields (for backward compatibility)
    project_address = StringField(max_length=500)  # Old simple string address
    city = StringField(max_length=100)  # Old city field
    
    # Works (embedded array)
    works = EmbeddedDocumentListField(WorkItem, default=list)
    
    # Computo embedded (for frontend compatibility)
    meta_extra = DictField(default=dict)
    
    # Reference to computo ID (can be string or list)
    metric_computation_id = ListField(StringField(), default=list)
    
    def to_dict(self) -> dict:
        """Serialize to dict for API responses."""
        
        def _date_to_str(d):
            if d is None:
                return None
            if isinstance(d, str):
                return d  # Già stringa
            return d.isoformat()  # datetime → string
        
        result = {
            "id": str(self.id),
            "name": self.name,
            "project_date": _date_to_str(self.project_date),
            "status": self.status,
            "works": [
                {
                    "work_name": w.work_name,
                    "status": w.status,
                    "start_date_planned": _date_to_str(w.start_date_planned),
                    "end_date_planned": _date_to_str(w.end_date_planned),
                    "start_date_actual": _date_to_str(w.start_date_actual) if hasattr(w, 'start_date_actual') else None,  # ✅
                    "end_date_actual": _date_to_str(w.end_date_actual) if hasattr(w, 'end_date_actual') else None,  # ✅
                    "duration_estimated_hours": w.duration_estimated_hours,
                    "duration_actual_hours": w.duration_actual_hours if hasattr(w, 'duration_actual_hours') else None,  # ✅
                    "number_of_workers": w.number_of_workers,
                    "workers": w.workers,
                }
                for w in self.works
            ],
            "meta_extra": self.meta_extra,
            "metric_computation_id": self.metric_computation_id,
        }
        
        # Add addresses if present
        if self.addresses:
            result["addresses"] = {
                "formatted": self.addresses.formatted,
                "street": self.addresses.street,
                "street_number": self.addresses.street_number,
                "city": self.addresses.city,
                "state": self.addresses.state,
                "postal_code": self.addresses.postal_code,
            }
        
        # Add legacy fields if present
        if self.project_address:
            result["project_address"] = self.project_address
        if self.city:
            result["city"] = self.city
        
        return result
    
    def __repr__(self) -> str:
        return f"<ProjectDoc id={self.id} name={self.name!r} status={self.status!r}>"