# models_mongo/material.py
"""
Material model - MongoDB native ObjectId (no custom ID).
"""
from mongoengine import Document, StringField, FloatField, ListField


class MaterialDoc(Document):
    """
    Material document.
    
    Note: Uses MongoDB native ObjectId (_id field auto-generated).
    SKU is kept as separate field for business logic (not primary key).
    """
    meta = {
        'collection': 'materials',
        'indexes': [
            'name',
            'sku',
            'category',
            'unit',
        ]
    }
    
    # Business identifiers
    sku = StringField(max_length=100, unique=True, sparse=True)
    name = StringField(required=True, max_length=300)
    
    # Categorization
    category = StringField(max_length=100)
    unit = StringField(max_length=20)
    
    # Pricing
    unit_price_eur_2025 = FloatField()
    
    # Search helpers
    aliases = ListField(StringField(), default=list)
    
    def to_dict(self) -> dict:
        """Serialize to dict for API responses."""
        return {
            "id": str(self.id),
            "sku": self.sku,
            "name": self.name,
            "category": self.category,
            "unit": self.unit,
            "unit_price_eur_2025": self.unit_price_eur_2025,
            "aliases": self.aliases,
        }
    
    def __repr__(self) -> str:
        return f"<MaterialDoc id={self.id} sku={self.sku!r} name={self.name!r}>"