from functools import wraps
from flask import request, abort

def require_project_access(get_user_projects):
    """
    Decorator che garantisce che un utente possa accedere solo ai cantieri
    autorizzati o alle risorse GLOBAL.
    get_user_projects: funzione che restituisce la lista di ID cantiere
    a cui l'utente corrente ha accesso.
    """
    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            project_id = (
                request.headers.get("X-Project-Id")
                or request.args.get("project_id")
                or (request.json.get("project_id") if request.is_json else None)
            )

            # Se nessun project_id, consideriamo un accesso globale
            if not project_id or project_id == "GLOBAL":
                return fn(*args, **kwargs)

            allowed = get_user_projects() or []
            if project_id not in allowed:
                abort(403, f"Accesso negato al cantiere {project_id}")

            return fn(*args, **kwargs)
        return inner
    return wrapper
