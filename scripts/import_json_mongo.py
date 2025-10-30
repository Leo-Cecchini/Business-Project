# scripts/import_json_mongo.py
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Ensure project root (and optional ./src) are on sys.path
_DEF_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DEF_SRC = os.path.join(_DEF_ROOT, "src")
for _p in (_DEF_ROOT, _DEF_SRC):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

# Make packages importable even if __init__.py is missing (namespace pkg won't work everywhere)
# Prefer having __init__.py in models_mongo/ and scripts/

try:
    from models_mongo.worker import WorkerDoc  # type: ignore
    from models_mongo.material import MaterialDoc  # type: ignore
except ModuleNotFoundError as e:
    # Give a clearer error with guidance
    raise ModuleNotFoundError(
        "Impossibile importare 'models_mongo'. Verifica che esista la cartella 'models_mongo' nella root del progetto, "
        "che contenga 'worker.py' e 'material.py', e che esista un file '__init__.py' dentro 'models_mongo/'.\n"
        f"Project root cercato: {_DEF_ROOT}\n"
        f"Contenuto root: {os.listdir(_DEF_ROOT) if os.path.isdir(_DEF_ROOT) else 'non trovato'}\n"
        "Suggerimenti: crea i pacchetti con 'touch models_mongo/__init__.py scripts/__init__.py' e rilancia."
    ) from e

import json
import argparse
from typing import List, Dict, Any

from db.mongo import init_mongo, ensure_mongo_indexes

# -----------------------------
# Utilities
# -----------------------------

def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_default(path_hint: str) -> str | None:
    """Try provided path; if missing, also try under ./data and with lowercased filename."""
    candidates = [
        path_hint,
        os.path.join("data", path_hint),
        os.path.join("data", path_hint.lower()),
        path_hint.lower(),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None


# -----------------------------
# Workers
# -----------------------------

def upsert_workers(path: str) -> tuple[int, int]:
    data = _load_json(path)
    if not isinstance(data, list):
        raise ValueError("workers.json deve contenere una lista di oggetti")

    created, updated = 0, 0
    for r in data:
        if not isinstance(r, dict):
            continue
        _id = str(r.get("id") or r.get("_id") or r.get("code") or r.get("name") or "").strip()
        if not _id:
            # salta record senza id identificabile
            continue
        exists = WorkerDoc.objects(id=_id).first() is not None
        WorkerDoc.objects(id=_id).update_one(
            set__name=r.get("name"),
            set__role=r.get("role"),
            set__hourly_rate=r.get("hourly_rate"),
            set__available=bool(r.get("available", True)),
            set__home_city=r.get("home_city"),
            set__skills=r.get("skills") or [],
            set__certifications=r.get("certifications") or [],
            upsert=True,
        )
        if exists:
            updated += 1
        else:
            created += 1
    return created, updated


# -----------------------------
# Materials
# -----------------------------

def upsert_materials(path: str) -> tuple[int, int, List[str]]:
    data = _load_json(path)
    if not isinstance(data, list):
        raise ValueError("materials.json deve contenere una lista di oggetti")

    created, updated = 0, 0
    errors: List[str] = []
    for i, r in enumerate(data, start=1):
        try:
            if not isinstance(r, dict):
                continue
            name = (r.get("name") or "").strip()
            unit = (r.get("unit") or "").strip()
            if not name or not unit:
                errors.append(f"row {i}: name/unit mancanti")
                continue
            _id = f"{name}|{unit}"
            exists = MaterialDoc.objects(id=_id).first() is not None
            MaterialDoc.objects(id=_id).update_one(
                set__name=name,
                set__category=r.get("category"),
                set__subcategory=r.get("subcategory"),
                set__unit=unit,
                set__unit_price_eur_2025=r.get("unit_price_eur_2025") or r.get("price"),
                set__vat_rate=r.get("vat_rate"),
                set__supplier=r.get("supplier"),
                set__sku=r.get("sku"),
                set__stock_qty=r.get("stock_qty"),
                set__lead_time_days=r.get("lead_time_days"),
                set__notes=r.get("notes"),
                upsert=True,
            )
            if exists:
                updated += 1
            else:
                created += 1
        except Exception as e:
            errors.append(f"row {i}: {e}")
    return created, updated, errors


# -----------------------------
# Main
# -----------------------------

def main():
    parser = argparse.ArgumentParser(description="Import JSON → Mongo (workers, materials)")
    parser.add_argument("--workers", dest="workers", default="workers.json", help="Percorso workers.json (default: workers.json o data/workers.json)")
    parser.add_argument("--materials", dest="materials", default="materials.json", help="Percorso materials.json (default: materials.json o data/materials.json)")
    args = parser.parse_args()

    init_mongo()
    try:
        ensure_mongo_indexes()
    except Exception:
        # indici non sono bloccanti
        pass

    w_path = _resolve_default(args.workers)
    m_path = _resolve_default(args.materials)

    if w_path:
        w_new, w_upd = upsert_workers(w_path)
        print(f"[workers] {w_new} inseriti, {w_upd} aggiornati (file: {w_path})")
    else:
        print("[workers] nessun file trovato (cercati workers.json e data/workers.json)")

    if m_path:
        m_new, m_upd, m_err = upsert_materials(m_path)
        print(f"[materials] {m_new} inseriti, {m_upd} aggiornati (file: {m_path})")
        if m_err:
            print(f"[materials] errori: {len(m_err)}")
            for e in m_err[:10]:  # limita output
                print(" -", e)
    else:
        print("[materials] nessun file trovato (cercati materials.json e data/materials.json)")

    print("✅ Import JSON → Mongo completato.")


if __name__ == "__main__":
    main()