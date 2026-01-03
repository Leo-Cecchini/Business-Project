import os
import sys
import time
import json
import glob
from datetime import datetime
from bson import ObjectId  # ✅ AGGIUNGI PER GESTIRE _id CUSTOM

# Setup path per import dal backend
backend_path = os.path.join(os.path.dirname(__file__), 'backend')
sys.path.insert(0, backend_path)


def wait_for_mongo(max_retries=30, retry_delay=2):
    """Aspetta che MongoDB sia pronto."""
    from mongoengine import connect
    from mongoengine.connection import get_db
    
    mongo_uri = os.environ.get("MONGODB_URI")  # ✅ Era MONGO_URI
    db_name = os.environ.get("MONGODB_DB", "business_project")
    
    print(f"🔍 Controllo connessione MongoDB ({db_name})...")
    
    for attempt in range(max_retries):
        try:
            if mongo_uri:
                connect(db_name, host=mongo_uri, alias='default')
            else:
                connect(db_name, alias='default')
            
            db = get_db()
            db.command("ping")
            
            print(f"✅ MongoDB connesso!")
            return True
            
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"⏳ MongoDB non pronto (tentativo {attempt + 1}/{max_retries}), riprovo...")
                time.sleep(retry_delay)
            else:
                print(f"❌ MongoDB non raggiungibile dopo {max_retries} tentativi: {e}")
                return False
    
    return False


def create_indexes():
    """Crea indici necessari sulle collezioni."""
    try:
        from mongoengine.connection import get_db
        db = get_db()
        
        print("\n📇 Creazione indici...")
        
        # Index unico su pricelists (region, city)
        db["pricelists"].create_index(
            [("region", 1), ("city", 1)],
            unique=True,
            name="uniq_region_city"
        )
        print("  ✅ Index su pricelists (region, city)")
        
        return True
        
    except Exception as e:
        print(f"⚠️  Errore creazione indici (non bloccante): {e}")
        return True


def load_json_files(seed_dir):
    """Carica tutti i file JSON dalla directory seed."""
    if not os.path.isdir(seed_dir):
        return {}
    
    json_files = sorted(glob.glob(os.path.join(seed_dir, "*.json")))
    
    collections_data = {}
    for filepath in json_files:
        collection_name = os.path.splitext(os.path.basename(filepath))[0]
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Supporta sia liste che oggetti con "items"
                if isinstance(data, dict) and "items" in data:
                    data = data["items"]
                
                if isinstance(data, list):
                    collections_data[collection_name] = data
                else:
                    print(f"⚠️  {os.path.basename(filepath)}: formato non valido (deve essere array)")
        
        except Exception as e:
            print(f"⚠️  Errore leggendo {os.path.basename(filepath)}: {e}")
    
    return collections_data


def get_document_key(collection_name, doc):
    """Ritorna la chiave univoca per il documento."""
    # Pricelists: (region, city)
    if collection_name == "pricelists":
        return {"region": doc.get("region"), "city": doc.get("city", "")}
    
    # Cataloghi/materiali: sku
    if collection_name in ("work_catalog", "materials"):
        return {"sku": doc.get("sku")}
    
    # Workers: id o (name, role, home_city)
    if collection_name == "workers":
        if doc.get("id"):
            return {"id": doc["id"]}
        return {
            "name": doc.get("name"),
            "role": doc.get("role"),
            "home_city": doc.get("home_city")
        }
    
    # Projects: id
    if collection_name in ("projects", "project_drafts"):
        if doc.get("id"):
            return {"id": doc["id"]}
    
    # Fallback: usa _id se presente
    if doc.get("_id"):
        return {"_id": doc["_id"]}
    if doc.get("id"):
        return {"id": doc["id"]}
    
    # Ultimo fallback: tutto il documento (rischioso ma necessario)
    return doc


