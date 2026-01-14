# routes/estimate.py
from __future__ import annotations
from math import ceil
import math
from dataclasses import dataclass, asdict
import time
from typing import Dict, Any, List, Optional
import os
import re
from flask import Blueprint, request, jsonify, g, current_app


from models_mongo.material import MaterialDoc
from models_mongo.worker import WorkerDoc
try:
    from models_mongo.pricelist import PricelistDoc
except Exception:
    PricelistDoc = None

# Fallback raw-PyMongo access (when PricelistDoc is not available)
try:
    from mongoengine.connection import get_db  # used only if PricelistDoc is None
except Exception:
    get_db = None

# Guarded imports for project/site models
try:
    from models_mongo.project import ProjectDoc
except Exception:
    ProjectDoc = None
try:
    from models_mongo.site import SiteDoc
except Exception:
    SiteDoc = None

estimate_bp = Blueprint("estimate", __name__, url_prefix="/api/estimate")

# -------------------------
# Config & default fallback
# -------------------------

DEFAULT_WAGE = {
    "piastrellista": 28.0,   # €/h se mancano nel DB
    "elettricista": 32.0,
    "idraulico": 32.0,
    "muratore": 26.0,
}

# Pricing strategy:
# - "absolute" (default): use explicit per-region prices if present in Pricelist.
# - "multiplier": base prices are the catalog ones; territorial multipliers are applied.
PRICING_MODE = (os.getenv("PRICING_MODE", "absolute") or "absolute").strip().lower()

# Default regional multipliers (editable). Used when PRICING_MODE == "multiplier" OR
# when a Pricelist doc explicitly provides a multiplier.
REGION_MULTIPLIERS = {
    # Nord
    "Valle d'Aosta": 1.10,
    "Piemonte": 1.10,
    "Liguria": 1.10,
    "Lombardia": 1.10,
    "Trentino-Alto Adige": 1.10,
    "Veneto": 1.10,
    "Friuli-Venezia Giulia": 1.10,
    "Emilia-Romagna": 1.10,
    # Centro
    "Toscana": 1.03,
    "Umbria": 1.03,
    "Marche": 1.03,
    "Lazio": 1.03,
    # Sud
    "Abruzzo": 0.95,
    "Molise": 0.95,
    "Campania": 0.95,
    "Puglia": 0.95,
    "Basilicata": 0.95,
    "Calabria": 0.95,
    # Isole
    "Sicilia": 0.94,
    "Sardegna": 0.94,
}

_REGION_MULTIPLIERS_LC = {str(k).strip().lower(): float(v) for k, v in REGION_MULTIPLIERS.items()}

# Nel DB si cerca per "name ILIKE %token%"; puoi mappare sinonimi qui
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

# Mappa codici-preventivo → possibili SKU/codici materiali nel DB
CODE_TO_MATERIAL_KEYS = {
    # Piastrelle / posa
    "FLR-001": ["GRES60X60", "PIASTRELLE_GRES_60X60", "piastrella gres 60x60"],
    "ADH-001": ["COLLA_PIASTRELLE", "ADESIVO_C2", "colla per piastrelle"],
    "STU-001": ["STUCCO_FUGHE", "STUCCO_EPOS", "stucco fughe"],
    "BSK-001": ["BATTISCOPA_GRES", "battiscopa gres"],

    # Smaltimento
    "WAS-001": ["SACCHI_MACERIE_25KG", "sacchi macerie 25kg"],

    # Elettrico (esempi)
    "EL-PL": ["KIT_PUNTO_LUCE", "punto luce kit"],
    "EL-PP": ["KIT_PUNTO_PRESA", "punto presa kit"],
    "EL-CAVO-3G1.5": ["CAVO_3G1_5", "N07V-K_1.5", "cavo 3g1.5"],
    "EL-CAVO-3G2.5": ["CAVO_3G2_5", "N07V-K_2.5", "cavo 3g2.5"],
    "EL-TUBO-20": ["TUBO_CORR_20", "corrugato 20"],
    "EL-SCATOLA-503": ["SCATOLA_503"],
    "EL-SCATOLA-DER": ["SCATOLA_DERIVAZIONE"],

    # Idrico (esempi)
    "IDR-TUBO-PPR-20": ["TUBO_PPR_20", "tubo ppr 20"],
    "IDR-SCARICO-HT-50": ["TUBO_HT_50", "scarico 50"],
    "IDR-RACCORDI-PACK": ["KIT_RACCORDI_PPR", "raccordi ppr"],
    "IDR-BAGNO-PACK": ["KIT_IDRICO_BAGNO"],
    "IDR-001": ["TUBO_DN32", "tubo acqua dn32"],
    "IDR-002": ["TUBO_DN25", "tubo acqua dn25"],
    "IDR-003": ["TUBO_DN20", "tubo acqua dn20"],
    "IDR-004": ["RACC_PPR_MISC", "raccordi"],
    "IDR-005": ["VALVOLA_SFERA", "valvola intercettazione"],
    "IDR-006": ["SCARICO_PVC_50", "scarico pvc 50"],
    "IDR-007": ["SCARICO_PVC_100", "scarico pvc 100"],
    "IDR-008": ["COLLANTE_PVC", "collante pvc"],
}

# -------------------------
# Util: ricerca prezzi nel DB
# -------------------------

def _db_price(name_tokens: List[str], prefer_unit: Optional[str]=None) -> Optional[Dict[str, Any]]:
    """
    Cerca nel DB Material (MongoEngine) dove name contiene TUTTI i token.
    Se prefer_unit è indicato (es. 'm2','m','pz','kg','lt'), priorizza risultati con quella unità.
    """
    if not name_tokens:
        return None

    # Query iniziale ampia (MongoEngine)
    q = MaterialDoc.objects
    for tok in name_tokens:
        if tok:
            q = q.filter(name__icontains=tok)

    results = list(q.order_by("unit"))
    if not results:
        return None

    # scoring semplice: +2 se unit combacia, +1 se name inizia con primo token
    nl0 = (name_tokens[0] or "").lower() if name_tokens else ""

    def score(m: MaterialDoc) -> int:
        s = 0
        unit = (getattr(m, "unit", "") or "").lower()
        name = (getattr(m, "name", "") or "").lower()
        if prefer_unit and unit == prefer_unit.lower():
            s += 2
        if name.startswith(nl0):
            s += 1
        return s

    results.sort(key=score, reverse=True)
    best = results[0]
    mat_dict = best.to_mongo().to_dict() if hasattr(best, "to_mongo") else {}

    return {
        "name": getattr(best, "name", None),
        "unit": getattr(best, "unit", None),
        "price": getattr(best, "unit_price_eur_2025", None),
        "raw": mat_dict,
    }

# -------------------------
# Margine aziendale (configurabile)
# -------------------------

def _company_margin_pct() -> float:
    """Percentuale margine aziendale (env COMPANY_MARGIN_PCT, default 22%)."""
    try:
        pct = float(os.getenv("COMPANY_MARGIN_PCT", "22"))
        if pct < 0: pct = 0.0
        if pct > 60: pct = 60.0
        return round(pct, 2)
    except Exception:
        return 22.0

def _apply_company_margin(subtotal: float) -> tuple[float, float, float]:
    """Ritorna (pct, margin_amount, total_with_margin)."""
    pct = _company_margin_pct()
    margin = round((subtotal or 0.0) * (pct/100.0), 2)
    total = round((subtotal or 0.0) + margin, 2)
    return pct, margin, total

def _price_for(alias_key: str, prefer_unit: Optional[str]=None) -> Optional[Dict[str, Any]]:
    aliases = MATERIAL_ALIASES.get(alias_key, [])
    for label in aliases:
        tokens = [t for t in label.lower().split() if t]
        hit = _db_price(tokens, prefer_unit=prefer_unit)
        if hit and hit.get("price") is not None:
            return hit
    return None

# -------------------------
# Regole di stima (estendibili)
# -------------------------

@dataclass
class LineItem:
    code: str
    description: str
    qty: float
    unit: str
    unit_price: float
    role: Optional[str] = None

    @property
    def total(self) -> float:
        return round(self.qty * self.unit_price, 2)

@dataclass
class LaborItem:
    role: str
    hours: float
    hourly_rate: float

    @property
    def total(self) -> float:
        return round(self.hours * self.hourly_rate, 2)

# Coefficienti sfrido e produttività per formati
FLOORING_FORMATS = {
    "60x60": {"waste": 0.08, "hours_per_m2": 0.7},   # 8% sfrido, 0.7h/m²
    "60x120": {"waste": 0.10, "hours_per_m2": 0.85}, # lastre più impegnative
    "30x60": {"waste": 0.07, "hours_per_m2": 0.65},
    "30x30": {"waste": 0.06, "hours_per_m2": 0.6},
    "default": {"waste": 0.08, "hours_per_m2": 0.7},
}

# Produttività impianti (indicativa)
ELECTRIC_PRODUCTIVITY = {
    "punto_luce": 0.6,   # h/punto
    "punto_presa": 0.55,
    "punto_dati": 0.65,
    "punto_tv": 0.65,
    "traccia_m": 0.15,   # h/metro di traccia (muratore)
}


HYDRAULIC_PRODUCTIVITY = {
    "bagno_completo": 12.0,     # h/bagno (posa tubi+collegamenti sanitari, senza finiture pregiate)
    "punto_idrico": 2.5,        # h/punto acqua (lavabo, bidet, doccia: media)
    "scarico_m": 0.35,          # h/metro scarico PVC
    "tubo_acqua_m": 0.25,       # h/metro multistrato
}

