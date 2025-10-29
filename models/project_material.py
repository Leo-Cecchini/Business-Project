# models/project_material.py
from datetime import datetime
from models import db

class ProjectMaterial(db.Model):
    __tablename__ = "project_materials"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    material_id = db.Column(db.Integer, db.ForeignKey("materials.id"), nullable=False, index=True)

    qty_planned = db.Column(db.Float, default=0.0)            # quantità prevista
    qty_used = db.Column(db.Float, default=0.0)               # quantità effettiva usata
    unit_cost_override = db.Column(db.Float)                  # opzionale: costo personalizzato
    note = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relazioni
    project = db.relationship("Project", back_populates="project_materials")
    material = db.relationship("Material")

    def unit_cost_effective(self):
        """Restituisce il costo unitario effettivo (override o listino)."""
        return (
            self.unit_cost_override
            if self.unit_cost_override is not None
            else (self.material.unit_price_eur_2025 if self.material else 0.0)
        )

    def planned_cost(self):
        return (self.qty_planned or 0.0) * self.unit_cost_effective()

    def used_cost(self):
        return (self.qty_used or 0.0) * self.unit_cost_effective()

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "material_id": self.material_id,
            "material_name": self.material.name if self.material else None,
            "unit": self.material.unit if self.material else None,
            "qty_planned": self.qty_planned,
            "qty_used": self.qty_used,
            "unit_cost": self.unit_cost_effective(),
            "planned_cost": self.planned_cost(),
            "used_cost": self.used_cost(),
            "note": self.note,
        }