# utils/numparse.py
"""
Parser robusto per numeri, unità e prezzi nel dominio edile.
- Estrae quantità (m, m2, m3, kg, pezzi, h/giorni)
- Estrae prezzi (€, €/m2, €/m3, €/h)
- Estrae formati (es. 60x60, 20x20x50) e spessori (cm/mm -> mm)
- Normalizza separatori decimali (virgola/punto)
"""

from __future__ import annotations
from typing import List, Dict, Tuple, Optional
import re

# ----------------- Regex principali -----------------
NUM_UNIT_RX = re.compile(
    r"""(?P<val>\d{1,3}(?:[\.\s]\d{3})*(?:[\,\.]\d+)?|\d+(?:[\,\.]\d+)?)\s*
        (?P<unit>m2|mq|m³|m3|m|kg|pezzi|pz|h|ore|giorni)""",
    re.IGNORECASE | re.VERBOSE
)

PRICE_RX = re.compile(
    r"""(?P<val>\d{1,3}(?:[\.\s]\d{3})*(?:[\,\.]\d+)?|\d+(?:[\,\.]\d+)?)\s*
        (?P<unit>€|eur|€/m2|€/mq|€/m3|€/h)""",
    re.IGNORECASE | re.VERBOSE
)

DIM_RX = re.compile(r"\b(\d{2,3})\s*[x×]\s*(\d{2,3})(?:\s*[x×]\s*(\d{2,3}))?\b")
THICK_RX = re.compile(r"(\d{1,3})\s*(mm|cm)\b", re.IGNORECASE)

def _norm_float(s: str) -> float:
    s = s.replace(".", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def _norm_unit(u: str) -> str:
    u = (u or "").lower()
    u = u.replace("m²", "m2").replace("mq", "m2").replace("m³", "m3")
    u = u.replace("ore", "h").replace("eur", "€").replace("€/mq", "€/m2")
    return u

def parse_numbers(text: str) -> List[Dict]:
    """Ritorna lista di match con numeri+unità generiche (m, m2, m3, kg, pezzi/pz, h, giorni)."""
    out = []
    for m in NUM_UNIT_RX.finditer(text or ""):
        val = _norm_float(m.group("val"))
        unit = _norm_unit(m.group("unit"))
        if val is not None:
            out.append({"value": val, "unit": unit, "raw": m.group(0)})
    return out

def parse_prices(text: str) -> List[Dict]:
    """Ritorna lista di prezzi e tariffe (€ semplice o €/m2, €/m3, €/h)."""
    out = []
    for m in PRICE_RX.finditer(text or ""):
        val = _norm_float(m.group("val"))
        unit = _norm_unit(m.group("unit"))
        if val is not None:
            out.append({"value": val, "unit": unit, "raw": m.group(0)})
    return out

def parse_dimensions(text: str) -> List[str]:
    """Ritorna formati tipo '60x60' o '20x20x50' come stringhe normalizzate '60x60'."""
    out = []
    for m in DIM_RX.finditer(text or ""):
        parts = [p for p in m.groups() if p]
        out.append("x".join(parts))
    return out

def parse_thickness_mm(text: str) -> Optional[int]:
    """Ritorna lo spessore in millimetri se presente (cm/mm -> mm)."""
    for m in THICK_RX.finditer(text or ""):
        val = _norm_float(m.group(1))
        unit = m.group(2).lower()
        if val is None:
            continue
        if unit == "cm":
            return int(round(val * 10))
        return int(round(val))
    return None

def quick_extract(text: str) -> Dict:
    """Estrattore veloce combinato: qty principale, unità, prezzo/tariffa, dimensioni, spessori."""
    nums = parse_numbers(text)
    prices = parse_prices(text)
    dims = parse_dimensions(text)
    thick = parse_thickness_mm(text)

    # euristica: se presente una misura in m2/m3 prende quella come qty principale
    qty = None; unit = None
    for n in nums:
        if n["unit"] in ("m2", "m3"):
            qty = n["value"]
            unit = n["unit"]
            break
    if qty is None and nums:
        qty = nums[0]["value"]
        unit = nums[0]["unit"]

    # euristica: preferisci €/m2/€/m3/€/h, altrimenti €
    price_value = None; price_unit = None
    for p in prices:
        if p["unit"] in ("€/m2","€/m3","€/h"):
            price_value, price_unit = p["value"], p["unit"]
            break
    if price_value is None and prices:
        price_value, price_unit = prices[0]["value"], prices[0]["unit"]

    return {
        "qty": qty,
        "unit": unit,
        "price": price_value,
        "price_unit": price_unit,
        "dimensions": dims,
        "thickness_mm": thick,
        "raw_numbers": nums,
        "raw_prices": prices,
    }