# -------------------------
# Work catalog helpers (crew requirements)
# -------------------------

# Map simple labels to catalog codes (best-effort)
WORK_LABEL_TO_CODE = {
    "posa piastrelle": "FLOOR_TILE",
    "posa pavimento": "FLOOR_TILE",
    "piastrelle": "FLOOR_TILE",
    "battiscopa": "FLOOR_TILE",
    "smaltimento macerie": "SITE_WASTE",
    "macerie": "SITE_WASTE",
    "posa porta": "FIN_DOOR",
    "porta": "FIN_DOOR",
    "punto luce": "ELEC_FIXTURE",
    "punti luce": "ELEC_FIXTURE",
    "punto presa": "ELEC_FIXTURE",
    "punti presa": "ELEC_FIXTURE",
    "impianto idrico bagno": "PLUMB_FIXTURE",
    "punto idrico": "PLUMB_ROUGH",
    "punti idrici": "PLUMB_ROUGH",
}

# -------------------------
# Robust catalog matching (label -> work_catalog.code)
# -------------------------

# Basic Italian stopwords for catalog matching (keep this small & safe)
_CAT_STOPWORDS = {
    "di", "del", "dello", "della", "dei", "degli", "delle",
    "a", "ad", "da", "dal", "dall", "dalla", "dai", "dagli", "dalle",
    "in", "su", "con", "senza", "per", "tra", "fra",
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una",
    "mq", "m2", "m3", "mc", "ml", "pz", "nr", "n",    "puoi",
    "farmi",
    "fammi",
    "preventivo",
    "preventivi",
    "casa",
    "abitazione",
    "appartamento",
    "villa",
    "chiedo",
    "richiedo",
    "vorrei",
    "potresti",

}

_CAT_WORD_RE = re.compile(r"[a-zàèéìòóù0-9]+", re.IGNORECASE)


def _cat_tokens(label: str) -> List[str]:
    toks = [t.lower() for t in _CAT_WORD_RE.findall(label or "")]
    toks = [t for t in toks if len(t) >= 3 and t not in _CAT_STOPWORDS]
    # keep order but remove duplicates
    seen = set()
    out = []
    for t in toks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _best_work_catalog_code(label: str, unit: str | None) -> Optional[str]:
    """Best-effort match of a free label against work_catalog by name/synonyms.

    NOTE: This is intentionally *not* an AND over all tokens:
    chat sentences often contain irrelevant words ("puoi", "preventivo", ...), and an AND
    would return empty results too often.

    Strategy:
      - tokenize + light token expansion (plural/singular heuristics)
      - query by OR over a handful of tokens
      - score by number of matched tokens (+unit bonus)
    """
    if get_db is None:
        return None

    base_toks = _cat_tokens(label)
    if not base_toks:
        return None

    # light token expansion: handle common plurals (bagni->bagno) and add stems
    toks: List[str] = []
    for t in base_toks:
        toks.append(t)
        if t.endswith("i") and len(t) > 3:
            toks.append(t[:-1])          # stem
            toks.append(t[:-1] + "o")    # rough singular
        elif t.endswith("e") and len(t) > 3:
            toks.append(t[:-1])          # stem

    # de-dup preserving order
    seen = set()
    dedup = []
    for t in toks:
        if t not in seen:
            seen.add(t)
            dedup.append(t)
    toks = dedup

    # Keep the most meaningful tokens first (prefer longer ones)
    toks.sort(key=len, reverse=True)
    toks = toks[:8]

    try:
        db = get_db()
        or_terms = []
        for tok in toks:
            or_terms.append({"code": {"$regex": tok, "$options": "i"}})
            or_terms.append({"name": {"$regex": tok, "$options": "i"}})
            or_terms.append({"synonyms": {"$elemMatch": {"$regex": tok, "$options": "i"}}})

        filt: Dict[str, Any] = {"$or": or_terms} if or_terms else {}
        cur = list(db["work_catalog"].find(
            filt,
            {"_id": 0, "code": 1, "name": 1, "synonyms": 1, "unit": 1}
        ).limit(80))

        if not cur:
            return None

        def _score(doc: dict) -> int:
            blob = (str(doc.get("code") or "") + " " + str(doc.get("name") or "") + " " + " ".join(doc.get("synonyms") or [])).lower()
            s = 0
            for t in toks:
                if t and t in blob:
                    s += 2
            if unit and str(doc.get("unit") or "").lower() == str(unit).lower():
                s += 5
            if "impianto" in (label or "").lower() and "impianto" in blob:
                s += 1
            return s

        cur.sort(key=_score, reverse=True)
        best = cur[0]
        return str(best.get("code") or "").strip() or None
    except Exception:
        return None

def _catalog_code_from_label(label: str, unit: str) -> str | None:
    lab = (label or "").lower()
    # try direct contains matches in priority order
    for key, code in WORK_LABEL_TO_CODE.items():
        if key in lab:
            # small refinement: if battiscopa explicitly, keep FLOOR_TILE but caller may treat separately
            return code
    # heuristics
    if ("piastrell" in lab or "paviment" in lab) and unit == "m2":
        return "FLOOR_TILE"
    if ("porta" in lab and "posa" in lab) and unit == "pz":
        return "FIN_DOOR"
    if ("macerie" in lab or "smaltimento" in lab):
        return "SITE_WASTE"
    if ("elettric" in lab and ("luce" in lab or "presa" in lab)):
        return "ELEC_FIXTURE"
    # plumbing: distinguish rough (tubazioni) vs fixtures (sanitari)
    if ("impianto idric" in lab) or ("impianto idraul" in lab):
        return "PLUMB_ROUGH"
    if (("idric" in lab or "idraul" in lab) and (("bagno" in lab) or ("bagni" in lab) or ("sanitar" in lab) or ("rubinett" in lab) or ("punto" in lab) or ("wc" in lab))):
        return "PLUMB_FIXTURE"
    # DB search fallback (name/synonyms)
    return _best_work_catalog_code(label, unit)

def _crew_requirements_for_code(code: str | None) -> dict:
    """Fetches crew requirements (min_crew, crew_roles, pairing_rule) from work_catalog.
    Returns empty dict if not found or DB unavailable.
    """
    if not code or get_db is None:
        return {}
    try:
        db = get_db()
        doc = db["work_catalog"].find_one({"code": code}, {"_id":0, "min_crew":1, "crew_roles":1, "pairing_rule":1})
        if not doc:
            return {}
        # Normalize types
        out = {}
        if isinstance(doc.get("min_crew"), (int, float)):
            out["min_crew"] = int(doc["min_crew"]) if isinstance(doc["min_crew"], int) else int(round(doc["min_crew"]))
        if isinstance(doc.get("crew_roles"), dict):
            # ensure ints
            out["crew_roles"] = {str(k): int(v) for k, v in doc["crew_roles"].items() if isinstance(v, (int, float))}
        if isinstance(doc.get("pairing_rule"), str):
            out["pairing_rule"] = doc["pairing_rule"]
        return out
    except Exception:
        return {}
    
def _work_catalog_item(code: str | None) -> dict:
    if not code or get_db is None:
        return {}
    try:
        db = get_db()
        doc = db["work_catalog"].find_one({"code": code}, {"_id": 0}) or {}
        return doc or {}
    except Exception:
        return {}

# -------------------------
# Calcolo manodopera (da DB o default)
# -------------------------

def _hourly_rate_for(role: str) -> float:
    w = WorkerDoc.objects(role__icontains=role).first()
    if w and getattr(w, "hourly_rate", None) is not None:
        try:
            return float(w.hourly_rate)
        except Exception:
            pass
    return DEFAULT_WAGE.get(role, 28.0)

# -------------------------
# Stime: Pavimento
# -------------------------

def estimate_flooring(mq: float, formato: str="60x60") -> Dict[str, Any]:
    fmt = FLOORING_FORMATS.get(formato, FLOORING_FORMATS["default"])
    waste = fmt["waste"]
    hours_per_m2 = fmt["hours_per_m2"]

    # Quantità materiali base
    gres_alias = "piastrella_gres_60x60" if formato == "60x60" else (
        "piastrella_gres_60x120" if formato == "60x120" else "piastrella_gres_60x60"
    )
    gres = _price_for(gres_alias, prefer_unit="m2")
    colla = _price_for("colla_piastrelle", prefer_unit="kg")
    stucco = _price_for("stucco_fughe", prefer_unit="kg")
    massetto = _price_for("massetto_premiscelato", prefer_unit="m3")

    # Consumi (indicativi): colla 3.5 kg/m², stucco 0.15 kg/m², massetto 0.06 m³/m² se serve
    qty_gres = mq * (1 + waste)         # m²
    qty_colla = mq * 3.5                 # kg
    qty_stucco = mq * 0.15               # kg
    qty_massetto = 0.0                   # m³, lo calcoli solo se serve massetto (qui lo teniamo 0)

    items: List[LineItem] = []

    def add_item(code, desc, qty, unit, price, role=None):
        if price is None:
            price = 0.0
        items.append(LineItem(code, desc, qty, unit, float(price), role))

    add_item("FLR-001", f"Piastrelle gres {formato}", qty_gres, "m2", gres["price"] if gres else 0.0)
    add_item("FLR-002", "Colla per piastrelle", qty_colla, "kg", colla["price"] if colla else 0.0)
    add_item("FLR-003", "Stucco fughe", qty_stucco, "kg", stucco["price"] if stucco else 0.0)
    if qty_massetto > 0 and massetto:
        add_item("FLR-004", "Massetto premiscelato", qty_massetto, "m3", massetto["price"])

    # Manodopera piastrellista
    hours = mq * hours_per_m2
    wage = _hourly_rate_for("piastrellista")
    labor = [LaborItem("piastrellista", hours, wage)]

    return {
        "scope": "pavimento",
        "inputs": {"mq": mq, "formato": formato},
        "materials": [asdict(i) | {"total": i.total} for i in items],
        "labor": [asdict(l) | {"total": l.total} for l in labor],
        "subtotal_materials": round(sum(i.total for i in items), 2),
        "subtotal_labor": round(sum(l.total for l in labor), 2),
        "notes": ["Sfrido incluso", "Verificare planarità sottofondo", "Jolly/pezzi speciali esclusi"],
        "compliance_notes": ["Giunti di dilatazione secondo UNI 11493", "Verifica dislivelli massimi SOP"],
    }

