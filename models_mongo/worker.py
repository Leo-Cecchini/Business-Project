from mongoengine import Document, StringField, FloatField, BooleanField, ListField

class WorkerDoc(Document):
    meta = {
        "collection": "workers",
        "indexes": [
            "name",
            "role",
            {"fields": ["available"], "name": "w_available"}
        ]
    }
    id = StringField(primary_key=True)  # dagli JSON (ID/id/_id → normalizzato nello script)
    name = StringField(required=True)
    role = StringField(required=True)
    hourly_rate = FloatField()
    available = BooleanField(default=True)
    home_city = StringField()
    skills = ListField(StringField())
    certifications = ListField(StringField())