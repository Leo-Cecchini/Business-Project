# services/estimate_service.py
"""
Servizio unificato per le stime.
Include: Core utilities, Price Lookups, e Logiche specifiche (Elettrico, Idraulico, Pavimenti).
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
import math

from models_mongo.material import MaterialDoc
from models_mongo.worker import WorkerDoc

try:
    from models_mongo.pricelist import PricelistDoc
except Exception:
    PricelistDoc = None

try:
    from mongoengine.connection import get_db
except Exception:
    get_db = None

# ==============================================================================
# 1. CONFIG & CONSTANTS (ex core.py)
# ==============================================================================

DEFAULT_WAGE = {
    "piastrellista": 28.0,
    "elettricista": 32.0,
    "idraulico": 32.0,
    "muratore": 26.0,
}

MATERIAL_ALIASES = {
    "piastrella_gres_60x60": ["piastrella gres 60x60", "gres 60x60", "pavimento 60x60"],
    "piastrella_gres_60x120": ["piastrella gres 60x120", "gres 60x120", "lastre 60x120"],
    "colla_piastrelle": ["colla per piastrelle", "adesivo cementizio", "collante c2"],
    "stucco_fughe": ["stucco fughe", "stuccatura", "stucco epossidico"],
    "massetto_premiscelato": ["massetto premiscelato", "premiscelato", "massetto sabbia cemento"],
    "cavo_elettrico": ["cavo elettrico", "cavo unipolare", "cavo n07v-k"],
    "tubi_corrugati": ["tubo corrugato", "corrugato elettrico", "cavidotto"],
    "scatola_503": ["scatola 503", "scatola incasso 3 moduli"],
    "scatola_504": ["scatola 504", "scatola incasso 4 moduli"],
    "frutti_modulari": ["presa bipasso", "presa schuko", "interruttore", "dev", "invertitore"],
    "placca": ["placca modulare", "placca civile"],
    "cavo_tv": ["cavo coassiale tv", "cavo tv", "rg6"],
    "cavo_dati": ["cavo ethernet cat6", "cavo cat6", "cavo dati cat6"],
    "tubo_pp_dn20": ["tubo multistrato dn20", "tubo pex dn20", "tubo pp dn20"],
    "tubo_pp_dn25": ["tubo multistrato dn25", "tubo pex dn25", "tubo pp dn25"],
    "tubo_pp_dn32": ["tubo multistrato dn32", "tubo pex dn32", "tubo pp dn32"],
    "racc_zincati": ["raccordi multistrato", "raccordi pressare", "gomiti", "tee"],
    "valvole": ["valvola intercettazione", "saracinesca", "sfera"],
    "scarico_dn50": ["tubo scarico dn50", "scarico pvc dn50"],
    "scarico_dn100": ["tubo scarico dn100", "scarico pvc dn100"],
    "collante_pvc": ["collante pvc", "adesivo pvc"],
}

CODE_TO_MATERIAL_KEYS = {
    "FLR-001": ["GRES60X60", "PIASTRELLE_GRES_60X60", "piastrella gres 60x60"],
    "ADH-001": ["COLLA_PIASTRELLE", "ADESIVO_C2", "colla per piastrelle"],
    "STU-001": ["STUCCO_FUGHE", "STUCCO_EPOS", "stucco fughe"],
    "BSK-001": ["BATTISCOPA_GRES", "battiscopa gres"],
    "WAS-001": ["SACCHI_MACERIE_25KG", "sacchi macerie 25kg"],
    "EL-PL": ["KIT_PUNTO_LUCE", "punto luce kit"],
    "EL-PP": ["KIT_PUNTO_PRESA", "punto presa kit"],
    "EL-CAVO-3G1.5": ["CAVO_3G1_5", "N07V-K_1.5", "cavo 3g1.5"],
    "EL-CAVO-3G2.5": ["CAVO_3G2_5", "N07V-K_2.5", "cavo 3g2.5"],
    "EL-TUBO-20": ["TUBO_CORR_20", "corrugato 20"],
    "EL-SCATOLA-503": ["SCATOLA_503"],
    "EL-SCATOLA-DER": ["SCATOLA_DERIVAZIONE"],
    "IDR-TUBO-PPR-20": ["TUBO_PPR_20", "tubo ppr 20"],
    "IDR-SCARICO-HT-50": ["TUBO_HT_50", "scarico 50"],
    "IDR-RACCORDI-PACK": ["KIT_RACCORDI_PPR", "raccordi ppr"],
    "IDR-BAGNO-PACK": ["KIT_IDRICO_BAGNO"],
    "IDR-001": ["TUBO_DN32", "tubo acqua dn32"],
    "IDR-002": ["TUBO_DN25", "tubo acqua dn25"],
    "IDR-003": ["TUBO_DN20", "tubo acqua dn20"],
}

FLOORING_FORMATS = {
    "60x60": {"waste": 0.10, "hours_per_m2": 0.25},
    "60x120": {"waste": 0.12, "hours_per_m2": 0.28},
    "default": {"waste": 0.10, "hours_per_m2": 0.25},
}

ELECTRIC_CONFIGS = {
    "punto_luce": {"cavo_m": 15, "tubo_m": 15, "scatole": 2, "frutti": 2, "hours": 1.2},
    "punto_presa": {"cavo_m": 12, "tubo_m": 12, "scatole": 1, "frutti": 1, "hours": 0.8},
    "punto_dati": {"cavo_m": 12, "tubo_m": 12, "scatole": 1, "frutti": 1, "hours": 0.7},
    "punto_tv": {"cavo_m": 12, "tubo_m": 12, "scatole": 1, "frutti": 1, "hours": 0.6},
}

HYDRAULIC_CONFIGS = {
    "bagno_std": {
        "tubo_carico_m": 25,
        "tubo_scarico_m": 8,
        "raccordi_n": 12,
        "valvole_n": 4,
        "hours": 16,
    }
}

# ==============================================================================
# 2. DATACLASSES
# ==============================================================================

@dataclass
class LineItem:
    code: str
    description: str
    quantity: float
    unit: str
    unit_price: float
    role: Optional[str] = None

    @property
    def total(self) -> float:
        return round(self.quantity * self.unit_price, 2)

@dataclass
class LaborItem:
    role: str
    hours: float
    hourly_rate: float

    @property
    def total(self) -> float:
        return round(self.hours * self.hourly_rate, 2)

@dataclass
class CalcItem:
    label: str
    qty: float
    unit: str
    
@dataclass
class CalcBundle:
    items: List[CalcItem]
    raw_text: str

# ==============================================================================
# 3. HELPER LOOKUPS (Price, Wage, Pricelist)
# ==============================================================================

def _db_price(name_tokens: List[str], prefer_unit: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Search MaterialDoc by tokens and return price info."""
    if not name_tokens:
        return None
    
    query = MaterialDoc.objects
    for tok in name_tokens:
        if len(tok) >= 2:
            query = query.filter(name__icontains=tok)
    
    if prefer_unit:
        query = query.filter(unit__iexact=prefer_unit)
    
    candidates = list(query.limit(10))
    if not candidates:
        return None
    
    def score(m: MaterialDoc) -> int:
        s = 0
        name_lower = (m.name or "").lower()
        for tok in name_tokens:
            if tok.lower() in name_lower:
                s += 2
        if m.aliases:
            for alias in m.aliases:
                for tok in name_tokens:
                    if tok.lower() in alias.lower():
                        s += 1
        if prefer_unit and m.unit and m.unit.lower() == prefer_unit.lower():
            s += 3
        return s
    
    best = max(candidates, key=score)
    return {
        "name": best.name,
        "unit": best.unit,
        "price": best.unit_price_eur_2025 or 0.0,
        "sku": best.sku,
    }

