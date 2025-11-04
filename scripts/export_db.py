"""
Script: export_db.py
Scopo: Esporta le collezioni MongoDB in JSON leggibili in data/db_seed/.
- Overwrite sicuro dei file JSON di output
- Funzioni riusabili per bootstrap automatico:
    * export_collections_to_json(collections=None, out_dir=OUT_DIR)
    * ensure_seed_files_from_db(required=(...), out_dir=OUT_DIR)
- Supporto MONGO_URI/DB_NAME via env
- CLI con opzioni:
    --all                 → esporta tutte le collezioni (eccetto chat_* / telemetry)
    --collections a,b,c   → esporta solo quelle indicate
    --out PATH            → cartella di destinazione (default: data/db_seed)
    --include-runtime     → include anche chat_* e telemetry
Esecuzione: python scripts/export_db.py
"""

import os
import json
import argparse
from typing import Iterable, Dict, Any, List

from mongoengine.connection import connect, get_db
from bson import json_util

# === CONFIG ===
DB_NAME      = os.environ.get("MONGO_DBNAME", "business_project")
MONGO_URI    = os.environ.get("MONGO_URI")  # se valorizzata, usata da connect()
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
OUT_DIR      = os.path.join(PROJECT_ROOT, "data", "db_seed")
os.makedirs(OUT_DIR, exist_ok=True)

# Collezioni consigliate da versionare
DEFAULT_INCLUDE = [
    "work_catalog",
    "workers",
    "pricelists",
    "materials",
    "projects",
    "project_drafts",
]

# Collezioni da saltare (runtime) di default
SKIP_PREFIX = ("chat_", "telemetry")

__all__ = ["export_collections_to_json", "ensure_seed_files_from_db"]


def _connect():
    if MONGO_URI:
        connect(DB_NAME, host=MONGO_URI)
    else:
        connect(DB_NAME)


def _list_collections(include_runtime: bool) -> List[str]:
    db = get_db()
    names = db.list_collection_names()
    if include_runtime:
        return names
    return [n for n in names if not any(n.startswith(p) for p in SKIP_PREFIX)]


def export_collections_to_json(collections: Iterable[str] | None = None,
                               out_dir: str = OUT_DIR,
                               include_runtime: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Esporta le collezioni in JSON (pretty, senza _id) nella cartella out_dir.
    - collections=None → esporta tutte (eccetto runtime se include_runtime=False)
    - ritorna mappa { coll: {exported: n, path: path} }
    """
    _connect()
    db = get_db()
    os.makedirs(out_dir, exist_ok=True)

    if collections is None:
        target = _list_collections(include_runtime=include_runtime)
    else:
        target = list(collections)

    result: Dict[str, Dict[str, Any]] = {}
    for coll_name in target:
        try:
            docs = list(db[coll_name].find({}, {"_id": 0}))
            out_path = os.path.join(out_dir, f"{coll_name}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(docs, f, ensure_ascii=False, indent=2, default=json_util.default)
            print(f"💾 Export {coll_name}: {len(docs)} → {out_path}")
            result[coll_name] = {"exported": len(docs), "path": out_path}
        except Exception as e:
            print(f"⚠️  Errore export '{coll_name}': {e}")
    return result


def ensure_seed_files_from_db(required: Iterable[str] = ("work_catalog","workers","pricelists","materials"),
                              out_dir: str = OUT_DIR,
                              include_runtime: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Se mancano uno o più JSON richiesti in out_dir, li esporta dal DB.
    Non modifica il DB.
    """
    os.makedirs(out_dir, exist_ok=True)
    missing: List[str] = []
    for name in required:
        path = os.path.join(out_dir, f"{name}.json")
        if not os.path.exists(path):
            missing.append(name)
    if not missing:
        print("✅ Tutti i JSON richiesti sono presenti.")
        return {}
    print(f"🧩 Mancano JSON: {missing} → export dal DB")
    return export_collections_to_json(missing, out_dir=out_dir, include_runtime=include_runtime)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export collezioni MongoDB in JSON (data/db_seed/)")
    p.add_argument("--all", action="store_true", help="Esporta tutte le collezioni (eccetto runtime)")
    p.add_argument("--collections", type=str, default="", help="Lista di collezioni separate da virgola")
    p.add_argument("--out", type=str, default=OUT_DIR, help="Cartella di destinazione (default: data/db_seed)")
    p.add_argument("--include-runtime", action="store_true", help="Includi anche chat_* e telemetry")
    return p.parse_args()


def main():
    print(f"📦 Export da DB '{DB_NAME}' → {OUT_DIR}")
    _connect()
    get_db()  # sanity

    args = _parse_args()

    if args.all and args.collections:
        print("⚠️  Ignoro --collections perché è stato passato anche --all")

    if args.all:
        collections = None  # tutte (rispettando include_runtime)
    elif args.collections:
        collections = [c.strip() for c in args.collections.split(",") if c.strip()]
    else:
        collections = DEFAULT_INCLUDE

    # esegue export
    res = export_collections_to_json(collections=collections,
                                     out_dir=args.out,
                                     include_runtime=args.include_runtime)
    print("\n✅ Esportazione completata.")
    if res:
        updated = ", ".join(sorted(res.keys()))
        print(f"   Collezioni aggiornate: {updated}")
    return res


if __name__ == "__main__":
    main()