def seed_collection(db, collection_name, documents, mode="merge"):
    """Inserisce/aggiorna documenti in una collezione."""
    collection = db[collection_name]
    inserted = updated = skipped = 0
    
    for doc in documents:
        if not isinstance(doc, dict):
            skipped += 1
            continue
        
        # ✅ GESTIONE _id CUSTOM (EXTENDED JSON o STRING)
        if "_id" in doc:
            if isinstance(doc["_id"], dict) and "$oid" in doc["_id"]:
                # Extended JSON: {"$oid": "6957aeaf57e6e5cae46b8af0"}
                try:
                    doc["_id"] = ObjectId(doc["_id"]["$oid"])
                except Exception as e:
                    print(f"  ⚠️  _id invalido: {doc['_id']}, skip: {e}")
                    skipped += 1
                    continue
            elif isinstance(doc["_id"], str):
                # String diretta: "6957aeaf57e6e5cae46b8af0"
                try:
                    doc["_id"] = ObjectId(doc["_id"])
                except Exception as e:
                    print(f"  ⚠️  _id invalido: {doc['_id']}, skip: {e}")
                    skipped += 1
                    continue
        
        # Usa _id come chiave se presente, altrimenti usa get_document_key
        if "_id" in doc:
            key = {"_id": doc["_id"]}
        else:
            key = get_document_key(collection_name, doc)
        
        existing = collection.find_one(key)
        
        if not existing:
            # Inserimento
            collection.insert_one(doc)
            inserted += 1
        else:
            if mode == "merge":
                # Aggiorna solo campi mancanti
                update_fields = {}
                for k, v in doc.items():
                    if k not in existing or existing.get(k) is None:
                        update_fields[k] = v
                
                if update_fields:
                    collection.update_one(key, {"$set": update_fields})
                    updated += 1
                else:
                    skipped += 1
            elif mode == "replace":
                # Sovrascrivi tutto
                collection.update_one(key, {"$set": doc})
                updated += 1
            else:  # skip
                skipped += 1
    
    return {"inserted": inserted, "updated": updated, "skipped": skipped}


def run_seed():
    """Esegue seed del database se necessario."""
    try:
        from mongoengine.connection import get_db
        db = get_db()
        
        print("\n" + "="*60)
        print("🌱 SEED DATABASE")
        print("="*60)
        
        # Collezioni richieste
        required_collections = [
            "work_catalog",
            "workers",
            "materials",
            "pricelists",
            "projects"
        ]
        
        # Path seed directory
        seed_dir = os.path.join(os.path.dirname(__file__), "seed")
        print(f"📂 Seed directory: {seed_dir}")
        
        # Verifica directory
        if not os.path.isdir(seed_dir):
            print(f"⚠️  Directory seed non trovata: {seed_dir}")
            print("   Creo directory vuota...")
            os.makedirs(seed_dir, exist_ok=True)
            print("   ⚠️  ATTENZIONE: Metti i file JSON in project/seed/")
            return True
        
        # Verifica JSON
        json_files = glob.glob(os.path.join(seed_dir, "*.json"))
        if not json_files:
            print(f"⚠️  Nessun file JSON trovato in {seed_dir}")
            return True
        
        print(f"📄 Trovati {len(json_files)} file JSON")
        
        # Controlla se serve seed
        needs_seed = False
        for coll_name in required_collections:
            try:
                count = db[coll_name].count_documents({})
                if count == 0:
                    needs_seed = True
                    break
            except Exception:
                needs_seed = True
                break
        
        if not needs_seed:
            print("✅ Database già popolato, nessun seed necessario")
            return True
        
        # Carica JSON
        collections_data = load_json_files(seed_dir)
        
        if not collections_data:
            print("⚠️  Nessun dato da caricare")
            return True
        
        # Seed mode
        seed_mode = os.environ.get("SEED_MODE", "merge").lower()
        
        # Esegui seed
        print(f"\n💾 Modalità seed: {seed_mode}")
        results = {}
        
        for coll_name, documents in collections_data.items():
            stats = seed_collection(db, coll_name, documents, mode=seed_mode)
            results[coll_name] = stats
            
            print(f"  • {coll_name}: +{stats['inserted']} ins, "
                  f"~{stats['updated']} upd, ⭐ {stats['skipped']} skip")
        
        print("\n📊 Riepilogo seed completato")
        return True
        
    except Exception as e:
        print(f"❌ Errore durante seed: {e}")
        import traceback
        traceback.print_exc()
        return False


