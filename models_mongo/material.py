from mongoengine import Document, StringField, FloatField, IntField, DictField

class MaterialDoc(Document):
    meta = {
        "collection": "materials",
        "indexes": [
            "name", "category", "subcategory",
            {"fields": ["sku"], "unique": True},
            {"fields": ["unit"]}
        ]
    }
    id = StringField(primary_key=True)           # normalizzato a stringa nello script
    name = StringField(required=True)
    category = StringField()
    subcategory = StringField()
    unit = StringField(required=True, choices=["kg","m2","m3","pz","lt","m"])
    unit_price_eur_2025 = FloatField()
    supplier = StringField()
    vat_rate = FloatField()
    sku = StringField(required=True)
    stock_qty = FloatField()
    lead_time_days = IntField()
    notes = StringField()
    extra = DictField()