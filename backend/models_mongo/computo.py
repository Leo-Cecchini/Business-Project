# models_mongo/computo.py
"""
Computo Metrico model - MongoDB native ObjectId (no custom ID).
"""
from mongoengine import Document, StringField, DateField, FloatField, ListField, DictField
from datetime import datetime


class ComputoDoc(Document):
    """
    Computo Metrico (Bill of Quantities) document.
    
    Note: Uses MongoDB native ObjectId (_id field auto-generated).
    computo_code (e.g., CME-xxx) kept as separate field for reference.
    """
    meta = {
        'collection': 'computo_metrico',
        'indexes': [
            'computo_code',
            'project_id',
        ]
    }
    
    # Business reference code (optional)
    computo_code = StringField(max_length=50, unique=True, sparse=True)
    
    # Project reference (ObjectId as string)
    project_id = StringField()
    
    # Metadata
    metadata = DictField(default=dict)
    
    # Bill of quantities
    bill_of_quantities = ListField(DictField(), default=list)
    
    # Summary
    summary = ListField(DictField(), default=list)
    
    # Grand total
    grand_total = FloatField(default=0.0)
    
    # Timestamps
    created_at = DateField(default=datetime.utcnow)
    
    def to_dict(self) -> dict:
        """Serialize to dict for API responses."""
        return {
            "id": str(self.id),
            "computo_code": self.computo_code,
            "project_id": self.project_id,
            "metadata": self.metadata,
            "bill_of_quantities": self.bill_of_quantities,
            "summary": self.summary,
            "grand_total": self.grand_total,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    
    def __repr__(self) -> str:
        return f"<ComputoDoc id={self.id} code={self.computo_code!r} total={self.grand_total}>"