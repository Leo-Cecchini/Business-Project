from mongoengine import (
    Document, EmbeddedDocument,
    StringField, FloatField, IntField,
    ListField, EmbeddedDocumentField, DictField
)

class WorkItem(EmbeddedDocument):
    # campi coerenti al tuo template e agli helper
    work_name = StringField(required=True)
    status = StringField(default="planned")     # planned/completed/...
    start_date_planned = StringField()          # "YYYY-MM-DD"
    end_date_planned = StringField()
    start_date_actual = StringField()
    end_date_actual = StringField()
    duration_estimated_hours = FloatField()
    duration_actual_hours = FloatField()
    number_of_workers = IntField()
    workers = ListField(StringField())          # lista di worker-id

class ProjectDoc(Document):
    meta = {
        "collection": "projects",
        "indexes": [
            {"fields": ["name"], "name": "p_name"},
            {"fields": ["status"], "name": "p_status"},
            {"fields": ["id"], "name": "p_id", "unique": True},
            {"fields": ["city"], "name": "p_city"},
            {"fields": ["name", "city"], "name": "p_name_city", "unique": True, "sparse": True},
        ],
        "auto_create_index": False,  # delegato al bootstrap in app.py
    }

    id = StringField(primary_key=True)
    name = StringField(required=True, index=True)

    # campi del tuo template
    project_date = StringField()                # "YYYY-MM-DD"
    project_address = StringField()             # stringa formattata (primario)
    status = StringField(default="quotation", index=True)   # compat terminologia template
    metric_computation_id = StringField()

    # nuovo: supporto indirizzo minimale + città per regola (name+city) unica
    city = StringField()                        # city estesa per filtro/unicità
    addresses = ListField(DictField(), default=[])  # lista indirizzi minimali {formatted, street, street_number, city, state, postal_code}

    # lavori
    works = ListField(EmbeddedDocumentField(WorkItem), default=[])

    # spazio libero per futuri metadati
    meta_extra = DictField()