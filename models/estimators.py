# models/estimators.py
"""
Calcolatori di stima rapidi per lavorazioni tipiche.
Obiettivo: fornire numeri "ancora" (ore, costi, materiali) che il LLM formatterà e spiegherà.
Tutti i valori sono configurabili e pensati come baseline conservative.
"""

from __future__ import annotations
from typing import Dict, Optional

# --- Tariffe base (fallback) -------------------------------------------------
WAGE = {
    "muratore": 28.0,          # €/h
    "piastrellista": 30.0,     # €/h
    "cartongessista": 30.0,    # €/h
    "cappottista": 30.0,       # €/h
    "imbianchino": 26.0,       # €/h
}

# --- Materiali baseline (fallback) ------------------------------------------
MATERIALS = {
    "gres_60x60": 22.0,        # €/m2 (solo piastrella)
    "collante_flex": 3.0,      # €/m2
    "intonaco_civile": 8.0,    # €/m2 (materiale)
    "rasante_rete": 6.0,       # €/m2 (cappotto finitura)
    "eps_100_kg_m3": 18.0,     # €/m2 per 10 cm (stima grezza)
    "lastra_cartongesso_12_5": 6.0,  # €/m2
    "struttura_cartongesso": 7.0,    # €/m2
    "lana_vetro": 4.0,         # €/m2
}

def flooring_gres(mq: float, formato: str="60x60") -> Dict:
    """Stima pavimentazione gres con posa tradizionale su massetto pronto."""
    waste = 0.08 if formato == "60x60" else 0.10
    hours_per_m2 = 0.40 if formato == "60x60" else 0.45
    material_price = MATERIALS.get("gres_60x60", 22.0)
    collante = MATERIALS.get("collante_flex", 3.0)
    wage = WAGE.get("piastrellista", 30.0)

    qty_tiles = mq * (1 + waste)
    ore = mq * hours_per_m2
    costo_mat = (material_price + collante) * mq
    costo_mano = wage * ore
    totale = costo_mat + costo_mano

    return {
        "voce": "Pavimento gres",
        "mq": round(mq, 2),
        "formato": formato,
        "sfrido_%": round(waste * 100),
        "ore_uomo": round(ore, 2),
        "costo_materiali_€": round(costo_mat, 2),
        "costo_manodopera_€": round(costo_mano, 2),
        "totale_€": round(totale, 2),
        "note": "Posa tradizionale su massetto piano; esclusi battiscopa e demolizioni."
    }

def plaster_intonaco(mq: float, tipologia: str="civile") -> Dict:
    """Intonaco civile su pareti interne, due strati + rasatura."""
    hours_per_m2 = 0.35 if tipologia == "civile" else 0.45
    material = MATERIALS.get("intonaco_civile", 8.0)
    wage = WAGE.get("muratore", 28.0)

    ore = mq * hours_per_m2
    costo_mat = material * mq
    costo_mano = wage * ore
    totale = costo_mat + costo_mano

    return {
        "voce": f"Intonaco {tipologia}",
        "mq": round(mq, 2),
        "ore_uomo": round(ore, 2),
        "costo_materiali_€": round(costo_mat, 2),
        "costo_manodopera_€": round(costo_mano, 2),
        "totale_€": round(totale, 2),
        "note": "Supporti preparati; esclusi ponteggi e ripristini importanti."
    }

def drywall_cartongesso(mq: float, tipo: str="parete_singola") -> Dict:
    """Parete in cartongesso con struttura metallica; isolamento opzionale."""
    if tipo == "parete_doppia":
        hours_per_m2 = 0.65
        lastra = 2 * MATERIALS.get("lastra_cartongesso_12_5", 6.0)
    else:
        hours_per_m2 = 0.50
        lastra = MATERIALS.get("lastra_cartongesso_12_5", 6.0)

    struttura = MATERIALS.get("struttura_cartongesso", 7.0)
    isolamento = MATERIALS.get("lana_vetro", 4.0)
    wage = WAGE.get("cartongessista", 30.0)

    ore = mq * hours_per_m2
    costo_mat = (lastra + struttura + isolamento) * mq
    costo_mano = wage * ore
    totale = costo_mat + costo_mano

    return {
        "voce": f"Cartongesso ({tipo})",
        "mq": round(mq, 2),
        "ore_uomo": round(ore, 2),
        "costo_materiali_€": round(costo_mat, 2),
        "costo_manodopera_€": round(costo_mano, 2),
        "totale_€": round(totale, 2),
        "note": "Include isolamento leggero; esclusi varchi/porte e finiture speciali."
    }

def external_cappotto(mq: float, spessore_mm: int=120, materiale: str="EPS") -> Dict:
    """Cappotto termico esterno; baseline EPS 120 mm con finitura."""
    wage = WAGE.get("cappottista", 30.0)

    # ore/m2 aumentano con spessore
    base_hours = 0.80  # per 100-120 mm
    if spessore_mm >= 140: base_hours = 0.90
    if spessore_mm <= 100: base_hours = 0.70

    # materiali: pannelli + rasatura armata + finitura
    if materiale.upper() == "EPS":
        pannello = MATERIALS.get("eps_100_kg_m3", 18.0) * (spessore_mm / 100.0)
    else:
        # fallback per altri materiali (lana di roccia etc.) +30%
        pannello = MATERIALS.get("eps_100_kg_m3", 18.0) * (spessore_mm / 100.0) * 1.3

    finitura = MATERIALS.get("rasante_rete", 6.0)

    ore = mq * base_hours
    costo_mat = (pannello + finitura) * mq
    costo_mano = wage * ore
    totale = costo_mat + costo_mano

    return {
        "voce": f"Cappotto {materiale.upper()} {spessore_mm} mm",
        "mq": round(mq, 2),
        "ore_uomo": round(ore, 2),
        "costo_materiali_€": round(costo_mat, 2),
        "costo_manodopera_€": round(costo_mano, 2),
        "totale_€": round(totale, 2),
        "note": "Esclusi ponteggi, opere provvisionali, oneri sicurezza e ponteggi."
    }

def pick_and_estimate(entities: Dict) -> Optional[Dict]:
    """
    Sceglie automaticamente il calcolatore in base a 'voce_lavoro'/'dimensioni'/'materiali' e 'unit'.
    Ritorna dict con breakdown oppure None se non stimabile.
    """
    qty = entities.get("qty")
    unit = (entities.get("unit") or "").lower()
    if not qty or unit not in ("m2", "m3", "m"):
        return None

    voce = (entities.get("voce_lavoro") or "").lower()
    mats = [str(m).lower() for m in (entities.get("materiali") or [])]
    dims = entities.get("dimensioni") or []

    # Heuristics semplici
    if "cappotto" in voce or "eps" in mats or ("spessori_mm" in entities and entities["spessori_mm"]):
        return external_cappotto(float(qty), int(entities.get("spessori_mm") or 120), "EPS")

    if "cartongesso" in voce or any("cartongesso" in m for m in mats):
        return drywall_cartongesso(float(qty), "parete_singola")

    if "intonaco" in voce:
        return plaster_intonaco(float(qty))

    if "pavimento" in voce or "piastre" in voce or dims:
        formato = dims[0] if dims else "60x60"
        return flooring_gres(float(qty), formato)

    # fallback su pavimento se unit=m2 e non ci sono indizi
    if unit == "m2":
        return flooring_gres(float(qty))

    return None
