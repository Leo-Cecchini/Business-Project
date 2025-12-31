
from __future__ import annotations
import re
from typing import List, Dict, Optional, Tuple

def _to_float_local(s: str) -> float:
    if "," in s and s.count(".") >= 1:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        m = re.search(r"\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else 1.0

SEP = re.compile(r'(?:^|\n|\r|;)\s*(?:[-•*]\s*|\(?\d+\)?[.)]\s*)?')

QTY_UNIT = re.compile(r'(?ix)'
    r'(?P<count>\d+(?:[\.,]\d+)?)'
    r'\s*(?:x|\*)?\s*(?P<count2>\d+(?:[\.,]\d+)?)?'
    r'\s*(?P<unit>m2|m3|mq|mc|m|ml|pz|n°|nr|h|ore?|kg|l|lt|litri|litro|pezzi|pezzo|metri\s+quadri|metri\s+cubi)?'
)

COUNT_PREFIX = re.compile(r'(?i)\b(nr|n°)\s*(\d+)\b')

UNIT_MAP = {
    "m":"m","ml":"m","metro":"m","metri":"m",
    "mq":"m2","m²":"m2","m2":"m2","metri quadri":"m2",
    "mc":"m3","m³":"m3","m3":"m3","metri cubi":"m3",
    "pz":"pz","pezzo":"pz","pezzi":"pz","n":"pz","nr":"pz","n°":"pz",
    "h":"h","ore":"h","ora":"h",
    "kg":"kg",
    "l":"l","lt":"l","litro":"l","litri":"l",
}

def _norm_unit(u: Optional[str]) -> str:
    if not u:
        return "pz"
    u = u.strip().lower()
    return UNIT_MAP.get(u, "pz")

def _clean_label(s: str, remove_span: Optional[Tuple[int,int]]) -> str:
    s = s.strip()
    if remove_span:
        i, j = remove_span
        s = (s[:i] + " " + s[j:]).strip()
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip(" -:.,")

def split_candidates(text: str) -> List[str]:
    parts = [p.strip() for p in SEP.split(text) if p and p.strip()]
    merged: List[str] = []
    for p in parts:
        if merged and len(p) < 3:
            merged[-1] = (merged[-1] + " " + p).strip()
        else:
            merged.append(p)
    return merged

def parse_multi(text: str) -> List[Dict]:
    items: List[Dict] = []
    if not text or not text.strip():
        return items
    for seg in split_candidates(text):
        m = QTY_UNIT.search(seg)
        qty = 1.0; unit = "pz"; span = None
        if m and m.group("count"):
            qty = _to_float_local(m.group("count"))
            if m.group("count2"):
                qty *= _to_float_local(m.group("count2"))
            unit = _norm_unit(m.group("unit"))
            span = m.span()
        else:
            m2 = COUNT_PREFIX.search(seg)
            if m2:
                qty = _to_float_local(m2.group(2))
                unit = "pz"
                span = m2.span()
        label = _clean_label(seg, span)
        if not label:
            continue
        items.append({"label": label, "qty": float(qty), "unit": unit})
    return items

def parse_bundle(text: str) -> dict:
    return {"items": parse_multi(text), "raw_text": text}
