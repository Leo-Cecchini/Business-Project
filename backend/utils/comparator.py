# utils/comparator.py
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

# -----------------------
# Datamodel per evidenze
# -----------------------
@dataclass
class Evidence:
    value: float | None         # numerico se disponibile, altrimenti None
    unit: str | None            # es. "kg", "m3", "€/kg", "giorni"
    label: str | None           # categoria/descrizione
    source: str                 # titolo/URL/documento
    raw_snippet: str = ""       # per debug/tooltip

# -----------------------
# Normalizzazioni base
# -----------------------
UNIT_ALIASES = {
    "mc": "m3",
    "€/mc": "€/m3",
    "euro/kg": "€/kg",
    "euro/m3": "€/m3",
    "giorno": "giorni",
    "settimana": "settimane",
    "mese": "mesi",
    "ora": "ore",
}

def norm_unit(u: Optional[str]) -> Optional[str]:
    if not u:
        return u
    u = u.strip().lower()
    return UNIT_ALIASES.get(u, u)

# -----------------------
# Estrazione numerica
# -----------------------
NUM = r"(?:\d{1,3}(?:[.,]\d{3})*[.,]\d+|\d+)"
EUR = r"(?:€|\beuro\b)"

PATTERNS_PRICE = [
    re.compile(rf"{EUR}\s*({NUM})\s*/\s*(kg|m3|mc)", re.IGNORECASE),
    re.compile(rf"({NUM})\s*{EUR}\s*/\s*(kg|m3|mc)", re.IGNORECASE),
    re.compile(rf"{EUR}\s*({NUM})\s*(kg|m3|mc)", re.IGNORECASE),
]

PATTERNS_GENERIC = [
    re.compile(rf"({NUM})\s*(kg|m3|mc|giorni|settimane|mesi|ore)\b", re.IGNORECASE),
    re.compile(rf"({NUM})\s*(?:{EUR})\s*/\s*(kg|m3|mc)", re.IGNORECASE),
]

def _to_float(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))

def extract_numeric(text: str, want_price: bool = False) -> List[Tuple[float, str]]:
    """Ritorna lista di (valore, unità normalizzata) dal testo."""
    if not text:
        return []
    found: List[Tuple[float,str]] = []
    pats = PATTERNS_PRICE if want_price else PATTERNS_GENERIC
    for pat in pats:
        for m in pat.finditer(text):
            val = _to_float(m.group(1))
            unit = norm_unit(m.group(2))
            found.append((val, unit))  # type: ignore
    return found

