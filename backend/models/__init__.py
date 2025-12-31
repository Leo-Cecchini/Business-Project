"""
Pacchetto 'models': mantiene utility non-DB (vector_store, chat_model).
I modelli dati sono su 'models_mongo'.
I moduli SQLAlchemy legacy sono deprecati.
"""

import warnings

_DEPRECATED = {"project", "db"}

def __getattr__(name: str):
    # Se qualcuno tenta di importare i vecchi moduli, blocca subito
    if name in _DEPRECATED:
        raise ImportError(
            f"Il modulo 'models.{name}' è deprecato. Usa i modelli in 'models_mongo'."
        )
    # Per altri nomi, lascia che Python carichi i sottomoduli normalmente
    raise AttributeError(name)