# -------------------------
# Stime: Impianto elettrico
# -------------------------

def estimate_electric(
    punti_luce: int,
    punti_prese: int,
    punti_dati: int,
    punti_tv: int,
    metri_tracce: float,
    placche_moduli_media: int = 3
) -> Dict[str, Any]:

    # Materiali principali per punto
    # quantità per punto (medie prudenti)
    m_corrugato = 8.0   # m/punto (media canalizzazione)
    m_cavo = 12.0       # m/punto (n° conduttori e tratte)
    scatole_503 = max(0, punti_luce + punti_prese + punti_dati + punti_tv)  # semplificazione
    placche = ceil(scatole_503 * 1.0)  # una placca per scatola (moduli medi)

    # Prezzi dal DB
    p_corr = _price_for("tubi_corrugati", "m")
    p_cavo = _price_for("cavo_elettrico", "m")
    p_503 = _price_for("scatola_503", "pz")
    p_504 = _price_for("scatola_504", "pz")  # se serve
    p_frutti = _price_for("frutti_modulari", "pz")
    p_placca = _price_for("placca", "pz")
    p_cavo_tv = _price_for("cavo_tv", "m")
    p_cavo_dati = _price_for("cavo_dati", "m")

    items: List[LineItem] = []

    def add_item(code, desc, qty, unit, price, role=None):
        if price is None:
            price = 0.0
        items.append(LineItem(code, desc, qty, unit, float(price), role))

    # Quantità
    tot_punti = punti_luce + punti_prese + punti_dati + punti_tv
    add_item("EL-001", "Tubi corrugati Ø20-25", tot_punti * m_corrugato, "m", (p_corr or {}).get("price"))
    add_item("EL-002", "Cavo elettrico unipolare", (punti_luce + punti_prese) * m_cavo, "m", (p_cavo or {}).get("price"))
    if punti_tv > 0:
        add_item("EL-003", "Cavo coassiale TV", punti_tv * m_cavo, "m", (p_cavo_tv or {}).get("price"))
    if punti_dati > 0:
        add_item("EL-004", "Cavo dati Cat6", punti_dati * m_cavo, "m", (p_cavo_dati or {}).get("price"))
    add_item("EL-005", "Scatole incasso 503", scatole_503, "pz", (p_503 or {}).get("price"))
    add_item("EL-006", "Placche modulari", placche, "pz", (p_placca or {}).get("price"))
    # Frutti modulari: 1-3 per scatola a seconda della configurazione
    add_item("EL-007", "Frutti modulari (interr./prese dati/TV)", placche * placche_moduli_media, "pz", (p_frutti or {}).get("price"))

    # Manodopera: elettricista + muratore per tracce
    h_el = (
        punti_luce * ELECTRIC_PRODUCTIVITY["punto_luce"] +
        punti_prese * ELECTRIC_PRODUCTIVITY["punto_presa"] +
        punti_dati * ELECTRIC_PRODUCTIVITY["punto_dati"] +
        punti_tv * ELECTRIC_PRODUCTIVITY["punto_tv"]
    )
    h_mur = metri_tracce * ELECTRIC_PRODUCTIVITY["traccia_m"]

    labor = [
        LaborItem("elettricista", h_el, _hourly_rate_for("elettricista")),
        LaborItem("muratore", h_mur, _hourly_rate_for("muratore")),
    ]

    return {
        "scope": "impianto elettrico",
        "inputs": {
            "punti_luce": punti_luce,
            "punti_prese": punti_prese,
            "punti_dati": punti_dati,
            "punti_tv": punti_tv,
            "metri_tracce": metri_tracce,
        },
        "materials": [asdict(i) | {"total": i.total} for i in items],
        "labor": [asdict(l) | {"total": l.total} for l in labor],
        "subtotal_materials": round(sum(i.total for i in items), 2),
        "subtotal_labor": round(sum(l.total for l in labor), 2),
        "notes": ["Canalizzazioni e pozzetti ispezionabili dove necessario"],
        "compliance_notes": [
            "Sezioni minime cavi e protezioni secondo CEI 64-8",
            "Cavidotti adeguati al numero di conduttori e raggi di curvatura",
            "Quote prese TV/dati secondo capitolato",
        ],
    }

# -------------------------
# Stime: Impianto idrico
# -------------------------

def estimate_hydraulic(
    mq_abitazione: float,
    n_bagni: int,
    punti_idrici_extra: int,
    lunghezze: Dict[str, float] | None = None
) -> Dict[str, Any]:
    """
    lunghezze: dizionario facoltativo con metri per diametro (es. {"dn32": 12, "dn25": 28, "dn20": 60, "scarico50": 20, "scarico100": 10})
    Se non passato, stima proporzionale ai bagni e alla superficie.
    """
    lunghezze = lunghezze or {}
    # stima dorsali e diramazioni di default (molto prudenziale)
    dn32 = lunghezze.get("dn32", max(8.0, mq_abitazione * 0.10))
    dn25 = lunghezze.get("dn25", max(15.0, n_bagni * 8.0))
    dn20 = lunghezze.get("dn20", max(25.0, n_bagni * 15.0 + punti_idrici_extra * 4.0))
    scarico50 = lunghezze.get("scarico50", n_bagni * 8.0)
    scarico100 = lunghezze.get("scarico100", max(5.0, n_bagni * 6.0))

    # Prezzi
    p_dn32 = _price_for("tubo_pp_dn32", "m")
    p_dn25 = _price_for("tubo_pp_dn25", "m")
    p_dn20 = _price_for("tubo_pp_dn20", "m")
    p_racc = _price_for("racc_zincati", "pz")
    p_valv = _price_for("valvole", "pz")
    p_s50 = _price_for("scarico_dn50", "m")
    p_s100 = _price_for("scarico_dn100", "m")
    p_pvc_glue = _price_for("collante_pvc", "pz")

    items: List[LineItem] = []
    def add_item(code, desc, qty, unit, price, role=None):
        if price is None: price = 0.0
        items.append(LineItem(code, desc, qty, unit, float(price), role))

    # Quantità base
    add_item("IDR-001", "Tubo acqua DN32 (dorsale)", dn32, "m", (p_dn32 or {}).get("price"))
    add_item("IDR-002", "Tubo acqua DN25 (distribuz.)", dn25, "m", (p_dn25 or {}).get("price"))
    add_item("IDR-003", "Tubo acqua DN20 (utenze)", dn20, "m", (p_dn20 or {}).get("price"))
    add_item("IDR-004", "Raccordi/Curve/Tee pressare", ceil((dn32 + dn25 + dn20) * 0.2), "pz", (p_racc or {}).get("price"))
    add_item("IDR-005", "Valvole intercettazione", n_bagni * 2 + 2, "pz", (p_valv or {}).get("price"))
    add_item("IDR-006", "Scarico PVC DN50", scarico50, "m", (p_s50 or {}).get("price"))
    add_item("IDR-007", "Scarico PVC DN100", scarico100, "m", (p_s100 or {}).get("price"))
    add_item("IDR-008", "Collante PVC", ceil((scarico50 + scarico100) / 12), "pz", (p_pvc_glue or {}).get("price"))

    # Manodopera
    h_idr = n_bagni * HYDRAULIC_PRODUCTIVITY["bagno_completo"] + punti_idrici_extra * HYDRAULIC_PRODUCTIVITY["punto_idrico"]
    h_scarico = (scarico50 + scarico100) * HYDRAULIC_PRODUCTIVITY["scarico_m"]
    h_tubi = (dn20 + dn25 + dn32) * HYDRAULIC_PRODUCTIVITY["tubo_acqua_m"]

    labor = [
        LaborItem("idraulico", h_idr + h_tubi, _hourly_rate_for("idraulico")),
        LaborItem("muratore", h_scarico * 0.4, _hourly_rate_for("muratore")),  # piccole tracce/chiusure
    ]

    return {
        "scope": "impianto idrico",
        "inputs": {
            "mq_abitazione": mq_abitazione,
            "n_bagni": n_bagni,
            "punti_idrici_extra": punti_idrici_extra,
            "lunghezze": {"dn32": dn32, "dn25": dn25, "dn20": dn20, "scarico50": scarico50, "scarico100": scarico100},
        },
        "materials": [asdict(i) | {"total": i.total} for i in items],
        "labor": [asdict(l) | {"total": l.total} for l in labor],
        "subtotal_materials": round(sum(i.total for i in items), 2),
        "subtotal_labor": round(sum(l.total for l in labor), 2),
        "notes": ["Collettori e cassette d’ispezione escluse salvo indicazione"],
        "compliance_notes": [
            "Pendenze scarichi ≥ 1% (UNI EN 12056)",
            "Isolamento tubazioni ACS/AF dove necessario",
            "Valvole su ogni linea principale e prima degli apparecchi",
        ],
    }

