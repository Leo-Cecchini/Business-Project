# utils/price_extractor.py
import re
from typing import List, Dict, Optional

EUR = r"(?:€|\beuro\b)"
NUM = r"(?:\d{1,3}(?:[.,]\d{3})*[.,]\d+|\d+)"
UNITS = {"kg":"kg","m3":"m3","mc":"m3"}

PATTERNS = [
    re.compile(rf"{EUR}\s*({NUM})\s*/\s*(kg|m3|mc)", re.IGNORECASE),
    re.compile(rf"({NUM})\s*{EUR}\s*/\s*(kg|m3|mc)", re.IGNORECASE),
    re.compile(rf"{EUR}\s*({NUM})\s*(kg|m3|mc)", re.IGNORECASE),
]

def _to_float(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))

def _unit(u: str) -> str:
    return UNITS.get(u.lower(), u.lower())

def extract_prices(text: str) -> List[Dict]:
    found = []
    for pat in PATTERNS:
        for m in pat.finditer(text or ""):
            found.append({"value": _to_float(m.group(1)), "unit": _unit(m.group(2))})
    return found

def pick_best(prices: List[Dict], prefer_unit: str = "kg") -> Optional[Dict]:
    c = [p for p in prices if p["unit"] == prefer_unit] or prices
    if not c: return None
    vals = sorted(p["value"] for p in c)
    mid = len(vals)//2
    med = vals[mid] if len(vals)%2==1 else (vals[mid-1]+vals[mid])/2
    return {"value": round(med, 2), "unit": c[0]["unit"]}