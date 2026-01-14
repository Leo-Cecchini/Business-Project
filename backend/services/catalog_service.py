# services/catalog_service.py
from datetime import datetime
from typing import List, Dict, Any, Optional
from mongoengine.connection import get_db

class CatalogService:
    """
    Gestisce l'accesso al Catalogo Lavorazioni e ai Listini.
    """

    # --- WORK CATALOG (Lettura/Scrittura puntuale) ---

    @staticmethod
    def list_items() -> List[Dict]:
        db = get_db()
        return list(db["work_catalog"].find({}, {"_id": 0}))

    @staticmethod
    def get_item_by_code(code: str) -> Optional[Dict]:
        db = get_db()
        return db["work_catalog"].find_one({"code": {"$regex": f"^{code}$", "$options": "i"}}, {"_id": 0})

    @staticmethod
    def search_items(q: str, role: str, unit: str, limit: int = 50) -> Dict[str, Any]:
        """Ricerca avanzata nel catalogo."""
        db = get_db()
        filt = {}
        and_terms = []

        if q:
            # Cerca in codice, nome o sinonimi
            and_terms.append({"$or": [
                {"code": {"$regex": q, "$options": "i"}},
                {"name": {"$regex": q, "$options": "i"}},
                {"synonyms": {"$elemMatch": {"$regex": q, "$options": "i"}}},
            ]})

        if role:
            # Cerca nel ruolo primario o nei consentiti
            and_terms.append({"$or": [
                {"primary_role": {"$regex": f"^{role}$", "$options": "i"}},
                {"roles_allowed": {"$elemMatch": {"$regex": f"^{role}$", "$options": "i"}}},
            ]})

        if unit:
            and_terms.append({"unit": {"$regex": f"^{unit}$", "$options": "i"}})

        if and_terms:
            filt = {"$and": and_terms}

        cursor = db["work_catalog"].find(filt, {"_id": 0}).sort("name", 1).limit(limit)
        items = list(cursor)
        return {"total": len(items), "items": items}

    @staticmethod
    def get_crew_requirements(code: str) -> Optional[Dict]:
        """Recupera solo i dati sulla squadra per un lavoro."""
        db = get_db()
        proj = {"_id": 0, "code": 1, "min_crew": 1, "max_crew": 1, "crew_roles": 1, "pairing_rule": 1}
        return db["work_catalog"].find_one({"code": {"$regex": f"^{code}$", "$options": "i"}}, proj)

    @staticmethod
    def upsert_item(data: Dict[str, Any]) -> str:
        """Crea o aggiorna una singola voce di catalogo."""
        db = get_db()
        code = (data.get("code") or "").strip().upper()
        if not code:
            raise ValueError("Code is required")

        payload = {
            "name": data.get("name"),
            "synonyms": data.get("synonyms") or [],
            "primary_role": data.get("primary_role"),
            "roles_allowed": data.get("roles_allowed") or [],
            "unit": data.get("unit"),
            "productivity_per_worker_per_hour": float(data.get("productivity_per_worker_per_hour") or 0) or 1.0,
            "min_crew": int(data.get("min_crew") or 1),
            "max_crew": int(data.get("max_crew") or 1),
            "prerequisites": data.get("prerequisites") or [],
            "notes": data.get("notes") or "",
            "crew_roles": data.get("crew_roles") or {},
            "pairing_rule": data.get("pairing_rule") or ""
        }

        db["work_catalog"].update_one(
            {"code": code},
            {"$set": payload, "$setOnInsert": {"code": code}},
            upsert=True
        )
        return code

    # --- PRICELISTS (Listini) ---

    @staticmethod
    def get_pricelist(region: str, city: str) -> Optional[Dict]:
        """Trova il listino più specifico (Città > Regione > Default)."""
        db = get_db()
        doc = None
        # 1. Match esatto (Regione + Città)
        if region and city:
            doc = db["pricelists"].find_one({
                "region": {"$regex": f"^{region}$", "$options": "i"},
                "city": {"$regex": f"^{city}$", "$options": "i"}
            }, {"_id": 0})
        
        # 2. Solo Regione (se non trovato città specifica)
        if not doc and region:
            doc = db["pricelists"].find_one({
                "region": {"$regex": f"^{region}$", "$options": "i"},
                "$or": [{"city": {"$exists": False}}, {"city": {"$in": [None, ""]}}]
            }, {"_id": 0})
            
        # 3. Solo Città (caso raro)
        if not doc and city:
            doc = db["pricelists"].find_one({
                "city": {"$regex": f"^{city}$", "$options": "i"}
            }, {"_id": 0})
            
        return doc

    @staticmethod
    def upsert_pricelist_codes(region: str, city: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Aggiorna puntualmente prezzi nel listino."""
        db = get_db()
        # IMPORTANT:
        # - city == "" means "regional pricelist" (not city-specific)
        # - if we filter only by region we might match and update a *city* pricelist by mistake
        #   causing inconsistent prices across territories.
        filt: Dict[str, Any] = {}
        if region:
            filt["region"] = {"$regex": f"^{region}$", "$options": "i"}

        if city is None:
            city = ""

        if city != "":
            # city-specific pricelist
            filt["city"] = {"$regex": f"^{city}$", "$options": "i"}
        elif region:
            # region-level pricelist (city empty/missing)
            filt["$or"] = [{"city": {"$exists": False}}, {"city": {"$in": [None, ""]}}]

        # Fallback se non c'è regione ma c'è città
        if not filt and city:
            filt["city"] = {"$regex": f"^{city}$", "$options": "i"}

        if not filt:
            raise ValueError("Region or City required")

        update = {"$set": {}}
        for field in ["materials", "wages", "factors"]:
            for k, v in (data.get(field) or {}).items():
                try: 
                    update["$set"][f"{field}.{k}"] = float(v)
                except: 
                    pass
        
        if not update["$set"]: 
            return {"modified": 0}

        update["$set"]["updated_at"] = datetime.utcnow()
        
        # Se stiamo creando un nuovo documento (upsert), impostiamo i campi base
        set_on_insert = {"created_at": datetime.utcnow()}
        if region:
            set_on_insert["region"] = region
        # Persist "" for regional lists to make lookups deterministic
        if city is not None:
            set_on_insert["city"] = city
        update["$setOnInsert"] = set_on_insert

        res = db["pricelists"].update_one(filt, update, upsert=True)

        # Invalidate cached pricelist lookups (estimate.py uses @lru_cache)
        try:
            from utils.estimate import _get_pricelist  # local import to avoid circular deps at import time
            _get_pricelist.cache_clear()
        except Exception:
            pass

        return {"matched": res.matched_count, "modified": res.modified_count, "upserted": bool(res.upserted_id)}