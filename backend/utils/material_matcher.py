from __future__ import annotations
import re
from typing import Optional, Tuple, List
from models.material import Material

# Sinonimi essenziali (estendibile):
ALIASES = {
    "cemento": ["cemento", "cemento 32.5", "cemento 42.5", "cemento portland"],
    "calcestruzzo": ["calcestruzzo", "cls", "cls rck", "cls c25/30", "cls c30/37"],
    "sabbia": ["sabbia", "sabbia fine", "sabbia media"],
    "ghiaia": ["ghiaia", "inerti", "pietrisco"],
    "acciaio": ["acciaio", "armatura", "tondini", "ferro tondo"],
    "cartongesso": ["cartongesso", "lastra cartongesso", "lastra gkb", "lastra idrofuga"],
    "lana di roccia": ["lana di roccia", "isolante in lana di roccia"],
    "xps": ["xps", "polistirene estruso"],
    "eps": ["eps", "polistirene espanso"],
    "vernice": ["vernice", "idropittura", "smalto"],
    "guaina": ["guaina", "membrana bituminosa", "guaine"],
}

UNITS = {"kg", "m3", "m2", "m", "pz", "lt", "l"}

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())

def guess_material_and_unit(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Ritorna (nome_materiale_probabile, unità_probabile) se riconosciuti nel testo.
    """
    t = _norm(text)
    # prova match unità
    unit = None
    for u in UNITS:
        if re.search(rf"\b{re.escape(u)}\b", t):
            unit = u
            break
    # prova alias
    for canonical, syns in ALIASES.items():
        for s in syns:
            if s in t:
                return canonical, unit
    # fallback: prendi una parola “forte”
    for word in t.split():
        if len(word) >= 5:
            return word, unit
    return None, unit

def find_best_db_match(name: str, unit: Optional[str]) -> Optional[Material]:
    """
    Cerca in DB per name (ilike) e, se possibile, per unit.
    """
    q = Material.query
    if name:
        q = q.filter(Material.name.ilike(f"%{name}%"))
    if unit:
        q = q.filter(Material.unit.ilike(unit))
    q = q.order_by(Material.category.asc(), Material.name.asc())
    return q.first()

def price_lookup_from_text(text: str) -> Optional[dict]:
    """
    Dato un testo tipo “prezzo cemento 32.5 al kg”, prova a restituire:
      {material_id, name, unit, unit_price_eur_2025, vat_rate}
    """
    mat_name, unit = guess_material_and_unit(text)
    if not mat_name:
        return None
    m = find_best_db_match(mat_name, unit)
    if not m:
        # riprova ignorando unit
        m = find_best_db_match(mat_name, None)
    if not m:
        return None
    return {
        "material_id": m.id,
        "name": m.name,
        "unit": m.unit,
        "unit_price_eur_2025": m.unit_price_eur_2025,
        "vat_rate": m.vat_rate,
        "supplier": m.supplier,
    }