from mongoengine import Document, StringField, FloatField, IntField, DictField, ListField

class MaterialDoc(Document):
    meta = {
        "collection": "materials",
        "indexes": [
            {"fields": ["name"], "name": "m_name"},
            {"fields": ["category"], "name": "m_category"},
            {"fields": ["subcategory"], "name": "m_subcategory"},
            {"fields": ["sku"], "name": "m_sku", "unique": True},
            {"fields": ["unit"], "name": "m_unit"},
            {"fields": ["aliases"], "name": "m_aliases"},
            {"fields": ["category", "subcategory", "aliases"], "name": "m_cat_subcat_aliases"},
            # Text index per ricerca full-text
            {  # versione indicizzata per evitare conflitti futuri
                "fields": ["$name", "$aliases", "$category", "$subcategory"],
                "name": "m_text_v1",
                "default_language": "italian",
                "weights": {
                    "aliases": 10,
                    "category": 3,
                    "name": 7,
                    "subcategory": 3,
                },
            },
        ],
        "auto_create_index": False,  # delegato al bootstrap in app.py
    }

    id = StringField(primary_key=True)           # normalizzato a stringa nello script
    name = StringField(required=True)
    aliases = ListField(StringField())           # NEW: list of normalized aliases/synonyms
    category = StringField()
    subcategory = StringField()
    unit = StringField(required=True, choices=["kg", "m2", "m3", "pz", "lt", "m"])
    unit_price_eur_2025 = FloatField()
    supplier = StringField()
    vat_rate = FloatField()
    sku = StringField(required=True)
    stock_qty = FloatField()
    lead_time_days = IntField()
    notes = StringField()
    extra = DictField()