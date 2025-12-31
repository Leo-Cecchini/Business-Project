# scripts/normalize_and_load.py
import os, json, re
from mongoengine import connect
from models_mongo.worker import WorkerDoc
from models_mongo.material import MaterialDoc

WORKERS_PATH = os.getenv("WORKERS_JSON", "Workers.json")
MATERIALS_PATH = os.getenv("MATERIALS_JSON", "Materials.json")

URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DB  = os.getenv("MONGODB_DB", "business_project")
connect(db=DB, host=URI, uuidRepresentation="standard")

def to_bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in {"1","true","si","sì","yes","y"}

def to_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    # keep digits, comma, dot, minus
    s = re.sub(r"[^0-9,.-]+", "", s)
    # if both comma and dot exist, assume comma is thousands separator
    if "," in s and "." in s:
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        # last resort: extract first number pattern
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else None

# --- Unit normalization utilities ---

def normalize_unit(u):
    """
    Normalizza le unità verso l'insieme ammesso: {'kg','m2','m3','pz','lt'}.
    Gestisce sinonimi, spazi, maiuscole, simboli (m²/m³), abbreviazioni.
    Ritorna None se non mappabile.
    """
    if not u:
        return None
    s = str(u).strip().lower()

    # rimuovi prefissi/simboli comuni
    s = s.replace("€/", "").replace("eur/", "").strip()
    s = s.replace(" al ", "/").replace(" a ", "/")  # es. "al pezzo" → "/ pezzo"
    s = s.replace(".", "").replace(",", "").strip()

    # mappa unicode m²/m³
    s = s.replace("m²", "m2").replace("m³", "m3")

    direct = {
        "kg": "kg",
        "kilogrammo": "kg",
        "kilogrammi": "kg",
        "chilogrammo": "kg",
        "chilogrammi": "kg",
        "m": "m",               
        "metro": "m",           
        "metri": "m",  
        "mq": "m2",
        "m2": "m2",
        "mc": "m3",
        "m3": "m3",
        "pz": "pz",
        "pz.": "pz",
        "pezzo": "pz",
        "pezzi": "pz",
        "nr": "pz",
        "n": "pz",
        "n.": "pz",
        "l": "lt",
        "lt": "lt",
        "litro": "lt",
        "litri": "lt",
        "cart": "pz",           
        "cartuccia": "pz",      
        "bomb": "pz",           
        "bomboletta": "pz",
    }
    if s in direct:
        return direct[s]

    # pattern frequenti
    if "/kg" in s or " kg" in s:
        return "kg"
    if "/mq" in s or "/m2" in s or " m2" in s or " mq" in s:
        return "m2"
    if "/mc" in s or "/m3" in s or " m3" in s or " mc" in s:
        return "m3"
    if "pezzo" in s or "pezzi" in s:
        return "pz"
    if "/pz" in s or " pz" in s:
        return "pz"
    if "/l" in s or "/lt" in s or " lt" in s or " litro" in s or " litri" in s:
        return "lt"

    return None


def coerce_unit_or_raise(u, name_for_err=""):
    out = normalize_unit(u)
    if out is None:
        raise ValueError(f"Unità non supportata o non riconosciuta: {u!r} (materiale: {name_for_err})")
    return out

