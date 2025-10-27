# models/intents.py
from pydantic import BaseModel, Field
from typing import Optional, Literal

class StaffIntent(BaseModel):
    topic: Literal["staff"]
    operation: Literal["count", "list", "where", "clarify", "roles"]
    role: Optional[str] = None                # "elettricista", "idraulico", ...
    free_only: bool = False
    limit: int = 25
    free_hours_threshold: float = 20.0
    # se è follow-up, possiamo voler riusare il contesto:
    reuse_last: bool = False

class RoutedIntent(BaseModel):
    # Se non è staff, lascia spazio ad altri topic futuri (prezzi, meteo decisionale ecc.)
    topic: Optional[str] = None               # "staff" | "pricing" | "none"
    staff: Optional[StaffIntent] = None