# -------------------------
# Orchestratore generale
# -------------------------

def _sum_budget(chunks: List[Dict[str, Any]]) -> Dict[str, float]:
    m = sum(c["subtotal_materials"] for c in chunks)
    l = sum(c["subtotal_labor"] for c in chunks)
    return {"materials": round(m, 2), "labor": round(l, 2), "total": round(m + l, 2)}

@estimate_bp.route("", methods=["POST"])
def estimate():
    """
    Body JSON di esempio:
    {
      "abitazione_mq": 100,
      "pavimento": {"enabled": true, "mq": 100, "formato": "60x120"},
      "elettrico": {"enabled": true, "punti_luce": 50, "punti_prese": 35, "punti_dati": 12, "punti_tv": 6, "metri_tracce": 120},
      "idrico": {"enabled": true, "n_bagni": 2, "punti_idrici_extra": 3}
    }
    """
    data = request.get_json(force=True) or {}
    chunks: List[Dict[str, Any]] = []

    # PAVIMENTO
    pav = data.get("pavimento") or {}
    if pav.get("enabled"):
        mq = float(pav.get("mq") or data.get("abitazione_mq") or 0)
        fmt = (pav.get("formato") or "60x60").lower()
        chunks.append(estimate_flooring(mq, fmt))

    # ELETTRICO
    el = data.get("elettrico") or {}
    if el.get("enabled"):
        chunks.append(estimate_electric(
            punti_luce=int(el.get("punti_luce") or 0),
            punti_prese=int(el.get("punti_prese") or 0),
            punti_dati=int(el.get("punti_dati") or 0),
            punti_tv=int(el.get("punti_tv") or 0),
            metri_tracce=float(el.get("metri_tracce") or 0.0),
            placche_moduli_media=int(el.get("placche_moduli_media") or 3),
        ))

    # IDRICO
    idr = data.get("idrico") or {}
    if idr.get("enabled"):
        chunks.append(estimate_hydraulic(
            mq_abitazione=float(data.get("abitazione_mq") or idr.get("mq_abitazione") or 0.0),
            n_bagni=int(idr.get("n_bagni") or 1),
            punti_idrici_extra=int(idr.get("punti_idrici_extra") or 0),
            lunghezze=idr.get("lunghezze") or None,
        ))

    if not chunks:
        return jsonify({"error": "Nessun ambito attivato (pavimento/elettrico/idrico)."}), 400

    budget = _sum_budget(chunks)

    # Stima durata e squadre suggerite (grezza): 8h/giorno per persona
    total_hours = 0.0
    for ch in chunks:
        for l in ch.get("labor", []):
            total_hours += float(l["hours"])
    # ipotesi: 3 persone medie in parallelo
    crew_size = 3
    days = ceil(total_hours / (crew_size * 8.0)) if total_hours > 0 else 0

    # Applica margine aziendale al totale progetto
    net_total = float(budget.get("total", 0.0))
    m_pct, m_amt, total_with_margin = _apply_company_margin(net_total)

    return jsonify({
        "project": {
            "summary": {
                "crew_size_suggested": crew_size,
                "estimated_days": days,
                "total_hours": round(total_hours, 1),
            },
            "budget": budget,  # materiali/lavoro e totale netto
            "budget_margin": {
                "margin_pct": m_pct,
                "margin_amount": m_amt,
                "total_with_margin": total_with_margin
            }
        },
        "chunks": chunks
    }), 200

@estimate_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True})

# ------------------ Helpers comuni (preview) ------------------

UNIT_NORM = {
    "mq": "m2", "m²": "m2",
    "mc": "m3", "m³": "m3",
    "lt": "l",
    "ore": "h", "ora": "h",
    "pezzi": "pz", "pezzo": "pz",
    "ml": "m",
}

def _unit(u: str) -> str:
    if not u: return "pz"
    return UNIT_NORM.get(u.strip().lower(), u.strip().lower())


def _line(code: str|None, descr: str, um: str, qta: float, prezzo: float) -> Dict[str, Any]:
    tot = round(qta * prezzo, 2)
    return {"code": code, "descr": descr, "um": um, "qta": round(qta, 3), "prezzo": round(prezzo, 2), "totale": tot}


def _labor(role: str, ore: float, tariffa: float) -> Dict[str, Any]:
    return {"ruolo": role, "ore": round(ore, 2), "tariffa": round(tariffa, 2), "totale": round(ore*tariffa, 2)}


def _sum(rows: List[Dict[str, Any]], key: str = "totale") -> float:
    return round(sum((r.get(key) or 0) for r in rows), 2)



# ------------------ Listini regionali/città (con fallback) ------------------
# Usa PricelistDoc se presente: materials, wages, factors (es: {"historic_center":1.05})
from functools import lru_cache


def _db() -> Any:
    """Return a raw PyMongo Database handle.
    We prefer mongoengine.get_db() when available because it is already configured
    to use the same connection settings as the rest of the app.
    """
    if get_db is None:
        raise RuntimeError("Mongo DB handle not available (get_db is None)")
    return get_db()


def _get_material_by_sku_or_code(key: str):
    key = (key or "").strip()
    if not key:
        return None
    db = _db()
    # NO $or: two simple and reliable queries
    doc = db["materials"].find_one({"sku": key}, {"_id": 0})
    if doc:
        return doc
    return db["materials"].find_one({"code": key}, {"_id": 0})


def _material_name_unit(key: str) -> tuple[str, str]:
    doc = _get_material_by_sku_or_code(key) or {}
    name = doc.get("name") or key
    unit = doc.get("unit") or "pz"
    return str(name), _unit(str(unit))


def _material_unit_price(region: str | None, city: str | None, key: str, tags: list[str] | None = None) -> float:
    key = (key or "").strip()
    if not key:
        return 0.0
    tags = tags or []

    pl = _get_pricelist(region, city)
    factors = pl.get("factors", {}) or {}
    mul = _territorial_multiplier(region, pl)

    pl_price = float((pl.get("materials") or {}).get(key) or 0.0)
    doc = _get_material_by_sku_or_code(key) or {}
    cat_price = float(doc.get("unit_price_eur_2025") or 0.0)

    # Pricing mode:
    # - absolute: prefer explicit pricelist values when present
    # - multiplier: base is catalog; pricelist acts as per-code override
    if PRICING_MODE == "multiplier":
        base = pl_price if pl_price > 0 else cat_price
    else:
        base = pl_price if pl_price > 0 else cat_price

    if base > 0:
        return float(_apply_factors(round(base * mul, 4), factors, tags))

    return 0.0


@lru_cache(maxsize=128)
def _get_pricelist(region: str|None, city: str|None) -> dict:
    """Ritorna dict {materials, wages, factors}.
    Ordine di ricerca:
      1) (region, city)
      2) solo region (city assente/vuota)
      3) solo city
      4) fallback vuoto
    Supporta sia MongoEngine (PricelistDoc) sia raw PyMongo (db['pricelists']).
    """
    out = {"materials": {}, "wages": {}, "factors": {}, "multiplier": None, "pricing_mode": None}

    # 1) MongoEngine (PricelistDoc), se disponibile
    if PricelistDoc is not None:
        try:
            q = None
            if city and region:
                q = PricelistDoc.objects(region__iexact=region, city__iexact=city).first()
            if (q is None) and region:
                q = (PricelistDoc.objects(region__iexact=region, city__exists=False).first()
                     or PricelistDoc.objects(region__iexact=region, city__in=[None, ""]).first())
            if (q is None) and city:
                q = PricelistDoc.objects(city__iexact=city).first()
            if q:
                # PricelistDoc schema doesn't include multiplier by default; keep it optional.
                mul = getattr(q, "multiplier", None)
                pmode = getattr(q, "pricing_mode", None)
                return {
                    "materials": dict(getattr(q, "materials", {}) or {}),
                    "wages": dict(getattr(q, "wages", {}) or {}),
                    "factors": dict(getattr(q, "factors", {}) or {}),
                    "multiplier": float(mul) if isinstance(mul, (int, float)) else None,
                    "pricing_mode": str(pmode) if isinstance(pmode, str) and pmode.strip() else None,
                }
        except Exception:
            pass

    # 2) Raw PyMongo fallback (coerente con endpoints in work_catalog)
    if get_db is not None:
        try:
            db = get_db()
            def _find(filter_):
                return db["pricelists"].find_one(filter_, {"_id": 0}) or {}

            doc = {}
            if city and region:
                doc = _find({
                    "region": {"$regex": f"^{region}$", "$options": "i"},
                    "city": {"$regex": f"^{city}$", "$options": "i"}
                })
            if not doc and region:
                doc = _find({
                    "region": {"$regex": f"^{region}$", "$options": "i"},
                    "$or": [{"city": {"$exists": False}}, {"city": {"$in": [None, ""]}}]
                })
            if not doc and city:
                doc = _find({"city": {"$regex": f"^{city}$", "$options": "i"}})

            if doc:
                mul = doc.get("multiplier")
                if mul is None:
                    mul = doc.get("region_multiplier")
                pmode = doc.get("pricing_mode") or doc.get("mode")
                return {
                    "materials": dict(doc.get("materials") or {}),
                    "wages": dict(doc.get("wages") or {}),
                    "factors": dict(doc.get("factors") or {}),
                    "multiplier": float(mul) if isinstance(mul, (int, float)) else None,
                    "pricing_mode": str(pmode) if isinstance(pmode, str) and pmode.strip() else None,
                }
        except Exception:
            pass

    return out

