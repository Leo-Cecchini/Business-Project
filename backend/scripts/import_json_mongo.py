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
# Normalization helpers
# -----------------------------
UNIT_MAP = {
    "mq": "m2", "m²": "m2",
    "mc": "m3", "m³": "m3",
    "l": "lt", "litri": "lt",
    "pezzi": "pz", "pezzo": "pz", "cart": "pz", "bomb": "pz"
}

def _as_bool(v):
    if isinstance(v, bool):
        return v
    s = str(v or "").strip().lower()
    return s in {"1", "true", "si", "sì", "yes", "y"}

def _as_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    s = s.replace(",", ".")  # decimali con virgola → punto
    import re as _re
    m = _re.search(r"(-?\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None

def _as_int(v):
    f = _as_float(v)
    return int(f) if f is not None else None

def _as_list_csv(v):
    if v is None:
        return []
    if isinstance(v, list):
        return sorted({str(x).strip() for x in v if str(x).strip()})
    parts = [p.strip() for p in str(v).split(",")]
    return sorted({p for p in parts if p})

def _norm_unit(u: str | None) -> str | None:
    if not u:
        return None
    u = str(u).strip().lower()
    return UNIT_MAP.get(u, u)

def _capName(name: str | None) -> str:
    if not name:
        return ""
    return " ".join(w.capitalize() for w in str(name).strip().split())


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

def upsert_workers(path: str) -> tuple[int, int, list[str]]:
    data = _load_json(path)
    if not isinstance(data, list):
        raise ValueError("workers.json deve contenere una lista di oggetti")

    created, updated = 0, 0
    errors: list[str] = []
    for i, r in enumerate(data, start=1):
        try:
            if not isinstance(r, dict):
                continue
            name = (r.get("name") or "").strip()
            role = (r.get("role") or "").strip()
            home_city = (r.get("home_city") or "").strip()
            if not name or not role:
                errors.append(f"row {i}: name/role mancanti")
                continue

            # id: usa id/ID/_id se presente, altrimenti chiave logica name|role|home_city
            raw_id = (r.get("id") or r.get("ID") or r.get("_id") or "").strip()
            _id = raw_id or f"{name}|{role}|{home_city}"

            payload = {
                "id": _id,
                "name": _capName(name),
                "role": role.strip(),
                "hourly_rate": _as_float(r.get("hourly_rate")),
                "available": _as_bool(r.get("available", True)),
                "home_city": _capName(home_city),
                "skills": _as_list_csv(r.get("skills")),
                "certifications": _as_list_csv(r.get("certifications")),
            }

            existing = WorkerDoc.objects(id=_id).first()
            if existing:
                existing.modify(**{k: v for k, v in payload.items() if k != "id"})
                updated += 1
            else:
                # prova match per chiave logica se ID differente
                clash = WorkerDoc.objects(name=payload["name"], role=payload["role"], home_city=payload["home_city"]).first()
                if clash:
                    clash.modify(**{k: v for k, v in payload.items() if k != "id"})
                    updated += 1
                else:
                    WorkerDoc(**payload).save()
                    created += 1
        except Exception as e:
            errors.append(f"row {i}: {e}")
    return created, updated, errors


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
            name = _capName(r.get("name"))
            unit = _norm_unit(r.get("unit"))
            if not name or not unit:
                errors.append(f"row {i}: name/unit mancanti")
                continue

            sku = (r.get("sku") or "").strip().upper() or None

            _id = str(r.get("id") or r.get("_id") or sku or f"{name}|{unit}")

            payload = {
                "id": _id,
                "name": name,
                "category": r.get("category"),
                "subcategory": r.get("subcategory"),
                "unit": unit,
                "unit_price_eur_2025": _as_float(r.get("unit_price_eur_2025") or r.get("price")),
                "supplier": r.get("supplier"),
                "vat_rate": _as_float(r.get("vat_rate")),
                "sku": sku,
                "stock_qty": _as_float(r.get("stock_qty")),
                "lead_time_days": _as_int(r.get("lead_time_days")),
                "notes": r.get("notes"),
            }

            existing = MaterialDoc.objects(id=_id).first()
            if not existing and sku:
                # rispetta l'unicità dello SKU (se già presente, aggiorna quel record)
                existing = MaterialDoc.objects(sku=sku).first()

            if existing:
                existing.modify(**{k: v for k, v in payload.items() if k != "id"})
                updated += 1
            else:
                MaterialDoc(**payload).save()
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
        w_new, w_upd, w_err = upsert_workers(w_path)
        print(f"[workers] {w_new} inseriti, {w_upd} aggiornati (file: {w_path})")
        if w_err:
            print(f"[workers] errori: {len(w_err)}")
            for e in w_err[:10]:
                print(" -", e)
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