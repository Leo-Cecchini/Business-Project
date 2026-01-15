# services/material_service.py
import re
from typing import Optional, List, Dict, Any
from mongoengine.queryset.visitor import Q
from models_mongo.material import MaterialDoc
from utils.material_synonyms import SYNONYM_TO_ROOT

class MaterialService:
    UNIT_MAP = {"mq":"m2","m²":"m2","mc":"m3","m³":"m3","l":"lt","litri":"lt","pezzi":"pz","pezzo":"pz","cart":"pz","bomb":"pz"}

    @staticmethod
    def _normalize_tokens(text: str) -> List[List[str]]:
        """Converte il testo in gruppi di sinonimi (logica estratta da chat.py)."""
        if not text: return []
        cleaned = re.sub(r"(?i)\b(prezzo|quanto|costa|al|allo|alla|per|unit(a|à)|sku[:\s]*[A-Z0-9\-]+)\b", " ", text)
        raw_tokens = re.findall(r"[A-Za-z]+|\d+(?:[.,]\d+)?[A-Za-z]?", cleaned.lower())
        raw_tokens = [t.strip().replace(",", ".") for t in raw_tokens if len(t.strip()) >= 2]

        groups = []
        seen = set()
        for tok in raw_tokens:
            variants = {tok}
            m = re.match(r"^(\d+(?:\.\d+)?)([a-z])$", tok)
            if m: variants.add(f"{m.group(1)} {m.group(2)}")
            root = SYNONYM_TO_ROOT.get(tok)
            if root:
                syns = {v for v, r in SYNONYM_TO_ROOT.items() if r == root}
                variants |= syns
            norm = sorted({" ".join(v.split()) for v in variants})
            key = tuple(norm)
            if key in seen: continue
            seen.add(key)
            groups.append(norm)
        return groups

    @staticmethod
    def _format_answer(mdoc: MaterialDoc) -> Dict[str, Any]:
        price = mdoc.unit_price_eur_2025 if mdoc.unit_price_eur_2025 is not None else 0.0
        return {
            "INTENT_DB": "MATERIAL_PRICE",
            "answer": (
                f"{mdoc.name}: {price:.2f} €/ {mdoc.unit} (SKU {mdoc.sku}). "
                f"Stock: {int(mdoc.stock_qty or 0)}, Lead time: {int(mdoc.lead_time_days or 0)} gg, IVA: {int(mdoc.vat_rate or 0)}%."
            ),
            "material": {
                "id": str(mdoc.id),
                "name": mdoc.name,
                "sku": mdoc.sku,
                "price": price
            }
        }

    @staticmethod
    def search_price_in_text(text: str) -> Optional[Dict[str, Any]]:
        """Cerca un materiale nel testo e ritorna la risposta formattata."""
        if not text: return None

        # 1) Unità
        unit = None
        for u in ["kg","m2","m3","pz","lt","m","mq","m²","mc","m³","l","litri","pezzi","pezzo","cart","bomb"]:
            if re.search(rf"\b{re.escape(u)}\b", text, re.IGNORECASE):
                unit = MaterialService.UNIT_MAP.get(u, u)
                break

        # 2) SKU
        sku_match = re.search(r"\b([A-Z]{2,}[0-9]{2,}[A-Z0-9]*)\b", text.upper())
        if sku_match:
            mdoc = MaterialDoc.objects(sku=sku_match.group(1)).first()
            if mdoc: return MaterialService._format_answer(mdoc)

        # 3) Token search
        groups = MaterialService._normalize_tokens(text)
        if not groups: return None

        q = None
        for variants in groups:
            q_or = None
            for v in variants:
                cond = Q(name__icontains=v)
                q_or = cond if q_or is None else (q_or | cond)
            q = q_or if q is None else (q & q_or)

        qs = MaterialDoc.objects
        if q is not None: qs = qs.filter(q)
        if unit: qs = qs.filter(unit=unit)

        mdoc = qs.order_by("name").first()
        if not mdoc and unit:
            # Riprova senza unità
            qs2 = MaterialDoc.objects
            if q is not None: qs2 = qs2.filter(q)
            mdoc = qs2.order_by("name").first()

        return MaterialService._format_answer(mdoc) if mdoc else None
    
    @staticmethod
    def get_by_sku(sku: str) -> Optional[Dict[str, Any]]:
        m = MaterialDoc.objects(sku=sku).first()
        return MaterialService._format_answer(m) if m else None

    @staticmethod
    def search_general(query: str, filters: dict = None) -> List[Dict[str, Any]]:
        """Ricerca generica per intenti SEARCH."""
        filters = filters or {}
        base = MaterialDoc.objects
        if filters.get("category"):
            base = base.filter(category__icontains=filters["category"])
        if filters.get("unit"):
            base = base.filter(unit__iexact=filters["unit"])
        
        # Logica ibrida (aliases -> name -> fulltext)
        hits = list(base.filter(aliases__icontains=query).limit(20))
        if not hits:
            hits = list(base.filter(name__icontains=query).limit(20))
        if not hits:
            try:
                hits = list(base.search_text(query).order_by("$text_score").limit(20))
            except Exception:
                pass
        
        return [{
            "id": str(doc.id),
            "name": doc.name,
            "sku": getattr(doc, "sku", None),
            "unit": getattr(doc, "unit", None),
            "price": getattr(doc, "unit_price_eur_2025", None)
        } for doc in hits]
        
        # --- AGGIUNGI QUESTI METODI ALLA CLASSE MaterialService ---

    @staticmethod
    def get_by_id(material_id: str) -> Optional[MaterialDoc]:
        return MaterialDoc.objects(id=material_id).first()

    @staticmethod
    def upsert_material(data: Dict[str, Any]) -> MaterialDoc:
        """
        Crea o aggiorna un materiale basandosi sullo SKU.
        """
        sku = (data.get("sku") or "").strip().upper()
        name = (data.get("name") or "").strip()
        unit = (data.get("unit") or "").strip().lower()

        if not name or not unit or not sku:
            raise ValueError("name, unit e sku sono obbligatori")

        # Cerca esistente per SKU
        m = MaterialDoc.objects(sku=sku).first()
        if not m:
            m = MaterialDoc(sku=sku)
        
        # Helper per float sicuri
        def _f(v): 
            try: return float(str(v).replace(",", ".").strip()) 
            except: return None
        
        m.name = name
        m.unit = unit
        m.category = data.get("category") or None
        m.subcategory = data.get("subcategory") or None
        
        # Gestione prezzi e quantità
        price = data.get("unit_price_eur_2025")
        if price in (None, ""): price = data.get("price")
        m.unit_price_eur_2025 = _f(price)
        
        vat = data.get("vat_rate")
        m.vat_rate = _f(vat) if vat not in (None, "") else 22.0
        
        m.supplier = data.get("supplier") or None
        m.stock_qty = _f(data.get("stock_qty")) or 0.0
        m.lead_time_days = int(_f(data.get("lead_time_days")) or 0)
        m.notes = data.get("notes") or None
        
        m.save()
        return m

    @staticmethod
    def lookup_best_match(name: str, unit: str = None) -> Dict[str, Any]:
        """
        Cerca il materiale migliore per nome e unità opzionale.
        Ritorna {found: bool, matches: int, material: dict, ...}
        """
        qs = MaterialDoc.objects(name__icontains=name)
        if unit:
            qs = qs.filter(unit__iexact=unit)

        rows = list(qs.order_by("name"))
        if not rows:
            return {"found": False, "matches": 0}

        # Logica di ranking locale
        def _score(m: MaterialDoc) -> int:
            score = 0
            if (m.name or "").lower() == name.lower():
                score += 2
            if unit and (m.unit or "").lower() == unit.lower():
                score += 1
            return score

        rows.sort(key=_score, reverse=True)
        best = rows[0]
        
        # Per coerenza interna, ritorniamo l'oggetto Doc dentro il dict o i dati raw
        # Qui ritorniamo i dati raw per servire direttamente la route 'lookup'
        return {
            "found": True,
            "matches": len(rows),
            "material_doc": best, # Passiamo il doc per serializzarlo fuori
            "price": best.unit_price_eur_2025,
            "unit": best.unit
        }

    @staticmethod
    def list_materials_full(filters: Dict[str, str], query_text: str = "", limit: int = 50, vector_store=None) -> List[MaterialDoc]:
        """
        Lista materiali con filtri DB e fallback su Vector Search.
        """
        base = MaterialDoc.objects
        
        # Filtri DB
        if filters.get("category"):
            base = base.filter(category__icontains=filters["category"])
        if filters.get("subcategory"):
            base = base.filter(subcategory__icontains=filters["subcategory"])
        if filters.get("unit"):
            base = base.filter(unit__iexact=filters["unit"])
        
        hits = []
        if query_text:
            # TIER 1: DB Search (SKU, Name, Alias)
            hits = list(base.filter(
                Q(sku__iexact=query_text) | 
                Q(name__icontains=query_text) | 
                Q(aliases__icontains=query_text)
            ).limit(limit))
            
            # TIER 2: Vector Search (Fallback)
            if not hits and vector_store:
                try:
                    results = vector_store.search(query_text, top_k=limit)
                    material_ids = [r.get("material_id") for r in results if r.get("material_id")]
                    if material_ids:
                        hits = list(base.filter(id__in=material_ids))
                except Exception:
                    pass
        else:
            hits = list(base.order_by("category", "name").limit(limit))
            
        return hits