def _price_for(alias_key: str, prefer_unit: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Lookup price by alias key."""
    variants = MATERIAL_ALIASES.get(alias_key, [alias_key])
    for v in variants:
        tokens = v.split()
        result = _db_price(tokens, prefer_unit)
        if result:
            return result
    return None

def _hourly_rate_for(role: str) -> float:
    """Get hourly rate for role from DB or default."""
    try:
        workers = WorkerDoc.objects(role__iexact=role, available=True).limit(5)
        rates = [w.hourly_rate for w in workers if w.hourly_rate and w.hourly_rate > 0]
        if rates:
            return round(sum(rates) / len(rates), 2)
    except Exception:
        pass
    return DEFAULT_WAGE.get(role.lower(), 25.0)

# ==============================================================================
# 4. DOMAIN ESTIMATORS (Flooring, Electric, Hydraulic)
# ==============================================================================

def estimate_flooring(mq: float, formato: str = "60x60") -> Dict[str, Any]:
    """Estimate cost for floor tiling."""
    fmt = FLOORING_FORMATS.get(formato, FLOORING_FORMATS["default"])
    waste = fmt["waste"]
    hours_per_m2 = fmt["hours_per_m2"]

    gres_alias = "piastrella_gres_60x60" if formato == "60x60" else (
        "piastrella_gres_60x120" if formato == "60x120" else "piastrella_gres_60x60"
    )
    gres = _price_for(gres_alias, prefer_unit="m2")
    colla = _price_for("colla_piastrelle", prefer_unit="kg")
    stucco = _price_for("stucco_fughe", prefer_unit="kg")
    massetto = _price_for("massetto_premiscelato", prefer_unit="m3")

    qty_gres = mq * (1 + waste)
    qty_colla = mq * 3.5
    qty_stucco = mq * 0.15
    qty_massetto = 0.0

    items: List[LineItem] = []
    
    def add_item(code, desc, qty, unit, price, role=None):
        if price is None: price = 0.0
        items.append(LineItem(code, desc, qty, unit, float(price), role))

    add_item("FLR-001", f"Piastrelle gres {formato}", qty_gres, "m2", gres["price"] if gres else 0.0)
    add_item("FLR-002", "Colla per piastrelle", qty_colla, "kg", colla["price"] if colla else 0.0)
    add_item("FLR-003", "Stucco fughe", qty_stucco, "kg", stucco["price"] if stucco else 0.0)
    if qty_massetto > 0 and massetto:
        add_item("FLR-004", "Massetto premiscelato", qty_massetto, "m3", massetto["price"])

    hours = mq * hours_per_m2
    wage = _hourly_rate_for("piastrellista")
    labor = [LaborItem("piastrellista", hours, wage)]

    subtotal_materials = round(sum(i.total for i in items), 2)
    subtotal_labor = round(sum(l.total for l in labor), 2)

    return {
        "scope": "pavimento",
        "inputs": {"mq": mq, "formato": formato},
        "materials": [asdict(i) | {"total": i.total} for i in items],
        "labor": [asdict(l) | {"total": l.total} for l in labor],
        "subtotal_materials": subtotal_materials,
        "subtotal_labor": subtotal_labor,
        "notes": ["Sfrido incluso", "Esclusi jolly/pezzi speciali"],
    }

def estimate_electric(punti_luce: int = 0, punti_prese: int = 0, punti_dati: int = 0, punti_tv: int = 0) -> Dict[str, Any]:
    """Estimate cost for electrical installation."""
    cavo = _price_for("cavo_elettrico", prefer_unit="m")
    tubo = _price_for("tubi_corrugati", prefer_unit="m")
    scatola = _price_for("scatola_503", prefer_unit="pz")
    frutti = _price_for("frutti_modulari", prefer_unit="pz")
    placca = _price_for("placca", prefer_unit="pz")
    cavo_tv = _price_for("cavo_tv", prefer_unit="m")
    cavo_dati = _price_for("cavo_dati", prefer_unit="m")

    items: List[LineItem] = []
    total_hours = 0.0

    def add_item(code, desc, qty, unit, price, role=None):
        if price is None: price = 0.0
        if qty > 0:
            items.append(LineItem(code, desc, qty, unit, float(price), role))

    if punti_luce > 0:
        cfg = ELECTRIC_CONFIGS["punto_luce"]
        add_item("EL-CAVO-3G1.5", "Cavo 3G1.5mm²", punti_luce * cfg["cavo_m"], "m", cavo["price"] if cavo else 0.0)
        add_item("EL-TUBO-20", "Tubo corrugato Ø20", punti_luce * cfg["tubo_m"], "m", tubo["price"] if tubo else 0.0)
        add_item("EL-SCATOLA-503", "Scatola 503", punti_luce * cfg["scatole"], "pz", scatola["price"] if scatola else 0.0)
        add_item("EL-FRUTTI-PL", "Frutti punto luce", punti_luce * cfg["frutti"], "pz", frutti["price"] if frutti else 0.0)
        add_item("EL-PLACCA", "Placca modulare", punti_luce, "pz", placca["price"] if placca else 0.0)
        total_hours += punti_luce * cfg["hours"]

    if punti_prese > 0:
        cfg = ELECTRIC_CONFIGS["punto_presa"]
        add_item("EL-CAVO-3G2.5", "Cavo 3G2.5mm²", punti_prese * cfg["cavo_m"], "m", cavo["price"] if cavo else 0.0)
        add_item("EL-TUBO-20", "Tubo corrugato Ø20", punti_prese * cfg["tubo_m"], "m", tubo["price"] if tubo else 0.0)
        add_item("EL-SCATOLA-503", "Scatola 503", punti_prese * cfg["scatole"], "pz", scatola["price"] if scatola else 0.0)
        add_item("EL-FRUTTI-PP", "Frutti presa", punti_prese * cfg["frutti"], "pz", frutti["price"] if frutti else 0.0)
        add_item("EL-PLACCA", "Placca modulare", punti_prese, "pz", placca["price"] if placca else 0.0)
        total_hours += punti_prese * cfg["hours"]

    if punti_dati > 0:
        cfg = ELECTRIC_CONFIGS["punto_dati"]
        add_item("EL-CAVO-CAT6", "Cavo Cat6 UTP", punti_dati * cfg["cavo_m"], "m", cavo_dati["price"] if cavo_dati else 0.0)
        add_item("EL-TUBO-20", "Tubo corrugato Ø20", punti_dati * cfg["tubo_m"], "m", tubo["price"] if tubo else 0.0)
        add_item("EL-SCATOLA-503", "Scatola 503", punti_dati * cfg["scatole"], "pz", scatola["price"] if scatola else 0.0)
        add_item("EL-FRUTTI-DATI", "Frutti RJ45", punti_dati * cfg["frutti"], "pz", frutti["price"] if frutti else 0.0)
        add_item("EL-PLACCA", "Placca modulare", punti_dati, "pz", placca["price"] if placca else 0.0)
        total_hours += punti_dati * cfg["hours"]

    if punti_tv > 0:
        cfg = ELECTRIC_CONFIGS["punto_tv"]
        add_item("EL-CAVO-TV", "Cavo coassiale TV", punti_tv * cfg["cavo_m"], "m", cavo_tv["price"] if cavo_tv else 0.0)
        add_item("EL-TUBO-20", "Tubo corrugato Ø20", punti_tv * cfg["tubo_m"], "m", tubo["price"] if tubo else 0.0)
        add_item("EL-SCATOLA-503", "Scatola 503", punti_tv * cfg["scatole"], "pz", scatola["price"] if scatola else 0.0)
        add_item("EL-FRUTTI-TV", "Presa TV", punti_tv * cfg["frutti"], "pz", frutti["price"] if frutti else 0.0)
        add_item("EL-PLACCA", "Placca modulare", punti_tv, "pz", placca["price"] if placca else 0.0)
        total_hours += punti_tv * cfg["hours"]

    wage = _hourly_rate_for("elettricista")
    labor = [LaborItem("elettricista", total_hours, wage)]

    subtotal_materials = round(sum(i.total for i in items), 2)
    subtotal_labor = round(sum(l.total for l in labor), 2)

    return {
        "scope": "impianto_elettrico",
        "inputs": {"punti_luce": punti_luce, "punti_prese": punti_prese, "punti_dati": punti_dati},
        "materials": [asdict(i) | {"total": i.total} for i in items],
        "labor": [asdict(l) | {"total": l.total} for l in labor],
        "subtotal_materials": subtotal_materials,
        "subtotal_labor": subtotal_labor,
        "notes": ["Tracce murarie escluse", "Quadro elettrico escluso"]
    }

def estimate_hydraulic(n_bagni: int = 1, punti_extra: int = 0) -> Dict[str, Any]:
    """Estimate cost for hydraulic installation."""
    tubo_20 = _price_for("tubo_pp_dn20", prefer_unit="m")
    tubo_25 = _price_for("tubo_pp_dn25", prefer_unit="m")
    tubo_32 = _price_for("tubo_pp_dn32", prefer_unit="m")
    raccordi = _price_for("racc_zincati", prefer_unit="pz")
    valvole = _price_for("valvole", prefer_unit="pz")
    scarico_50 = _price_for("scarico_dn50", prefer_unit="m")
    scarico_100 = _price_for("scarico_dn100", prefer_unit="m")
    collante = _price_for("collante_pvc", prefer_unit="kg")

    items: List[LineItem] = []
    total_hours = 0.0

    def add_item(code, desc, qty, unit, price, role=None):
        if price is None: price = 0.0
        if qty > 0:
            items.append(LineItem(code, desc, qty, unit, float(price), role))

    if n_bagni > 0:
        cfg = HYDRAULIC_CONFIGS["bagno_std"]
        add_item("IDR-001", "Tubo PP-R Ø32mm (principale)", n_bagni * 5, "m", tubo_32["price"] if tubo_32 else 0.0)
        add_item("IDR-002", "Tubo PP-R Ø25mm (derivazioni)", n_bagni * 10, "m", tubo_25["price"] if tubo_25 else 0.0)
        add_item("IDR-003", "Tubo PP-R Ø20mm (terminali)", n_bagni * cfg["tubo_carico_m"], "m", tubo_20["price"] if tubo_20 else 0.0)
        add_item("IDR-004", "Raccordi multistrato", n_bagni * cfg["raccordi_n"], "pz", raccordi["price"] if raccordi else 0.0)
        add_item("IDR-005", "Valvole intercettazione", n_bagni * cfg["valvole_n"], "pz", valvole["price"] if valvole else 0.0)
        add_item("IDR-006", "Tubo scarico PVC Ø50mm", n_bagni * 4, "m", scarico_50["price"] if scarico_50 else 0.0)
        add_item("IDR-007", "Tubo scarico PVC Ø100mm", n_bagni * cfg["tubo_scarico_m"], "m", scarico_100["price"] if scarico_100 else 0.0)
        add_item("IDR-008", "Collante PVC", n_bagni * 0.5, "kg", collante["price"] if collante else 0.0)
        total_hours += n_bagni * cfg["hours"]

    if punti_extra > 0:
        add_item("IDR-003", "Tubo PP-R Ø20mm (extra)", punti_extra * 8, "m", tubo_20["price"] if tubo_20 else 0.0)
        add_item("IDR-004", "Raccordi multistrato (extra)", punti_extra * 4, "pz", raccordi["price"] if raccordi else 0.0)
        add_item("IDR-005", "Valvole intercettazione (extra)", punti_extra, "pz", valvole["price"] if valvole else 0.0)
        add_item("IDR-006", "Tubo scarico PVC Ø50mm (extra)", punti_extra * 3, "m", scarico_50["price"] if scarico_50 else 0.0)
        total_hours += punti_extra * 4

    wage = _hourly_rate_for("idraulico")
    labor = [LaborItem("idraulico", total_hours, wage)]

    subtotal_materials = round(sum(i.total for i in items), 2)
    subtotal_labor = round(sum(l.total for l in labor), 2)

    return {
        "scope": "impianto_idrico",
        "inputs": {"n_bagni": n_bagni, "punti_extra": punti_extra},
        "materials": [asdict(i) | {"total": i.total} for i in items],
        "labor": [asdict(l) | {"total": l.total} for l in labor],
        "subtotal_materials": subtotal_materials,
        "subtotal_labor": subtotal_labor,
        "notes": ["Tracce murarie escluse", "Sanitari esclusi"]
    }

# ==============================================================================
# 5. DISPATCHER & PUBLIC API
# ==============================================================================

def estimate_from_entities(entities: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Funzione dispatcher chiamata da ChatService.
    Decide quale logica di stima invocare in base alle entità trovate.
    """
    # Flooring
    if "qty" in entities and ("unit" in entities and entities["unit"] in ["m2","mq","metri quadri"]):
        # Se c'è un hint di pavimento/piastrelle (semplificato) o se non c'è altro
        if any(k in str(entities).lower() for k in ["pavim","piastrell","gres","terra"]):
             return estimate_flooring(entities["qty"], entities.get("formato", "60x60"))
        # Default fallback se sono mq
        return estimate_flooring(entities["qty"], entities.get("formato", "60x60"))

    # Electric
    if any(k in entities for k in ["punti_luce", "punti_prese", "punti_dati", "punti_tv"]):
        return estimate_electric(
            punti_luce=int(entities.get("punti_luce") or 0),
            punti_prese=int(entities.get("punti_prese") or 0),
            punti_dati=int(entities.get("punti_dati") or 0),
            punti_tv=int(entities.get("punti_tv") or 0),
        )

    # Hydraulic
    if "n_bagni" in entities or "punti_idrici_extra" in entities:
        return estimate_hydraulic(
            n_bagni=int(entities.get("n_bagni") or 0),
            punti_extra=int(entities.get("punti_idrici_extra") or 0)
        )

    return None

def price(code: str, default: float = 0.0, *, region: str | None = None, city: str | None = None, tags: list[str] | None = None) -> float:
    """Public API per prezzi (usata da ChatService/Skills)."""
    # Qui integriamo _get_pricelist e _apply_factors se necessario
    # Per ora wrapper semplice su _lookup_material_price_by_code
    val = _lookup_material_price_by_code(code)
    return val if val is not None else default

def wage(role: str, default: float = 25.0, *, region: str | None = None, city: str | None = None, tags: list[str] | None = None) -> float:
    """Public API per costo orario."""
    return _hourly_rate_for(role)

def _get_pricelist(region: str | None, city: str | None) -> dict:
    # Stub per compatibilità
    return {}

def _apply_factors(base: float, factors: dict, tags: list[str] | None) -> float:
    # Stub per compatibilità
    return base

def _lookup_material_price_by_code(code: str) -> Optional[float]:
    keys = CODE_TO_MATERIAL_KEYS.get(code, [])
    for key in keys:
        res = _db_price(key.split())
        if res: return res["price"]
    return None

__all__ = [
    'estimate_from_entities', 
    'estimate_flooring', 
    'estimate_electric', 
    'estimate_hydraulic',
    'price', 
    'wage'
]