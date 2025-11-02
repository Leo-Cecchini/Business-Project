from mongoengine import Document, StringField, FloatField, BooleanField, ListField

class WorkerDoc(Document):
    meta = {
        "collection": "workers",
        "indexes": [
            {"fields": ["name"], "name": "w_name"},
            {"fields": ["role"], "name": "w_role"},
            {"fields": ["available"], "name": "w_available"},
            {"fields": ["name", "role", "home_city"], "name": "w_name_role_city", "unique": True},
            {"fields": ["aliases"], "name": "w_aliases"},
            {"fields": ["role", "aliases"], "name": "w_role_aliases"},
            # Text index per ricerche full-text su name/role/aliases
            {"fields": ["$name", "$role", "$aliases"], "name": "w_text", "default_language": "italian"},
        ],
        "auto_create_index": False,  # delegato al bootstrap in app.py
    }

    id = StringField(primary_key=True)
    name = StringField(required=True)
    role = StringField(required=True)
    aliases = ListField(StringField())                 # NEW: list of normalized aliases/synonyms
    hourly_rate = FloatField()
    available = BooleanField(default=True)
    home_city = StringField()
    skills = ListField(StringField())
    certifications = ListField(StringField())