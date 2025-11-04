"""
Script: scripts/seed_db.py
Scopo: Popola il database MongoDB da tutti i JSON in data/db_seed/.
- Modalità non distruttiva di default (merge): crea i record mancanti e completa solo i campi assenti.
- Supporta anche 'skip' (non tocca nulla se il doc esiste) e 'replace' (sovrascrive – sconsigliato).
- Se EXPORT_MISSING_SEED=1: se mancano JSON richiesti, li esporta dal DB prima del seed.
Esecuzione CLI:    python scripts/seed_db.py
Bootstrap in app:  from scripts.seed_db import seed_if_needed
"""

import os
import json
import glob
from typing import Dict, Any, Iterable

from mongoengine.connection import connect, get_db
from pymongo.collection import Collection

# === CONFIG ===
DB_NAME   = os.environ.get("MONGO_DBNAME", "business_project")
MONGO_URI = os.environ.get("MONGO_URI")  # se definita, usata da connect()
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
SEED_DIR  = os.path.normpath(os.path.join(PROJECT_ROOT, "data", "db_seed"))

# Modalità: merge (default) | skip | replace
SEED_MODE = os.environ.get("SEED_MODE", "merge").strip().lower()
EXPORT_MISSING_SEED = os.environ.get("EXPORT_MISSING_SEED", "1") == "1"

# Collezioni da NON seedare (dati runtime)
SKIP_PREFIX = ("chat_", "telemetry")

# Collezioni richieste minime per considerare il DB "popolato"
REQUIRED_DEFAULT = ("work_catalog", "workers", "pricelists", "materials")


# ----------------------------
# Utilità
# ----------------------------

def _load_json_files(seed_dir: str) -> Iterable[tuple[str, list]]:
  """Carica tutti i *.json da seed_dir.
  Supporta sia formato lista che {"items":[...]}.
  """
  if not os.path.isdir(seed_dir):
    return []
  files = sorted(glob.glob(os.path.join(seed_dir, "*.json")))
  out = []
  for fp in files:
    name = os.path.splitext(os.path.basename(fp))[0]  # es: work_catalog.json -> work_catalog
    try:
      with open(fp, "r", encoding="utf-8") as f:
        data = json.load(f) or []
        if isinstance(data, dict) and isinstance(data.get("items"), list):
          data = data["items"]
        if not isinstance(data, list):
          print(f"⚠️  {os.path.basename(fp)} deve contenere una lista o un oggetto con 'items'")
          continue
        out.append((name, data))
    except Exception as e:
      print(f"⚠️  Errore leggere {fp}: {e}")
  return out


