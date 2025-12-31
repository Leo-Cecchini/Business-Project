# models_mongo/pricelist.py
from mongoengine import Document, StringField, DictField, DateTimeField
from datetime import datetime

class PricelistDoc(Document):
    meta = {
        "collection": "pricelists",
        "indexes": [
            {"fields": ["region", "city"], "unique": True, "name": "uniq_region_city"},
        ],
    }

    region   = StringField(required=True)
    city     = StringField(default="")  # vuota = prezzario regionale
    materials = DictField()  # es: {"FLR-001": 21.2, "BSK-001": 7.1}
    wages     = DictField()  # es: {"piastrellista": 31.0, "muratore": 26.0}
    factors   = DictField()  # es: {"historic_center": 1.06, "remote": 1.08}
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        if self.city is None:
            self.city = ""
        return super().save(*args, **kwargs)