def auto_generate_pricelists():
    """Genera pricelists da materials se necessario."""
    
    if os.environ.get("AUTO_GENERATE_PRICELISTS", "1") != "1":
        print("ℹ️  AUTO_GENERATE_PRICELISTS=0, skip")
        return True
    
    try:
        from mongoengine.connection import get_db
        db = get_db()
        
        materials_count = db["materials"].count_documents({})
        pricelists_count = db["pricelists"].count_documents({})
        
        if materials_count > 0 and pricelists_count == 0:
            print("\n" + "="*60)
            print("💰 AUTO-GENERATE PRICELISTS DA MATERIALS")
            print("="*60)
            
            # Moltiplicatori regionali
            regional_multipliers = {
                "Lombardia": 1.03, "Lazio": 1.00, "Veneto": 0.99,
                "Emilia-Romagna": 0.99, "Piemonte": 0.98, "Toscana": 0.99,
                "Campania": 0.96, "Puglia": 0.95, "Sicilia": 0.95,
                "Calabria": 0.94
            }
            
            default_factors = {"historic_center": 1.05, "remote": 1.08}
            
            # Carica materials
            materials = list(db["materials"].find({}, {"_id": 0, "sku": 1, "unit_price_eur_2025": 1}))
            sku_prices = {
                m["sku"]: float(m.get("unit_price_eur_2025") or 0.0)
                for m in materials
                if m.get("sku")
            }
            
            added = 0
            now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
            
            # Genera pricelists per ogni regione
            for region, multiplier in regional_multipliers.items():
                materials_map = {
                    sku: round(price * multiplier, 2)
                    for sku, price in sku_prices.items()
                }
                
                pricelist = {
                    "region": region,
                    "city": "",
                    "created_at": now,
                    "updated_at": now,
                    "factors": default_factors.copy(),
                    "materials": materials_map,
                    "wages": {}
                }
                
                db["pricelists"].insert_one(pricelist)
                added += 1
            
            print(f"✅ Pricelists generati: {added} regioni")
            return True
            
        elif pricelists_count > 0:
            print(f"✅ Pricelists già presenti ({pricelists_count} documenti)")
            return True
        else:
            print("ℹ️  Nessun material presente, skip auto-generate pricelists")
            return True
            
    except Exception as e:
        print(f"⚠️  Errore generazione pricelists (non bloccante): {e}")
        import traceback
        traceback.print_exc()
        return True


def warm_up_collections():
    """Esegue count su collezioni principali per warm-up."""
    try:
        from mongoengine.connection import get_db
        db = get_db()
        
        print("\n🔥 Warm-up collezioni...")
        
        collections = ["materials", "projects", "workers", "pricelists", "work_catalog"]
        
        for coll in collections:
            try:
                count = db[coll].count_documents({})
                print(f"  • {coll}: {count} docs")
            except Exception as e:
                print(f"  ⚠️  {coll}: errore ({e})")
        
        return True
        
    except Exception as e:
        print(f"⚠️  Errore warm-up (non bloccante): {e}")
        return True


def main():
    """Sequenza completa di inizializzazione."""
    print("\n" + "="*60)
    print("🚀 INIZIALIZZAZIONE DATABASE")
    print("="*60)
    
    # Check se auto-seed è abilitato
    auto_seed = os.environ.get("AUTO_SEED", "1") == "1"
    
    if not auto_seed:
        print("ℹ️  AUTO_SEED=0, skip inizializzazione completa")
        print("   Solo verifica connessione MongoDB...")
        if wait_for_mongo():
            print("✅ MongoDB OK, avvio Flask")
            return True
        else:
            return False
    
    # === SEQUENZA COMPLETA ===
    
    # 1. Wait MongoDB
    if not wait_for_mongo():
        print("❌ Impossibile connettersi a MongoDB")
        return False
    
    # 2. Create Indexes
    create_indexes()
    
    # 3. Seed Database (se necessario)
    if not run_seed():
        print("⚠️  Seed fallito, ma continuo...")
    
    # 4. Auto-Generate Pricelists (se necessario)
    auto_generate_pricelists()
    
    # 5. Warm-up Collections
    warm_up_collections()
    
    print("\n" + "="*60)
    print("✅ INIZIALIZZAZIONE COMPLETATA")
    print("="*60 + "\n")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)