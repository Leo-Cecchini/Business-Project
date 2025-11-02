from mongoengine import Document, StringField, DictField, DateTimeField
from datetime import datetime


class CompanyDoc(Document):
    """
    Rappresenta la ditta principale del sistema.
    Poiché il progetto si basa su un'unica azienda edile,
    questa collezione conterrà un solo documento.
    """
    meta = {
        "collection": "company",
        "indexes": [
            {"fields": ["name"], "name": "c_name"},
            {"fields": ["vat_number"], "name": "c_vat"},
            {"fields": ["city"], "name": "c_city"},
        ],
        # Disabilita creazione automatica multipla: verrà eseguita una sola volta al bootstrap
        "auto_create_index": False,
    }

    # ID fisso per evitare duplicati
    id = StringField(primary_key=True, default="COMPANY-001")

    # Dati principali
    name = StringField(required=True)
    vat_number = StringField()         # Partita IVA
    address = StringField()
    city = StringField()
    country = StringField(default="Italia")
    phone = StringField()
    email = StringField()

    created_at = DateTimeField(default=datetime.utcnow)

    # Campo flessibile per futuri metadati
    meta_extra = DictField()