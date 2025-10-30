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
    meta = {"collection": "projects", "indexes": ["name", "status"]}
    id = StringField(primary_key=True)
    name = StringField(required=True, index=True)

    # campi del tuo template
    project_date = StringField()                # "YYYY-MM-DD"
    project_address = StringField()
    status = StringField(default="quotation", index=True)   # manteniamo la tua terminologia
    metric_computation_id = StringField()

    works = ListField(EmbeddedDocumentField(WorkItem), default=[])

    # spazio libero per futuri metadati
    meta_extra = DictField()