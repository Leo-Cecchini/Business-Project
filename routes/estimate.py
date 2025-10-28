# routes/estimate.py
from __future__ import annotations
from math import ceil
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional
from flask import Blueprint, request, jsonify, g, current_app

from models import db
from models.material import Material
from models.worker import Worker

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

# -------------------------
# Util: ricerca prezzi nel DB
# -------------------------

def _db_price(name_tokens: List[str], prefer_unit: Optional[str]=None) -> Optional[Dict[str, Any]]:
    """
    Cerca nel DB Material dove name contiene TUTTI i token.
    Se prefer_unit è indicato (es. 'm2','m','pz','kg'), priorizza risultati con quella unità.
    """
    if not name_tokens:
        return None

    # query iniziale ampia
    q = Material.query
    for tok in name_tokens:
        q = q.filter(Material.name.ilike(f"%{tok}%"))
    results = q.order_by(Material.unit.asc()).all()
    if not results:
        return None

    # scoring semplice: +2 se unit combacia, +1 se name inizia con primo token
    def score(m: Material) -> int:
        s = 0
        if prefer_unit and (m.unit or "").lower() == prefer_unit.lower():
            s += 2
        if (m.name or "").lower().startswith(name_tokens[0].lower()):
            s += 1
        return s

    results.sort(key=score, reverse=True)
    best = results[0]
    return {
        "name": best.name,
        "unit": best.unit,
        "price": best.unit_price_eur_2025,
        "raw": best.to_dict()
    }

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
# Calcolo manodopera (da DB o default)
# -------------------------

def _hourly_rate_for(role: str) -> float:
    w = Worker.query.filter(Worker.role.ilike(f"%{role}%")).first()
    if w and w.hourly_rate:
        return float(w.hourly_rate)
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

    return jsonify({
        "project": {
            "summary": {
                "crew_size_suggested": crew_size,
                "estimated_days": days,
                "total_hours": round(total_hours, 1),
            },
            "budget": budget,
        },
        "chunks": chunks
    }), 200

@estimate_bp.route("/ping", methods=["GET"])
def ping():
    return jsonify({"ok": True})

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