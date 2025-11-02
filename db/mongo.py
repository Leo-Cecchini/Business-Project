# db/mongo.py
import os
from mongoengine import connect

def init_mongo():
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    dbname = os.getenv("MONGODB_DB", "business_project")
    connect(db=dbname, host=uri, uuidRepresentation="standard")

def ensure_mongo_indexes():
    """Create/normalize Mongo indexes safely and idempotently.
    - If an index with the same key-spec already exists (even with a different name), drop it and recreate with canonical name.
    - If IndexOptionsConflict (code 85) arises, drop the conflicting index and recreate.
    """
    from pymongo import ASCENDING, TEXT, DESCENDING
    from pymongo.errors import OperationFailure
    from models_mongo.worker import WorkerDoc
    # imports per side-effects (registrano i modelli)
    from models_mongo.material import MaterialDoc  # noqa: F401
    from models_mongo.project import ProjectDoc    # noqa: F401

    db = WorkerDoc._get_db()

    # ===== Reconciliation helpers =====
    def _keys_doc(keys: list[tuple]) -> dict:
        return {k: v for k, v in keys}

    def _list_indexes(col: str):
        try:
            return list(db[col].list_indexes())
        except Exception:
            return []

    def _find_by_keys(col: str, keys: list[tuple]):
        spec = _keys_doc(keys)
        for idx in _list_indexes(col):
            keydoc = dict(idx.get("key") or {})
            if keydoc == spec:
                return idx
        return None

    def _drop_index_by_name(col: str, name: str):
        try:
            db[col].drop_index(name)
        except Exception:
            pass

    def _create_index(col: str, keys: list[tuple], name: str, **opts):
        return db[col].create_index(keys, name=name, **opts)

    # Dizionario degli indici attesi per collezione (nome canonico)
    expected = {
        "workers": [
            ([("name", ASCENDING)], "w_name", {}),
            ([("role", ASCENDING)], "w_role", {}),
            ([("available", ASCENDING)], "w_available", {}),
            ([("aliases", ASCENDING)], "w_aliases", {}),
            ([("role", ASCENDING), ("aliases", ASCENDING)], "w_role_aliases", {}),
            # text index gestito separatamente sotto
        ],
        "materials": [
            ([("name", ASCENDING)], "m_name", {}),
            ([("sku", ASCENDING)], "m_sku", {"unique": True}),
            ([("category", ASCENDING)], "m_category", {}),
            ([("subcategory", ASCENDING)], "m_subcategory", {}),
            ([("unit", ASCENDING)], "m_unit", {}),
            ([("aliases", ASCENDING)], "m_aliases", {}),
            ([("category", ASCENDING), ("subcategory", ASCENDING), ("aliases", ASCENDING)], "m_cat_subcat_aliases", {}),
        ],
        "projects": [
            ([("name", ASCENDING)], "p_name", {}),
            ([("status", ASCENDING)], "p_status", {}),
            ([("id", ASCENDING)], "p_id", {"unique": True}),
            ([("city", ASCENDING)], "p_city", {}),
        ],
        "project_drafts": [
            ([("draft_id", ASCENDING)], "pd_draft_id", {"unique": True}),
            ([("project_id", ASCENDING), ("updated_at", DESCENDING)], "pd_project_updated", {}),
            ([("project_id", ASCENDING), ("status", ASCENDING)], "pd_project_status", {}),
        ],
    }

    # 1) RICONCILIA: per ogni indice atteso, se esiste un indice con la STESSA chiave ma NOME diverso → drop e ricrea col nome canonico
    for col, idx_list in expected.items():
        existing = _list_indexes(col)
        for keys, name, opts in idx_list:
            current = _find_by_keys(col, keys)
            if current is not None:
                existing_name = current.get("name")
                # Se esiste ma con nome diverso → drop e ricrea con nome canonico
                if existing_name != name:
                    _drop_index_by_name(col, existing_name)
                    try:
                        _create_index(col, keys, name=name, **opts)
                    except OperationFailure as e:
                        # Se ancora conflitto, riprova forzando drop per nome canonico e ricrea
                        if getattr(e, "code", None) in (85, ) or "IndexOptionsConflict" in str(e):
                            _drop_index_by_name(col, name)
                            _create_index(col, keys, name=name, **opts)
                        else:
                            raise
                # Se il nome è già corretto, non fare nulla
            else:
                # Non esiste un indice con questa key → crealo con nome canonico
                try:
                    _create_index(col, keys, name=name, **opts)
                except OperationFailure as e:
                    if getattr(e, "code", None) in (85, ) or "IndexOptionsConflict" in str(e):
                        # Se confligge per opzioni, droppa per nome e ricrea
                        _drop_index_by_name(col, name)
                        _create_index(col, keys, name=name, **opts)
                    else:
                        raise
                except Exception:
                    pass

    # Wildcard index for embedded drafts stored under projects.meta_extra.work_drafts
    try:
        db["projects"].create_index(
            [("meta_extra.work_drafts.$**", "wildcard")],
            name="p_work_drafts_wildcard"
        )
    except Exception:
        pass

    # 2) Indici testuali (riconcilio anche se il nome è lo stesso ma le opzioni differiscono)
    try:
        # workers text
        txt_name = "w_text"
        desired = {
            "weights": {"role": 10, "aliases": 8, "name": 3},
            "default_language": "italian",
        }
        # Se esiste con nome uguale ma opzioni diverse → drop e ricrea
        for idx in _list_indexes("workers"):
            if idx.get("name") == txt_name:
                if (idx.get("weights") != desired["weights"] or
                    idx.get("default_language") != desired["default_language"]):
                    _drop_index_by_name("workers", txt_name)
                break
        db["workers"].create_index(
            [("name", TEXT), ("role", TEXT), ("aliases", TEXT)],
            name=txt_name,
            default_language=desired["default_language"],
            weights=desired["weights"]
        )
    except Exception:
        pass

    try:
        # materials text
        txt_name = "m_text"
        desired = {
            "weights": {"aliases": 10, "name": 7, "category": 3, "subcategory": 3},
            "default_language": "italian",
        }
        for idx in _list_indexes("materials"):
            if idx.get("name") == txt_name:
                if (idx.get("weights") != desired["weights"] or
                    idx.get("default_language") != desired["default_language"]):
                    _drop_index_by_name("materials", txt_name)
                break
        db["materials"].create_index(
            [("name", TEXT), ("aliases", TEXT), ("category", TEXT), ("subcategory", TEXT)],
            name=txt_name,
            default_language=desired["default_language"],
            weights=desired["weights"]
        )
    except Exception:
        pass

    # --- TTL chat_sessions (scadenza 7 giorni) ---
    try:
        # NB: assicurati che i documenti abbiano un campo datetime coerente (e.g., 'createdAt' o 'ts')
        db["chat_sessions"].create_index(
            [("createdAt", 1)],  # in alternativa usa ("ts", 1) se il campo si chiama così
            expireAfterSeconds=7 * 24 * 3600,
            name="chat_sessions_ttl_7d"
        )
    except Exception:
        # Non rendere fatale l'assenza del campo o altri errori runtime
        pass

# Backward-compatible alias for app.py imports
def ensure_indexes_safely():
    return ensure_mongo_indexes()