def parse_hourly_rate(v):
    """
    Estrai un float da stringhe tipo '28.0JS:28' o '€28/h'.
    Ritorna None se non si trova nulla.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v)
    m = re.findall(r"[0-9]+(?:[.,][0-9]+)?", s)
    if not m:
        return None
    # prendi il primo numero, usa '.' come separatore decimale
    num = m[0].replace(",", ".")
    try:
        return float(num)
    except Exception:
        return None

def split_list(s):
    """
    Trasforma 'a,b; c|d' -> ['a','b','c','d'] con dedup e trim.
    Gestisce None e già-liste.
    """
    if s is None:
        return []
    if isinstance(s, list):
        items = [str(x).strip() for x in s if str(x).strip()]
        return sorted(list(set(items)))
    parts = re.split(r"[;,|]", str(s))
    items = [p.strip() for p in parts if p.strip()]
    return sorted(list(set(items)))

def load_json_array(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
        return data["data"]
    assert isinstance(data, list), f"{path} deve essere un array JSON"
    return data

def upsert_workers():
    data = load_json_array(WORKERS_PATH)
    # svuota per pulizia (se vuoi append, rimuovi la drop)
    # WorkerDoc.drop_collection()
    n_ok = 0
    for raw in data:
        doc = dict(raw)
        # id: prendi 'ID' o 'id' o '_id', e stringa
        _id = str(doc.pop("_id", doc.pop("ID", doc.pop("id", "")))).strip()
        if not _id:
            print(f"[SKIP][workers] id mancante -> {raw}")
            continue
        # campi puliti
        hourly = parse_hourly_rate(doc.get("hourly_rate"))
        available = to_bool(doc.get("available"))
        skills = split_list(doc.get("skills"))
        certs = split_list(doc.get("certifications"))

        # costruisci payload per WorkerDoc
        payload = {
            "id": _id,
            "name": doc.get("name"),
            "role": doc.get("role"),
            "hourly_rate": hourly,
            "available": available,
            "home_city": doc.get("home_city"),
            "skills": skills,
            "certifications": certs,
        }

        # salva idempotente
        existing = WorkerDoc.objects(id=_id).first()
        if existing:
            existing.modify(**{k: v for k, v in payload.items() if k != "id"})
        else:
            WorkerDoc(**payload).save()
        n_ok += 1
    return n_ok

def upsert_materials():
    data = load_json_array(MATERIALS_PATH)
    # MaterialDoc.drop_collection()
    n_ok = 0
    for raw in data:
        doc = dict(raw)
        _id = str(doc.pop("_id", doc.pop("id", ""))).strip()

        # normalizzazioni leggere
        sku = doc.get("sku")
        name = doc.get("name")
        if sku: sku = str(sku).strip().upper()
        if name: name = str(name).strip().title()

        if not _id:
            _id = sku or (name or "")
        _id = str(_id).strip()
        if not _id or not sku or not name:
            print(f"[SKIP][materials] id/sku/name mancanti -> {raw}")
            continue

        unit_price = to_float(doc.get("unit_price_eur_2025"))
        vat = to_float(doc.get("vat_rate"))
        stock_qty = to_float(doc.get("stock_qty"))
        lead_days = int(to_float(doc.get("lead_time_days")) or 0)

        # tipi coerenti
        try:
            payload = {
                "id": _id,
                "name": name,
                "category": doc.get("category"),
                "subcategory": doc.get("subcategory"),
                "unit": coerce_unit_or_raise(doc.get("unit"), name_for_err=name),
                "unit_price_eur_2025": unit_price,
                "supplier": doc.get("supplier"),
                "vat_rate": vat,
                "sku": sku,
                "stock_qty": stock_qty,
                "lead_time_days": lead_days,
                "notes": doc.get("notes"),
            }
            # upsert robusto: prova per id, poi per sku (indice unico)
            existing = MaterialDoc.objects(id=_id).first()
            if not existing:
                existing = MaterialDoc.objects(sku=sku).first()

            if existing:
                existing.modify(**{k: v for k, v in payload.items() if k != "id"})
                print(f"[materials][UPDATE] sku={sku} id={existing.id}")
            else:
                MaterialDoc(**payload).save()
                print(f"[materials][INSERT] sku={sku} id={_id}")
            n_ok += 1
        except Exception as e:
            print(f"[SKIP] {name or _id}: {e}")
    return n_ok

if __name__ == "__main__":
    w = upsert_workers()
    m = upsert_materials()
    print(f"Workers inseriti: {w}")
    print(f"Materials inseriti: {m}")