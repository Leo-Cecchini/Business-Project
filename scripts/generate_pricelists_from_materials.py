# scripts/generate_pricelists_from_materials.py
import os, json
from mongoengine.connection import get_db
import datetime
import copy

def _json_default(o):
    if isinstance(o, (datetime.datetime, datetime.date)):
        # ISO 8601 con 'Z' per UTC
        return o.isoformat().replace("+00:00", "Z") + ("Z" if o.tzinfo is None else "")
    return str(o)

def _sanitize_for_json(doc):
    """Ritorna una deep-copy del doc con tutte le date convertite a stringhe."""
    def _sanitize(v):
        if isinstance(v, dict):
            return {k: _sanitize(v2) for k, v2 in v.items()}
        if isinstance(v, list):
            return [_sanitize(x) for x in v]
        if isinstance(v, (datetime.datetime, datetime.date)):
            return _json_default(v)
        return v
    return _sanitize(copy.deepcopy(doc))

REGIONAL_MULTIPLIERS = {
    # moltiplicatori per MATERIALI (leggera variazione logistica)
    "Lombardia": 1.03, "Lazio": 1.00, "Veneto": 0.99, "Emilia-Romagna": 0.99,
    "Piemonte": 0.98, "Toscana": 0.99, "Campania": 0.96, "Puglia": 0.95,
    "Sicilia": 0.95, "Calabria": 0.94,
}

DEFAULT_FACTORS = {"historic_center": 1.05, "remote": 1.08}

def _now_http():
    return datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

def _load_existing_pricelists(db):
    cur = db["pricelists"].find({}, {"_id":0})
    return [doc for doc in cur]

def _pricelist_doc(region: str, materials_map: dict, wages: dict | None = None):
    return {
        "region": region,
        "city": "",
        "created_at": _now_http(),
        "updated_at": _now_http(),
        "factors": DEFAULT_FACTORS.copy(),
        "materials": materials_map,
        "wages": wages or {}
    }

def sync_pricelists_with_materials(save_json: bool = True, upsert_db: bool = True):
    """
    - Legge tutti i materiali da `materials`
    - Per ogni regione, unisce i prezzi già presenti (se esistono) con i materiali mancanti
      valorizzati da unit_price_eur_2025 * REGIONAL_MULTIPLIERS[regione]
    - Salva su data/db_seed/pricelists.json (se save_json=True)
    - Upsert su DB (se upsert_db=True)
    Ritorna un piccolo riepilogo (dict).
    """
    db = get_db()

    # 1) materiali base (sku -> prezzo)
    materials = list(db["materials"].find({}, {"_id": 0, "sku": 1, "unit_price_eur_2025": 1}))
    sku_prices = {
        m["sku"]: float(m.get("unit_price_eur_2025") or 0.0)
        for m in materials
        if m.get("sku")
    }

    # 2) leggi i pricelist esistenti per NON perdere wages/factors/override già inseriti
    existing = {(pl.get("region") or ""): pl for pl in _load_existing_pricelists(db)}

    regions = list(REGIONAL_MULTIPLIERS.keys())
    added, updated = 0, 0
    out_docs = []

    for reg in regions:
        mult = REGIONAL_MULTIPLIERS[reg]
        base_map = {sku: round(price * mult, 2) for sku, price in sku_prices.items()}

        if reg in existing:
            # mantieni tutto ciò che già c’è e integra i mancanti
            cur = existing[reg]
            merged_materials = dict(cur.get("materials") or {})
            for sku, v in base_map.items():
                if sku not in merged_materials:
                    merged_materials[sku] = v
            cur["materials"] = merged_materials
            cur["updated_at"] = _now_http()
            # assicurati di mantenere factors/wages esistenti
            cur.setdefault("factors", DEFAULT_FACTORS.copy())
            cur.setdefault("wages", {})
            cur.setdefault("city", "")
            out_docs.append(cur)
            updated += 1
        else:
            # nuovo doc completo
            out_docs.append(_pricelist_doc(reg, base_map))
            added += 1

    # 3) salva JSON su disco
    if save_json:
        out_dir = os.path.join("data", "db_seed")
        os.makedirs(out_dir, exist_ok=True)
        fp = os.path.join(out_dir, "pricelists.json")
        # ⚠️ sanitizza le date, poi dump
        out_docs_sanitized = [_sanitize_for_json(doc) for doc in out_docs]
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(out_docs_sanitized, f, ensure_ascii=False, indent=2, default=_json_default)

    # 4) upsert su DB
    if upsert_db:
        for doc in out_docs:
            db["pricelists"].update_one(
                {"region": doc["region"], "city": doc.get("city", "")},
                {"$set": doc},
                upsert=True,
            )

    return {"added": added, "updated": updated, "regions": len(out_docs)}