def _apply_factors(base: float, factors: dict, tags: list[str]|None) -> float:
    if not base:
        return 0.0
    mul = 1.0
    for t in (tags or []):
        v = factors.get(t)
        if isinstance(v, (int, float)):
            mul *= float(v)
    return round(base * mul, 4)


def _territorial_multiplier(region: str | None, pricelist: dict) -> float:
    """Returns a multiplier to apply to base prices.

    Rules:
    - If the pricelist doc defines an explicit multiplier, always use it.
    - Else, if PRICING_MODE == "multiplier", use REGION_MULTIPLIERS mapping.
    - Otherwise ("absolute" mode), do not apply extra multipliers.
    """
    mul = pricelist.get("multiplier") if isinstance(pricelist, dict) else None
    if isinstance(mul, (int, float)) and mul > 0:
        return float(mul)

    if PRICING_MODE != "multiplier":
        return 1.0

    r = (region or "").strip().lower()
    return float(_REGION_MULTIPLIERS_LC.get(r, 1.0))

def _lookup_material_price_by_code(code: str) -> Optional[float]:
    """Fallback: risale a un Material in DB partendo dal codice preventivo.
    Prova in ordine: SKU esatti → code esatti → name contains (tutti i token).
    Ritorna unit_price_eur_2025 se trovato, altrimenti None.
    """
    if not code or MaterialDoc is None:
        return None

    keys = CODE_TO_MATERIAL_KEYS.get(code, [])
    if not keys:
        return None

    # 1) SKU esatti
    for k in keys:
        m = MaterialDoc.objects(sku__iexact=k).first()
        if m and getattr(m, "unit_price_eur_2025", None) is not None:
            return float(m.unit_price_eur_2025)

    # 2) code esatti
    for k in keys:
        m = MaterialDoc.objects(code__iexact=k).first()
        if m and getattr(m, "unit_price_eur_2025", None) is not None:
            return float(m.unit_price_eur_2025)

    # 3) name contains (tutti i token)
    for k in keys:
        tokens = [t for t in str(k).lower().split() if t]
        if not tokens:
            continue
        q = MaterialDoc.objects
        for t in tokens:
            q = q.filter(name__icontains=t)
        m = q.first()
        if m and getattr(m, "unit_price_eur_2025", None) is not None:
            return float(m.unit_price_eur_2025)

    return None


def price(code: str, default: float = 0.0, *, region: str|None=None, city: str|None=None, tags: list[str]|None=None) -> float:
    pl = _get_pricelist(region, city)
    val = None
    # 1) Pricelist override (treat 0/None as "no override")
    try:
        raw = (pl.get("materials") or {}).get(code)
        if isinstance(raw, (int, float)) and raw > 0:
            val = float(raw)
    except Exception:
        val = None

    # 2) Fallback via CODE→SKU/name mini-mappa
    if val is None:
        try:
            mapped = _lookup_material_price_by_code(code)
            if isinstance(mapped, (int, float)) and mapped > 0:
                val = float(mapped)
        except Exception:
            val = None

    # 3) Ultimo fallback diretto sul catalogo Materials (sku/code)
    if val is None:
        try:
            # use raw pymongo lookup to avoid $or edge-cases and keep behavior consistent
            doc = _get_material_by_sku_or_code(code)
            if doc and isinstance(doc.get("unit_price_eur_2025"), (int, float)):
                v = float(doc.get("unit_price_eur_2025") or 0.0)
                if v > 0:
                    val = v
        except Exception:
            val = None

    # 4) Default
    if val is None:
        val = default

    # 5) Apply territorial multiplier + factors
    mul = _territorial_multiplier(region, pl)
    return float(_apply_factors(val * mul, pl.get("factors", {}) or {}, tags))

def wage(role: str, default: float = 25.0, *, region: str|None=None, city: str|None=None, tags: list[str]|None=None) -> float:
    pl = _get_pricelist(region, city)
    val = None
    # 1) Pricelist regional wage (treat 0/None as missing)
    try:
        raw = (pl.get("wages") or {}).get(role)
        if isinstance(raw, (int, float)) and raw > 0:
            val = float(raw)
    except Exception:
        val = None

    # 2) Fallback WorkerDoc → hourly_rate
    if val is None:
        try:
            w = WorkerDoc.objects(role__icontains=role).first() if WorkerDoc is not None else None
            if w and getattr(w, "hourly_rate", None) is not None:
                val = float(w.hourly_rate)
        except Exception:
            val = None

    # 3) Default wage table
    if val is None:
        val = DEFAULT_WAGE.get(role, default)

    # 4) Apply territorial multiplier + factors
    mul = _territorial_multiplier(region, pl)
    return float(_apply_factors(val * mul, pl.get("factors", {}), tags))

def wage_for_work(code: str | None, role: str | None, default: float = 25.0, *, region: str|None=None, city: str|None=None, tags: list[str]|None=None) -> float:
    """Tariffa oraria: prima per work-code, poi per ruolo, poi WorkerDoc, poi default."""
    pl = _get_pricelist(region, city)
    val = None

    # 1) Wage indicizzata per work-code (es. 'ELEC_ROUGH')
    try:
        if code:
            raw = (pl.get("wages") or {}).get(code)
            if isinstance(raw, (int, float)) and raw > 0:
                val = float(raw)
    except Exception:
        val = None

    # 2) Wage indicizzata per ruolo (es. 'elettricista')
    if val is None:
        try:
            if role:
                raw = (pl.get("wages") or {}).get(role)
                if isinstance(raw, (int, float)) and raw > 0:
                    val = float(raw)
        except Exception:
            val = None

    # 3) WorkerDoc fallback
    if val is None:
        try:
            if role and WorkerDoc is not None:
                w = WorkerDoc.objects(role__icontains=role).first()
                if w and getattr(w, "hourly_rate", None) is not None:
                    val = float(w.hourly_rate)
        except Exception:
            val = None

    # 4) Default
    if val is None:
        if role and role in DEFAULT_WAGE:
            val = float(DEFAULT_WAGE[role])
        else:
            val = float(default)

    mul = _territorial_multiplier(region, pl)
    return float(_apply_factors(val * mul, pl.get("factors", {}), tags))

# ------------------ Auto-resolve geo & factors ------------------

def _multiply_factors(factors: dict, tags: List[str]|None) -> float:
    mul = 1.0
    for t in (tags or []):
        v = factors.get(t)
        if isinstance(v, (int, float)):
            mul *= float(v)
    return round(mul, 4)