def median(values: List[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        return float("nan")
    mid = n // 2
    return round(s[mid] if n % 2 == 1 else (s[mid-1] + s[mid]) / 2, 2)

# -----------------------
# Intent/trigger grezzi
# -----------------------
PRICE_WORDS = {"prezzo","costo","listino","quotazione","€/","eur/"}
DURATION_WORDS = {"durata","giorni","settimane","mesi","ore","tempo","lead time"}
STANDARD_WORDS = {"norma","uni","classe","resistenza","requisito","mit","mims","cam"}

MATERIAL_ALIASES = {
    "cemento": ["cemento","calcestruzzo","cls"],
    "acciaio": ["acciaio","ferro tondo","tondino"],
    "bitume": ["bitume","asfalto"],
    "rame": ["rame"],
}

def infer_material(question: str) -> Optional[str]:
    ql = f" {question.lower()} "
    for mat, aliases in MATERIAL_ALIASES.items():
        if any(f" {a} " in ql for a in aliases):
            return mat
    return None

def classify_question(question: str) -> str:
    ql = question.lower()
    if any(w in ql for w in PRICE_WORDS):
        return "price"
    if any(w in ql for w in DURATION_WORDS):
        return "duration"
    if any(w in ql for w in STANDARD_WORDS):
        return "standard"
    # default: prova prezzo se contiene nomi materiali, altrimenti generic
    if infer_material(question):
        return "price"
    return "generic"

# -----------------------
# Builder confronto
# -----------------------
def choose_best_numeric(evidences: List[Evidence], prefer_unit: Optional[str] = None) -> Optional[Evidence]:
    if not evidences:
        return None
    if prefer_unit:
        cand = [e for e in evidences if e.unit == prefer_unit and e.value is not None]
        if cand:
            vals = [e.value for e in cand if e.value is not None]
            med = median([v for v in vals if v is not None])  # type: ignore
            out = cand[0]
            return Evidence(value=med, unit=out.unit, label=out.label, source=out.source, raw_snippet=out.raw_snippet)
    cand = [e for e in evidences if e.value is not None]
    vals = [e.value for e in cand if e.value is not None]
    if not vals:
        return None
    med = median(vals)
    out = cand[0]
    return Evidence(value=med, unit=out.unit, label=out.label, source=out.source, raw_snippet=out.raw_snippet)

def extract_internal_numeric(local_ctx: List[Dict], prefer_unit: Optional[str], want_price: bool, material: Optional[str]) -> Optional[Evidence]:
    evs: List[Evidence] = []
    for s in local_ctx:
        txt = (s.get("text") or "")
        meta = s.get("metadata", {}) or {}
        title = meta.get("source", "Documento")
        low = txt.lower()
        if material:
            aliases = MATERIAL_ALIASES.get(material, [])
            if not any(a in low for a in aliases):
                continue
        pairs = extract_numeric(txt, want_price=want_price)
        for val, unit in pairs:
            evs.append(Evidence(value=val, unit=unit, label=None, source=title, raw_snippet=txt[:240]))
    return choose_best_numeric(evs, prefer_unit=prefer_unit)

def extract_web_numeric(web_ctx: List[Dict], prefer_unit: Optional[str], want_price: bool) -> Tuple[Optional[Evidence], List[Evidence]]:
    all_evs: List[Evidence] = []
    for w in web_ctx:
        txt = w.get("text","") or ""
        title = w.get("title") or w.get("url") or "Fonte"
        pairs = extract_numeric(txt, want_price=want_price)
        for val, unit in pairs:
            all_evs.append(Evidence(value=val, unit=unit, label=None, source=title, raw_snippet=txt[:240]))
    best = choose_best_numeric(all_evs, prefer_unit=prefer_unit)
    return best, all_evs

def compare_numeric(internal: Evidence, external: Evidence) -> Dict:
    if internal.value is None or external.value is None:
        return {"verdict": "non_comparabile"}
    delta = round(external.value - internal.value, 2)
    base = internal.value if internal.value != 0 else 1e-6
    delta_pct = round((delta / base) * 100, 2)
    action = "valuta aggiornamento listino" if abs(delta_pct) >= 10 else "in linea con il mercato"
    return {
        "internal_value": internal.value,
        "internal_unit": internal.unit,
        "external_value": external.value,
        "external_unit": external.unit,
        "delta": delta,
        "delta_pct": delta_pct,
        "action": action,
        "internal_source": internal.source,
    }

def build_comparison(question: str, local_ctx: List[Dict], web_ctx: List[Dict]) -> Optional[Dict]:
    """
    Costruisce un confronto generico:
    - price: €/kg, €/m3 (prefer_unit derivata dal web)
    - duration: giorni/settimane/mesi/ore
    - standard: restituisce elenco fonti web con parole chiave (verifica qualitativa)
    """
    intent = classify_question(question)
    material = infer_material(question)

    if intent in ("price","duration"):
        want_price = intent == "price"
        # prefer_unit: unità più frequente nel web
        units = []
        for w in web_ctx:
            pairs = extract_numeric(w.get("text",""), want_price=want_price)
            units += [u for _, u in pairs]
        prefer_unit = None
        if units:
            from collections import Counter
            prefer_unit = sorted(Counter(units).items(), key=lambda x: x[1], reverse=True)[0][0]

        internal_best = extract_internal_numeric(local_ctx, prefer_unit=prefer_unit, want_price=want_price, material=material)
        external_best, _ = extract_web_numeric(web_ctx, prefer_unit=prefer_unit, want_price=want_price)

        if not internal_best and not external_best:
            return None

        out = {"type": intent}
        if internal_best:
            out["internal"] = {"value": internal_best.value, "unit": internal_best.unit, "source": internal_best.source}
        if external_best:
            out["external"] = {"value": external_best.value, "unit": external_best.unit, "source": external_best.source}
        if internal_best and external_best:
            out["comparison"] = compare_numeric(internal_best, external_best)
        return out

    if intent == "standard":
        # qualitativo
        hits = []
        for w in web_ctx:
            txt = (w.get("text","") or "").lower()
            if any(k in txt for k in ["uni", "classe", "resistenza", "norma", "mit", "cam"]):
                hits.append({"title": w.get("title") or w.get("url"), "url": w.get("url")})
        if hits:
            return {"type": "standard", "web_mentions": hits}
        return None

    return None