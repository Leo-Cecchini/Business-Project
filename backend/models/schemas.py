
from __future__ import annotations
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict
from enum import Enum

class Unit(str, Enum):
    m = "m"
    m2 = "m2"
    m3 = "m3"
    pz = "pz"
    h = "h"
    kg = "kg"
    l = "l"

UNIT_ALIASES: Dict[str, Unit] = {
    "m": Unit.m, "ml": Unit.m, "metro": Unit.m, "metri": Unit.m,
    "mq": Unit.m2, "m²": Unit.m2, "m2": Unit.m2, "metri quadri": Unit.m2, "superficie": Unit.m2,
    "mc": Unit.m3, "m³": Unit.m3, "m3": Unit.m3, "metri cubi": Unit.m3,
    "pz": Unit.pz, "pezzo": Unit.pz, "pezzi": Unit.pz, "n": Unit.pz, "nr": Unit.pz, "n°": Unit.pz,
    "h": Unit.h, "ora": Unit.h, "ore": Unit.h,
    "kg": Unit.kg, "kilogrammi": Unit.kg,
    "l": Unit.l, "lt": Unit.l, "litro": Unit.l, "litri": Unit.l,
}

class CalcItem(BaseModel):
    label: str = Field(..., description="Descrizione lavorazione, es: 'posa piastrelle bagno'")
    qty: float = Field(1.0, ge=0, description="Quantità numerica")
    unit: Unit = Field(Unit.pz, description="Unità di misura normalizzata")
    notes: Optional[str] = Field(None, description="Assunzioni o dettagli")
    tags: List[str] = Field(default_factory=list, description="Tag opzionali (es: 'demolizione','interni')")

    @validator("label")
    def _label_trim(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("label vuoto")
        return v

class CalcBundle(BaseModel):
    items: List[CalcItem] = Field(default_factory=list)
    raw_text: Optional[str] = None

    @property
    def total_qty(self) -> float:
        return sum(i.qty for i in self.items)

class EstimateLine(BaseModel):
    code: Optional[str] = None
    descr: str
    um: Unit
    qta: float
    prezzo: float
    totale: float

class EstimateItem(BaseModel):
    label: str
    materials: List[EstimateLine] = Field(default_factory=list)
    labor: List[EstimateLine] = Field(default_factory=list)
    subtotal: float = 0.0
    ready_to_commit: bool = False
    assumptions: Optional[str] = None

class EstimatePayload(BaseModel):
    items: List[EstimateItem] = Field(default_factory=list)
    grand_total: float = 0.0
    summary: Optional[str] = None