def _merge_missing_fields(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
  """Ritorna i soli campi mancanti o None da aggiungere a existing."""
  add = {}
  for k, v in incoming.items():
    if k not in existing or existing.get(k) is None:
      add[k] = v
  return add


def _key_for(coll_name: str, doc: Dict[str, Any]) -> Dict[str, Any]:
  """Chiave univoca per individuare il documento da upsertare."""
  # Pricelists: (region, city)
  if coll_name == "pricelists":
    return {"region": doc.get("region"), "city": (doc.get("city") or "")}
  # Cataloghi/materiali: code
  if coll_name in ("work_catalog", "materials"):
    return {"code": doc.get("code")}
  # Workers: id se c'è, altrimenti (name, role, home_city)
  if coll_name == "workers":
    if doc.get("id"):
      return {"id": doc["id"]}
    return {"name": doc.get("name"), "role": doc.get("role"), "home_city": doc.get("home_city")}
  # Projects / drafts: id
  if coll_name in ("projects", "project_drafts"):
    if doc.get("id"):
      return {"id": doc["id"]}
  # Fallback: usa id/_id se presenti
  if doc.get("id"):
    return {"id": doc["id"]}
  if doc.get("_id"):
    return {"_id": doc["_id"]}
  # Estremo: ritorna l'intero doc (rischio duplicati minimi)
  return doc


def _connect():
  if MONGO_URI:
    connect(DB_NAME, host=MONGO_URI)
  else:
    connect(DB_NAME)


# ----------------------------
# Core di seeding
# ----------------------------

def seed_directory(seed_dir: str = SEED_DIR, collections: Iterable[str] | None = None) -> Dict[str, Dict[str, int | str]]:
  """
  Esegue seed non distruttivo (merge) di tutte le collezioni per cui esiste un JSON in seed_dir.
  Parametri:
    - seed_dir: cartella dei json
    - collections: se passato, limita a questi nomi (altrimenti tutte quelle trovate)
  Ritorna: mappa coll_name -> {inserted, updated, skipped, mode}
  """
  _connect()
  db = get_db()
  results: Dict[str, Dict[str, int | str]] = {}

  rows = _load_json_files(seed_dir)
  if not rows:
    print(f"⚠️  Nessun JSON trovato in {seed_dir}")
    return results

  for coll_name, docs in rows:
    if collections and coll_name not in collections:
      continue
    if any(coll_name.startswith(prefix) for prefix in SKIP_PREFIX):
      print(f"⏭️  Skip '{coll_name}' (runtime)")
      continue

    coll: Collection = db[coll_name]
    inserted = updated = skipped = 0

    # Se skip e collezione non vuota, non fare nulla
    if SEED_MODE == "skip" and coll.estimated_document_count() > 0:
      results[coll_name] = {"inserted": 0, "updated": 0, "skipped": len(docs), "mode": SEED_MODE}
      continue

    for doc in docs:
      if not isinstance(doc, dict):
        skipped += 1
        continue
      key = _key_for(coll_name, doc)
      existing = coll.find_one(key) or {}

      if not existing:
        # Inserimento
        if SEED_MODE in ("merge", "replace", "skip"):
          coll.update_one(key, {"$setOnInsert": doc}, upsert=True)
          inserted += 1
      else:
        if SEED_MODE == "replace":
          coll.update_one(key, {"$set": doc}, upsert=True)
          updated += 1
        elif SEED_MODE == "merge":
          add = _merge_missing_fields(existing, doc)
          if add:
            coll.update_one(key, {"$set": add})
            updated += 1
          else:
            skipped += 1
        else:  # skip
          skipped += 1

    results[coll_name] = {"inserted": inserted, "updated": updated, "skipped": skipped, "mode": SEED_MODE}
    print(f"✅ {coll_name}: +{inserted} ins, ~{updated} upd, ⏭️ {skipped} skip (mode={SEED_MODE})")

  return results


def seed_if_needed(collections: Iterable[str] = REQUIRED_DEFAULT, seed_dir: str = SEED_DIR):
  """
  Se UNA delle collezioni richieste è vuota o mancante, esegue un seed completo (non distruttivo).
  Ritorna il report come dict.
  """
  _connect()
  db = get_db()

  # Se richiesto, assicura che i JSON seed esistano (export dal DB se mancanti)
  if EXPORT_MISSING_SEED:
    try:
      from scripts.export_db import ensure_seed_files_from_db
      ensure_seed_files_from_db(required=collections, out_dir=SEED_DIR)
    except Exception as e:
      print(f"⚠️  EXPORT_MISSING_SEED attivo ma export skipped: {e}")

  needs: list[str] = []
  for name in collections:
    try:
      if db[name].count_documents({}) == 0:
        needs.append(name)
    except Exception:
      needs.append(name)

  if needs:
    print(f"🔄 DB bootstrap: mancano/sono vuote {needs} → seed_directory({seed_dir})")
    return seed_directory(seed_dir=seed_dir, collections=None)  # tutte le collezioni presenti nei JSON
  else:
    print("✅ DB già popolato, nessun seed necessario.")
    return {}


def main():
  """Esecuzione CLI: seed di tutte le collezioni presenti in data/db_seed/."""
  # Prima di seed, genera eventuali JSON mancanti
  if EXPORT_MISSING_SEED:
    try:
      from scripts.export_db import ensure_seed_files_from_db
      ensure_seed_files_from_db(required=REQUIRED_DEFAULT, out_dir=SEED_DIR)
    except Exception as e:
      print(f"⚠️  EXPORT_MISSING_SEED attivo ma export skipped: {e}")

  res = seed_directory(seed_dir=SEED_DIR, collections=None)
  return res


if __name__ == "__main__":
  out = main()
  # stampa compatta finale
  if out:
    print("\n📊 Riepilogo:")
    for k, v in out.items():
      print(f" - {k}: {v}")
  else:
    print("Nessuna collezione seedata.")