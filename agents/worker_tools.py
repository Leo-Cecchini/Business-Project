# agents/worker_tools.py
from langchain_core.tools import tool
from models.tools import CreateWorker, RemoveWorker
from services.workers_service import create_worker_service, remove_worker_service

def current_user():
    """Recupera l'utente corrente dal tuo contesto Flask.
    Sostituisci con la tua logica (es. flask_login.current_user)."""
    try:
        from flask_login import current_user as cu
        return cu
    except Exception:
        class _Anon:
            id = "anonymous"
            is_admin = True  # <-- per test; in produzione metti False e usa RBAC reale
        return _Anon()

@tool("create_worker", args_schema=CreateWorker)
def create_worker_tool(**kwargs):
    """
    Crea un nuovo operaio nel database.
    Usa questo tool quando l'utente chiede di aggiungere un operaio con un ruolo e, opzionalmente, tariffa e città.
    """
    return create_worker_service(kwargs, current_user())

@tool("remove_worker", args_schema=RemoveWorker)
def remove_worker_tool(**kwargs):
    """
    Rimuove in modo definitivo un operaio dato il suo ID.
    Richiede conferma esplicita (confirm=true) prima di procedere.
    Usa questo tool solo dopo che l'utente ha confermato.
    """
    return remove_worker_service(kwargs, current_user())