def _resolve_geo_and_tags(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ritorna {region, city, applied_factors, factor_multiplier}.
    Precedenze:
      1) payload.region/city (+ tags opzionali: tags|factor_tags)
      2) project_id/cantiere_id/site_id -> geo + possibili tag fattori
      3) fallback: None/[]
    """
    region = data.get("region") or data.get("regione")
    city = data.get("city") or data.get("citta") or data.get("città")
    tags = list(data.get("tags") or data.get("factor_tags") or [])

    proj_id = data.get("project_id") or data.get("cantiere_id") or data.get("site_id")

    if (not region or not city) and proj_id:
        try:
            doc = None
            if ProjectDoc is not None:
                doc = ProjectDoc.objects(id=proj_id).first() or ProjectDoc.objects(project_id=proj_id).first()
            if doc is None and SiteDoc is not None:
                doc = SiteDoc.objects(id=proj_id).first() or SiteDoc.objects(site_id=proj_id).first()
            if doc:
                meta = getattr(doc, "meta", {}) or {}
                addr = getattr(doc, "address", {}) or getattr(doc, "site_address", {}) or {}
                region = region or meta.get("region") or meta.get("regione") or addr.get("region") or addr.get("regione")
                city = city or meta.get("city") or meta.get("citta") or meta.get("città") or addr.get("city") or addr.get("citta") or addr.get("città")
                maybe_tags = set()
                for key in ("tags","factor_tags","zone","flags","labels"):
                    val = getattr(doc, key, None) or meta.get(key)
                    if isinstance(val, (list, set, tuple)):
                        maybe_tags |= set(str(x).strip() for x in val if x)
                    elif isinstance(val, str):
                        maybe_tags |= set(s.strip() for s in val.split(",") if s.strip())
                if maybe_tags and not tags:
                    tags = list(maybe_tags)
        except Exception:
            pass

    pl = _get_pricelist(region, city) if (region or city) else {"factors": {}}
    factor_keys = set((pl.get("factors") or {}).keys())
    applied_factors = [t for t in (tags or []) if t in factor_keys]
    factor_multiplier = _multiply_factors(pl.get("factors", {}), applied_factors)

    return {
        "region": region,
        "city": city,
        "applied_factors": applied_factors,
        "factor_multiplier": factor_multiplier,
    }

# ------------------ Ricette semplici per le lavorazioni ------------------

def _recipe_from_item(label: str, qty: float, unit: str, region: str|None=None, city: str|None=None, tags: List[str] | None=None, meta: Dict[str, Any] | None=None) -> Dict[str, Any]:
    # Normalize inputs
    meta = meta or {}
    um = _unit(unit)
    mats: List[Dict[str, Any]] = []
    labor: List[Dict[str, Any]] = []

    # --- IMPORTANT ---
    # If the caller provides an explicit work code (e.g. meta={"code": "FLOOR_TILE"}),
    # we must use that code to resolve the work in the catalog and NOT fallback to
    # label-based heuristics (which can return legacy template codes like FLR-001/ADH-001).
    meta_code = (meta.get("code") or meta.get("work_code") or meta.get("catalog_code")) if isinstance(meta, dict) else None
    if isinstance(meta_code, str):
        meta_code = meta_code.strip() or None

    try:
        avg_m = float(meta.get("avg_distance_m") or 0)
    except Exception:
        avg_m = 0.0

    # Resolve catalog code and crew requirements (if present in DB)
    catalog_code = meta_code or _catalog_code_from_label(label, um)
    crew_req = _crew_requirements_for_code(catalog_code)

    # Fetch work catalog item once
    wc = _work_catalog_item(catalog_code)

    # If we successfully resolved a catalog work (especially via explicit meta_code),
    # prefer the catalog-driven recipe and skip legacy label-based heuristics.
    has_catalog_recipe = bool(wc) and (
        bool(meta_code) or bool(wc.get("materials_template")) or bool(wc.get("materials"))
    )

    # Lowercased label is only used for legacy heuristics
    lab = (label or "").lower()

    # Labor from work catalog productivity (if present)
    if wc:
        try:
            prod = float(wc.get("productivity_per_worker_per_hour") or 0)
        except Exception:
            prod = 0.0

        primary_role = wc.get("primary_role")
        if isinstance(primary_role, str):
            primary_role = primary_role.strip() or None

        if prod > 0 and qty > 0 and primary_role:
            hours = float(qty) / prod
            hr = wage_for_work(catalog_code, primary_role, region=region, city=city, tags=tags)
            labor.append(_labor(primary_role, hours, hr))

    def _elec_len_base(avg_m_val: float, factor: float = 1.0) -> float:
        # andata/ritorno + 10% scorta
        return round(max(avg_m_val, 0.0) * 2.0 * 1.10 * factor, 2)

    def _tube_len_base(avg_m_val: float, factor: float = 1.0) -> float:
        # piccola maggiorazione posa
        return round(max(avg_m_val, 0.0) * 1.05 * factor, 2)

    # Only run legacy heuristics if not has_catalog_recipe
    if not has_catalog_recipe:
        # 1) Posa piastrelle pavimento (qty in m2)
        if any(k in lab for k in ("posa piastrelle", "posa pavimento", "piastrelle")) and um == "m2":
            area = qty
            sfrido = 1.08  # 8% di sfrido
            mats.append(_line("FLR-001", "Piastrelle gres 60x60", "m2", area*sfrido, price("FLR-001", region=region, city=city, tags=tags)))
            # colla ~ 3.5 kg/m2
            mats.append(_line("ADH-001", "Colla per piastrelle", "kg", area*3.5, price("ADH-001", region=region, city=city, tags=tags)))
            # stucco ~ 0.15 kg/m2
            mats.append(_line("STU-001", "Stucco fughe", "kg", area*0.15, price("STU-001", region=region, city=city, tags=tags)))
            # manodopera ~ 0.7 h/m2
            labor.append(_labor("piastrellista", area*0.7, wage("piastrellista", region=region, city=city, tags=tags)))

        # 2) Battiscopa (qty in m)
        elif "battiscopa" in lab and um in ("m",):
            lung = qty
            mats.append(_line("BSK-001", "Battiscopa in gres", "m", lung, price("BSK-001", region=region, city=city, tags=tags)))
            # manodopera ~ 0.15 h/m
            labor.append(_labor("piastrellista", lung*0.15, wage("piastrellista", region=region, city=city, tags=tags)))

        # 3) Smaltimento macerie (qty in pz/sacchi)
        elif ("smaltimento" in lab or "macerie" in lab) and um in ("pz",):
            sacs = qty
            mats.append(_line("WAS-001", "Sacchi macerie 25kg", "pz", sacs, price("WAS-001", region=region, city=city, tags=tags)))
            # movimentazione ~ 0.25 h/sacco
            labor.append(_labor("manovale", sacs*0.25, wage("manovale", region=region, city=city, tags=tags)))

        # 4) Posa porta interna (qty in pz)
        elif ("porta" in lab and "posa" in lab) and um in ("pz",):
            pezzi = qty
            # falegname ~ 1.2 h/porta (solo manodopera in preview)
            labor.append(_labor("falegname", pezzi*1.2, wage("falegname", region=region, city=city, tags=tags)))

        # 5) Punto luce (qty in pz)
        elif (("punto luce" in lab) or ("punti luce" in lab) or ("luci" in lab) or (("elettric" in lab) and ("luce" in lab))) and um in ("pz",):
            punti = qty
            # materiale puntuale
            mats.append(_line("EL-PL", "Materiali punto luce", "pz", punti, price("EL-PL", region=region, city=city, tags=tags)))
            # metraggi se specificata distanza media
            if avg_m > 0:
                cavo_m = _elec_len_base(avg_m) * punti
                tubo_m = _tube_len_base(avg_m) * punti
                mats.append(_line("EL-CAVO-3G1.5", "Cavo 3G1.5", "m", cavo_m, price("EL-CAVO-3G1.5", region=region, city=city, tags=tags)))
                mats.append(_line("EL-TUBO-20", "Tubo corrugato Ø20", "m", tubo_m, price("EL-TUBO-20", region=region, city=city, tags=tags)))
                deriv = math.ceil(punti / 10.0)
                if deriv > 0:
                    mats.append(_line("EL-SCATOLA-DER", "Scatola derivazione", "pz", deriv, price("EL-SCATOLA-DER", region=region, city=city, tags=tags)))
            # manodopera
            labor.append(_labor("elettricista", punti*0.6, wage("elettricista", region=region, city=city, tags=tags)))

        # 6) Punto presa (qty in pz)
        elif (("punto presa" in lab) or ("punti presa" in lab) or ("prese" in lab) or (("elettric" in lab) and ("presa" in lab))) and um in ("pz",):
            punti = qty
            mats.append(_line("EL-PP", "Materiali punto presa", "pz", punti, price("EL-PP", region=region, city=city, tags=tags)))
            if avg_m > 0:
                cavo_m = _elec_len_base(avg_m) * punti
                tubo_m = _tube_len_base(avg_m) * punti
                mats.append(_line("EL-CAVO-3G2.5", "Cavo 3G2.5", "m", cavo_m, price("EL-CAVO-3G2.5", region=region, city=city, tags=tags)))
                mats.append(_line("EL-TUBO-20", "Tubo corrugato Ø20", "m", tubo_m, price("EL-TUBO-20", region=region, city=city, tags=tags)))
                mats.append(_line("EL-SCATOLA-503", "Scatola incasso 503", "pz", punti, price("EL-SCATOLA-503", region=region, city=city, tags=tags)))
                deriv = math.ceil(punti / 10.0)
                if deriv > 0:
                    mats.append(_line("EL-SCATOLA-DER", "Scatola derivazione", "pz", deriv, price("EL-SCATOLA-DER", region=region, city=city, tags=tags)))
            labor.append(_labor("elettricista", punti*0.55, wage("elettricista", region=region, city=city, tags=tags)))

        # 7) Impianto idrico bagno (pacchetto per bagno)
        elif ("impianto idrico bagno" in lab) and um in ("pz",):
            bagni = int(qty)
            mats.append(_line("IDR-BAGNO-PACK", "Kit impianto idrico bagno", "pz", bagni, price("IDR-BAGNO-PACK", region=region, city=city, tags=tags)))
            labor.append(_labor("idraulico", bagni*12.0, wage("idraulico", region=region, city=city, tags=tags)))

        # 7b) Punti idrici (qty in pz) con distanza opzionale
        elif ("punto idrico" in lab or "punti idrici" in lab or ("idric" in lab and "punto" in lab)) and um in ("pz",):
            punti = qty
            if avg_m > 0:
                ppr_m = round(avg_m * 2.0 * 1.10 * punti, 2)   # mandata+ritorno + scorta
                scarico_m = round(avg_m * 0.40 * punti, 2)     # quota default scarico
                mats.append(_line("IDR-TUBO-PPR-20", "Tubo PPR Ø20", "m", ppr_m, price("IDR-TUBO-PPR-20", region=region, city=city, tags=tags)))
                mats.append(_line("IDR-SCARICO-HT-50", "Scarico HT Ø50", "m", scarico_m, price("IDR-SCARICO-HT-50", region=region, city=city, tags=tags)))
                mats.append(_line("IDR-RACCORDI-PACK", "Kit raccordi", "pz", max(1, math.ceil(punti/2)), price("IDR-RACCORDI-PACK", region=region, city=city, tags=tags)))
            else:
                # fallback a pacchetto se non abbiamo lunghezze
                mats.append(_line("IDR-BAGNO-PACK", "Kit impianto idrico punto", "pz", punti, price("IDR-BAGNO-PACK", region=region, city=city, tags=tags)))
            labor.append(_labor("idraulico", punti * 1.20, wage("idraulico", region=region, city=city, tags=tags)))

    # Fallback generico: se non abbiamo materiali dalle regole euristiche,
    # prova a costruirli dal work_catalog (materials_template o materials)
    # NOTE: supporta più convenzioni di chiavi (um/unit, descr/name/description, qty_per_unit/qty_per_m, ecc.)
    if wc and not mats:
        # 1) preferisci materials_template (più ricco), poi fallback su materials
        template = wc.get("materials_template")
        mats_src = template if isinstance(template, list) and template else wc.get("materials")

        def _pick(d: dict, *keys, default=None):
            for k in keys:
                if k in d and d.get(k) not in (None, ""):
                    return d.get(k)
            return default

        def _as_float(x, default=0.0):
            try:
                if x is None:
                    return default
                if isinstance(x, (int, float)):
                    return float(x)
                s = str(x).strip().replace(",", ".")
                return float(s)
            except Exception:
                return default

        def _normalize_um(u: Any) -> str:
            return _unit(str(u or "pz"))

        rows: List[dict] = []

        # A) formato lista di dict: [{code/sku, descr, um/unit, qty_per_unit}, ...]
        if isinstance(mats_src, list):
            for m in mats_src:
                if not isinstance(m, dict):
                    continue

                code = str(_pick(m, "sku", "code", "material_code", "material", "id") or "").strip()
                if not code:
                    continue

                qty_per_unit = _as_float(
                    _pick(
                        m,
                        "qty_per_unit", "qty_per_m", "qty_per_m2", "qty_unit",
                        "qta_per_unit", "qta_per_m", "qta_per_m2",
                        default=0.0,
                    ),
                    0.0,
                )
                if qty_per_unit <= 0:
                    continue

                # Enrich from materials catalog (name/unit) but let template override when present
                cat_name, cat_unit = _material_name_unit(code)

                descr = str(_pick(m, "descr", "description", "name", "label", default="") or "").strip()
                if not descr:
                    descr = str(cat_name)

                um_raw = _pick(m, "um", "unit", "uom", default="")
                um_m = _normalize_um(um_raw) if (um_raw not in (None, "")) else cat_unit
                if not um_m:
                    um_m = cat_unit

                qta = float(qty) * float(qty_per_unit)

                # Price: prefer pricelist override for this region/city; fallback to materials catalog
                prezzo = _material_unit_price(region, city, code, tags=tags)

                rows.append(_line(code, descr, um_m, qta, float(prezzo or 0.0)))

        # B) formato dict: {"MAT-001": 0.2, "MAT-002": 1.5, ...}
        elif isinstance(mats_src, dict):
            for code, qty_per_unit in mats_src.items():
                code = str(code or "").strip()
                if not code:
                    continue

                qpu = _as_float(qty_per_unit, 0.0)
                if qpu <= 0:
                    continue

                qta = float(qty) * float(qpu)

                cat_name, cat_unit = _material_name_unit(code)
                descr = str(cat_name)
                um_m = cat_unit

                prezzo = _material_unit_price(region, city, code, tags=tags)

                rows.append(_line(code, descr, um_m, qta, float(prezzo or 0.0)))

        # Se abbiamo prodotto righe materiali dal catalogo, usale
        if rows:
            mats.extend(rows)

    # --- EXTRA: ELEC_FIXTURE con avg_distance_m (aggiunge materiali lineari) ---
    if catalog_code == "ELEC_FIXTURE" and um == "pz" and avg_m > 0:
        existing = set((r.get("code") or "").strip() for r in mats if isinstance(r, dict))

        def _elec_len_base(avg_m_val: float, factor: float = 1.0) -> float:
            # andata/ritorno + 10% scorta
            return round(max(avg_m_val, 0.0) * 2.0 * 1.10 * factor, 2)

        def _tube_len_base(avg_m_val: float, factor: float = 1.0) -> float:
            # piccola maggiorazione posa
            return round(max(avg_m_val, 0.0) * 1.05 * factor, 2)

        punti = float(qty)

        # Usa SKU del catalogo materiali (seed/materials.json)
        # (evitiamo codici legacy tipo EL-* che possono non esistere in DB)
        cavo_code = "FG1615"   # Cavo FG16OR 3x1,5
        tubo_code = "TC25"     # Tubo corrugato Ø25
        scat_code = "SC503"    # Scatola 503
        der_code  = None        # (non presente nel catalogo seed)

        cavo_m = _elec_len_base(avg_m) * punti
        tubo_m = _tube_len_base(avg_m) * punti

        if cavo_code not in existing and cavo_m > 0:
            name, unit_cat = _material_name_unit(cavo_code)
            prezzo = _material_unit_price(region, city, cavo_code, tags=tags)
            mats.append(_line(cavo_code, name, unit_cat, cavo_m, prezzo))

        if tubo_code not in existing and tubo_m > 0:
            name, unit_cat = _material_name_unit(tubo_code)
            prezzo = _material_unit_price(region, city, tubo_code, tags=tags)
            mats.append(_line(tubo_code, name, unit_cat, tubo_m, prezzo))

        # scatole incasso (1 per punto)
        if scat_code not in existing and punti > 0:
            name, unit_cat = _material_name_unit(scat_code)
            prezzo = _material_unit_price(region, city, scat_code, tags=tags)
            mats.append(_line(scat_code, name, unit_cat, punti, prezzo))

        # scatola derivazione ogni ~10 punti
        # Se in futuro aggiungi una scatola derivazione a catalogo, puoi riattivare questa parte.

    # Se non siamo riusciti a produrre nessuna riga (né materiali né manodopera),
    # NON ritorniamo una preview "vuota": mettiamo almeno una riga placeholder
    # con warning, così il frontend non mostra preventivi completamente vuoti.
    if not mats and not labor:
        mats.append(_line(None, f"{label} (non riconosciuto: verifica catalogo/sinonimi)", um, qty, 0.0))
        assumptions = {
            "warning": "Voce non riconosciuta dal catalogo: è stata inserita come placeholder (prezzi a 0).",
            "suggestion": "Aggiungi sinonimi nel work_catalog o passa meta.code per forzare il match.",
        }
    else:
        assumptions = None

    subtotal = _sum(mats) + _sum(labor)
    return {
        "materials": mats,
        "labor": labor,
        "subtotal": subtotal,
        "ready_to_commit": False,
        "assumptions": assumptions,
        "work_code": catalog_code,
        "crew_requirements": crew_req,
    }


# ------------------ Endpoint di preview ------------------
@estimate_bp.post("/preview")
def estimate_preview():
    """Genera anteprima per 1..N voci:
       Input: { items:[{label, qty, unit}], ... } oppure { parsed_items:[...] }.
       Output: { items:[{materials[], labor[], subtotal, ready_to_commit}], grand_total }.
    """
    data = request.get_json(force=True) or {}
    _t0 = time.perf_counter()
    items = data.get("items") or data.get("parsed_items") or []
    ctx = _resolve_geo_and_tags(data)
    region = ctx.get("region")
    city = ctx.get("city")
    tags = ctx.get("applied_factors") or []

    raw_text = (data.get("text") or "") if isinstance(data.get("text"), str) else ""

    # If region/city is not provided by the caller/router, try to infer region from raw text (e.g. "in Sicilia")
    if raw_text and not region:
        rt = raw_text.lower()
        _region_map = {k.lower(): k for k in REGION_MULTIPLIERS.keys()}
        for r_lc, r_name in _region_map.items():
            if r_lc in rt:
                region = r_name
                ctx["region"] = region
                break

    # Special handling for natural-language plumbing requests.
    # Chat users often write a full sentence; parse_multi would extract the first number (e.g. "2") and lose "100 mq".
    # Here we build 2 catalog items explicitly: rough pipes (m) + fixtures (pz).
    if raw_text:
        rt = raw_text.lower()
        if ("impianto idrico" in rt) or ("impianto idraul" in rt):
            m_mq = re.search(r"(\d+)\s*mq", rt)
            mq = int(m_mq.group(1)) if m_mq else 0
            m_b = re.search(r"(\d+)\s*bagni?", rt)
            n_bagni = int(m_b.group(1)) if m_b else 1

            # Explainable heuristic for piping length
            if mq > 0:
                rough_m = max(30.0, (0.70 * float(mq)) + (max(n_bagni, 1) - 1) * 15.0)
            else:
                rough_m = 45.0 + (max(n_bagni, 1) - 1) * 15.0

            items = [
                {"label": "Impianto idraulico - tubazioni", "qty": round(rough_m, 1), "unit": "m", "meta": {"code": "PLUMB_ROUGH"}},
                {"label": "Montaggio sanitari e rubinetteria", "qty": float(max(n_bagni, 1)), "unit": "pz", "meta": {"code": "PLUMB_FIXTURE"}},
            ]

    # Supporto rapido: se arriva solo del testo, prova a usare il parser della chat
    if not items and data.get("text"):
        try:
            from utils.message_parser import parse_multi as _pm
            items = _pm(data["text"]) or []
        except Exception:
            items = []

    if not isinstance(items, list) or not items:
        return jsonify({"error": "Nessuna voce da stimare"}), 422

    out_items: List[Dict[str, Any]] = []
    grand = 0.0
    for it in items:
        label = (it.get("label") or "voce").strip()
        qty = float(it.get("qty") or 1.0)
        unit = _unit(it.get("unit") or "pz")
        comp = _recipe_from_item(label, qty, unit, region=region, city=city, tags=tags, meta=it.get("meta") or {})
        comp["label"] = label
        comp["applied_factors"] = list(tags)
        # struttura tabelle UI (columns/rows) già pronte per il frontend
        comp["materials"] = {
            "columns": ["code", "descr", "um", "qta", "prezzo", "totale"],
            "rows": comp["materials"],
        }
        comp["labor"] = {
            "columns": ["ruolo", "ore", "tariffa", "totale"],
            "rows": comp["labor"],
        }
        out_items.append(comp)
        grand += float(comp.get("subtotal") or 0)

    # Calcolo margine aziendale
    net_subtotal = round(grand, 2)
    m_pct, m_amt, total_with_margin = _apply_company_margin(net_subtotal)

    ui_tables = {
        "items": out_items,
        "subtotal": net_subtotal,
        "margin_pct": m_pct,
        "margin_amount": m_amt,
        "grand_total": total_with_margin,
        "notes": "Anteprima non vincolante",
    }

    payload = {
        "ui_tables": ui_tables,
        # campi legacy per retro-compatibilità
        "items": out_items,
        "grand_total": total_with_margin,
        "summary": "Anteprima non vincolante",
        "pricing_context": ctx | {"margin_pct": m_pct},
    }
    try:
        from backend.utils.telemetry import log_estimate_quality
        log_estimate_quality({
            "region": region, "city": city,
            "factors": tags,
            "items_count": len(out_items),
            "grand_total": total_with_margin,
            "source": "preview",
            "latency_ms": int((time.perf_counter()-_t0)*1000) if "_t0" in locals() else None,
            "parse_ok": True, "had_error": False,
        })
    except Exception:
        pass
    return jsonify(payload), 200

# -------------------------
# Parser "frase libera" -> stima
# -------------------------
import re

def make_estimate_from_text(text: str) -> Dict[str, Any]:
    """
    Converte frasi libere tipo:
      "ristrutturazione di 120 mq, 2 bagni, 60 punti luce, impianto idrico completo e pavimento in gres 60x120"
    in un payload di stima e calcola la stima usando le funzioni sopra.

    Ritorna lo stesso schema di /api/estimate.
    """

    if not text or not isinstance(text, str):
        return {"error": "Testo non valido per la stima."}

    t = text.lower()

    # --- estrazioni base ---
    def _pick_int(pat, default=0):
        m = re.search(pat, t)
        return int(m.group(1)) if m else default

    def _pick_float(pat, default=0.0):
        m = re.search(pat, t)
        return float(m.group(1)) if m else default

    # mq
    mq = _pick_int(r"(\d+)\s*mq", default=0)

    # bagni
    n_bagni = _pick_int(r"(\d+)\s*bagni?", default=1)

    # elettrico: punti
    punti_luce = _pick_int(r"(\d+)\s*punti\s*luce", default=0)
    punti_prese = _pick_int(r"(\d+)\s*(punti\s*)?prese?", default=0)
    punti_dati  = _pick_int(r"(\d+)\s*(punti\s*)?(dati|ethernet)", default=0)
    punti_tv    = _pick_int(r"(\d+)\s*(punti\s*)?tv", default=0)

    # formato piastrelle (cattura 60x120, 60x60, ecc.)
    m_fmt = re.search(r"(?:gres|piastrell[ae]).*?(\d+)\s*x\s*(\d+)", t)
    formato = None
    if m_fmt:
        w = m_fmt.group(1)
        h = m_fmt.group(2)
        formato = f"{w}x{h}"

    # impianto idrico presente?
    has_idrico = ("impianto idrico" in t) or ("idrico completo" in t) or ("idraulico" in t)

    # metri di tracce (opzionale). Se non indicato, stima grossolana.
    metri_tracce = _pick_float(r"(\d+)\s*m(?:etri)?\s*tracc", default=0.0)

    # --- default intelligenti se l'utente non li ha detti ---
    if mq and not metri_tracce:
        # euristico: ~ 1.0*mq + 0.5*(tot punti) metri di traccia
        tot_punti = punti_luce + punti_prese + punti_dati + punti_tv
        metri_tracce = round(1.0 * mq + 0.5 * tot_punti, 1)

    if punti_luce and not punti_prese:
        # se non specifica prese: assumiamo ~0.8 prese per punto luce
        punti_prese = int(round(punti_luce * 0.8))

    if not punti_tv and (punti_luce or punti_prese):
        # minimo 2 punti TV se impianto elettrico c'è
        punti_tv = 2

    # pavimenti abilitati se cita gres/piastrelle o se ha dato mq
    pav_enabled = bool(mq) and (("gres" in t) or ("piastrell" in t))

    # elettrico abilitato se ha citato punti o “impianto elettrico”
    el_enabled = any([punti_luce, punti_prese, punti_dati, punti_tv]) or ("impianto elettrico" in t)

    # idrico abilitato se ha citato l’impianto o i bagni
    idr_enabled = has_idrico or ("bagni" in t) or ("bagno" in t)

    # --- costruzione "chunks" chiamando le funzioni già presenti ---
    chunks: List[Dict[str, Any]] = []

    if pav_enabled:
        fmt = (formato or "60x60")
        chunks.append(estimate_flooring(float(mq), fmt))

    if el_enabled:
        chunks.append(estimate_electric(
            punti_luce=int(punti_luce),
            punti_prese=int(punti_prese),
            punti_dati=int(punti_dati),
            punti_tv=int(punti_tv),
            metri_tracce=float(metri_tracce),
            placche_moduli_media=3,
        ))

    if idr_enabled:
        # punti idrici extra non citati -> 0 (ci pensano i bagni)
        chunks.append(estimate_hydraulic(
            mq_abitazione=float(mq or 0.0),
            n_bagni=int(n_bagni or 1),
            punti_idrici_extra=0,
            lunghezze=None,
        ))

    if not chunks:
        return {"error": "Non ho trovato elementi sufficienti (mq/bagni/impianti) per stimare."}

    budget = _sum_budget(chunks)

    # durata grezza (8h/giorno/persona)
    total_hours = 0.0
    for ch in chunks:
        for l in ch.get("labor", []):
            total_hours += float(l["hours"])
    crew_size = 3
    days = ceil(total_hours / (crew_size * 8.0)) if total_hours > 0 else 0

    return {
        "project": {
            "summary": {
                "crew_size_suggested": crew_size,
                "estimated_days": days,
                "total_hours": round(total_hours, 1),
            },
            "budget": budget,
        },
        "chunks": chunks
    }

# -------------------------
# Helper: usa ENTITIES della chat -> stima DB-based (se applicabile)
# -------------------------
def estimate_from_entities(entities: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Usa le entità estratte dal router per calcolare una stima DB-based.
    Supporta:
      - Pavimenti (qty+unit=m2, dimensioni/formato opzionali)
      - Elettrico (punti_luce/prese/dati/tv + metri_tracce)
      - Idrico (n_bagni [+ opzionale qty come mq_abitazione])
    Ritorna un "chunk" (come quelli prodotti dalle funzioni estimate_*), oppure None.
    """
    def _as_float(x):
        try:
            return float(str(x).replace(",", "."))
        except Exception:
            return None

    def _as_int(x):
        try:
            return int(x)
        except Exception:
            return None

    # --- normalizzazioni base ---
    qty  = _as_float(entities.get("qty"))
    unit = (entities.get("unit") or "").strip().lower()
    if unit in ("mq", "m²", "m^2"):
        unit = "m2"

    voce = (entities.get("voce_lavoro") or "").lower()
    dims = entities.get("dimensioni") or []
    if isinstance(dims, str):
        dims = [dims]

    # ============== 1) PAVIMENTO ==============
    if qty and unit == "m2" and (("pav" in voce) or ("gres" in voce) or ("piastrell" in voce) or dims):
        formato = str(dims[0]).lower() if dims else "60x60"
        return estimate_flooring(qty, formato)

    # ============== 2) ELETTRICO ==============
    # Richiede almeno alcuni punti e i metri di tracce
    pl = _as_int(entities.get("punti_luce"))
    pr = _as_int(entities.get("punti_prese"))
    pd = _as_int(entities.get("punti_dati"))
    tv = _as_int(entities.get("punti_tv"))
    mt = _as_float(entities.get("metri_tracce"))

    # se ha dato solo mq ma non mt, prova euristica mt ≈ 1.0*mq + 0.5*(punti totali)
    if (mt is None or mt == 0) and qty:
        tot_punti = (pl or 0) + (pr or 0) + (pd or 0) + (tv or 0)
        if tot_punti > 0:
            mt = round(1.0 * qty + 0.5 * tot_punti, 1)

    if any(x is not None for x in (pl, pr, pd, tv)) and mt is not None:
        return estimate_electric(
            punti_luce=int(pl or 0),
            punti_prese=int(pr or 0),
            punti_dati=int(pd or 0),
            punti_tv=int(tv or 0),
            metri_tracce=float(mt or 0.0),
            placche_moduli_media=3,
        )

    # ============== 3) IDRICO ==============
    nb = _as_int(entities.get("n_bagni"))
    if nb is not None:  # anche se 0 → comunque non stimiamo; serve almeno 1 bagno
        if nb <= 0:
            return None
        return estimate_hydraulic(
            mq_abitazione=float(qty or 0.0),  # se qty è m2 della casa lo usiamo, altrimenti 0
            n_bagni=int(nb or 1),
            punti_idrici_extra=int(_as_int(entities.get("punti_idrici_extra")) or 0),
            lunghezze=None,
        )

    return None