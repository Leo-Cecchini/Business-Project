# models/tools.py
from pydantic import BaseModel, Field, validator
from typing import Optional

class CreateWorker(BaseModel):
    name: str = Field(..., min_length=2, description="Nome e cognome operaio")
    role: str = Field(..., description="Ruolo standardizzato (es. elettricista, muratore)")
    hourly_rate: Optional[float] = Field(None, ge=0)
    home_city: Optional[str] = None
    skills: list[str] = []
    certifications: list[str] = []

    @validator("name")
    def _name_clean(cls, v):
        return " ".join(v.split())

class RemoveWorker(BaseModel):
    worker_id: str = Field(..., description="ID WorkerDoc.id da eliminare DEFINITIVAMENTE")
    confirm: bool = Field(False, description="Deve essere true per permettere la rimozione")