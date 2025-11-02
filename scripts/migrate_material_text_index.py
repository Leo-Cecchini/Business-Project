"""
Script di migrazione per l'indice full-text del modello MaterialDoc.

Questo script serve a creare un nuovo indice versionato (m_text_v1) con i pesi corretti,
ed eventualmente eliminare il vecchio indice (m_text) che causava conflitti
di opzioni in MongoDB (IndexOptionsConflict).

Va eseguito UNA SOLA VOLTA dopo aver aggiornato il modello in models_mongo/material.py.
Non va inserito nel ciclo di esecuzione dell'app (non dentro le route). 

Utilizzo:
    python scripts/migrate_material_text_index.py

"""

import sys, pathlib
# Aggiunge la root del progetto al PYTHONPATH quando eseguito come script
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mongoengine import connect
from models_mongo.material import MaterialDoc


def main():
    # Connessione: aggiorna i parametri in base alla tua configurazione
    connect(alias="default")  # oppure connect(db="BusinessProject", host="localhost", port=27017)

    coll = MaterialDoc._get_collection()
    existing = {i["name"]: i for i in coll.list_indexes()}

    # 1️⃣ Crea l'indice m_text_v1 se non esiste
    if "m_text_v1" not in existing:
        print("Creazione indice m_text_v1...")
        coll.create_index(
            [("name", "text"), ("aliases", "text"), ("category", "text"), ("subcategory", "text")],
            name="m_text_v1",
            default_language="italian",
            language_override="language",
            weights={
                "aliases": 10,
                "category": 3,
                "name": 7,
                "subcategory": 3,
            },
        )
        print("✅ Indice m_text_v1 creato.")
    else:
        print("Indice m_text_v1 già esistente, salto creazione.")

    # 2️⃣ Drop del vecchio indice confliggente
    if "m_text" in existing:
        print("Trovato vecchio indice m_text → lo elimino...")
        try:
            coll.drop_index("m_text")
            print("✅ Indice m_text eliminato.")
        except Exception as e:
            print("⚠️ Errore nel drop dell'indice m_text:", e)
    else:
        print("Nessun vecchio indice m_text trovato, tutto ok.")

    print("\nMigrazione completata con successo.")


if __name__ == "__main__":
    main()
