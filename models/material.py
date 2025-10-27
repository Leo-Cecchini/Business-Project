# models/material.py
from __future__ import annotations
from datetime import datetime
from models import db

class Material(db.Model):
    __tablename__ = "materials"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    category = db.Column(db.String(80), nullable=True, index=True)
    subcategory = db.Column(db.String(80), nullable=True, index=True)

    unit = db.Column(db.String(20), nullable=False)              # es. kg, m3, m2, pz
    unit_price_eur_2025 = db.Column(db.Float, nullable=True)     # prezzo indicativo €/unità (2025)
    vat_rate = db.Column(db.Float, nullable=True, default=22.0)

    supplier = db.Column(db.String(120), nullable=True)
    sku = db.Column(db.String(80), nullable=True)

    stock_qty = db.Column(db.Float, nullable=True, default=0.0)
    lead_time_days = db.Column(db.Integer, nullable=True, default=0)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("name", "unit", name="uq_material_name_unit"),
        db.Index("ix_materials_name_cat", "name", "category"),
    )

    # --- ALIAS RETRO-COMPATIBILE ---
    @property
    def price(self) -> float | None:
        return self.unit_price_eur_2025

    @price.setter
    def price(self, value: float | None):
        self.unit_price_eur_2025 = value

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "subcategory": self.subcategory,
            "unit": self.unit,
            "unit_price_eur_2025": self.unit_price_eur_2025,
            "price": self.unit_price_eur_2025,   # <-- comodo per il frontend
            "vat_rate": self.vat_rate,
            "supplier": self.supplier,
            "sku": self.sku,
            "stock_qty": self.stock_qty,
            "lead_time_days": self.lead_time_days,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }