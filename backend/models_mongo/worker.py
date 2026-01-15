# models_mongo/worker.py
"""
Worker model - MongoDB native ObjectId (no custom ID).
"""
from mongoengine import Document, StringField, FloatField, BooleanField, ListField


class WorkerDoc(Document):
    """
    Worker document.
    
    Note: Uses MongoDB native ObjectId (_id field auto-generated).
    No custom 'code' field - frontend uses ObjectId directly.
    """
    meta = {
        'collection': 'workers',
        'strict': False,  # ✅ Ignora campi extra come "ID"
        'indexes': [
            'name',
            'role',
            'available',
            'home_city',
            {'fields': ['role', 'home_city']},
        ]
    }
    
    # Basic info
    name = StringField(required=True, max_length=120)
    role = StringField(max_length=80)
    hourly_rate = FloatField()
    
    # Availability
    available = BooleanField(default=True)
    is_active = BooleanField(default=True)  # ✅ Alias per frontend compatibility
    
    # Location
    home_region = StringField(max_length=120)
    home_city = StringField(max_length=120)
    
    # Skills & Certifications (stored as lists)
    skills = ListField(StringField(), default=list)
    certifications = ListField(StringField(), default=list)
    
    # Aliases for role search (generated from role normalization)
    aliases = ListField(StringField(), default=list)
    
    def to_dict(self) -> dict:
        """Serialize to dict for API responses."""
        return {
            "id": str(self.id),  # ObjectId as string
            "name": self.name,
            "role": self.role,
            "hourly_rate": self.hourly_rate,
            "available": self.available,
            "is_active": self.is_active if hasattr(self, 'is_active') else self.available,  # ✅ Aggiungi is_active
            "home_city": self.home_city,
            "skills": self.skills,
            "certifications": self.certifications,
            "aliases": self.aliases,
        }
    
    def __repr__(self) -> str:
        return f"<WorkerDoc id={self.id} name={self.name!r} role={self.role!r}>"