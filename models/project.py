# models/project.py
from __future__ import annotations
from datetime import datetime, date
from sqlalchemy import CheckConstraint
from . import db  # models/__init__.py -> db = SQLAlchemy()


# ---------------------------
# Company
# ---------------------------
class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    vat_number = db.Column(db.String(32), nullable=True)  # P.IVA
    address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(120), nullable=True)
    country = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    projects = db.relationship(
        "Project",
        back_populates="company",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "vat_number": self.vat_number,
            "address": self.address,
            "city": self.city,
            "country": self.country,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Company {self.id} {self.name!r}>"


# ---------------------------
# Project (Cantiere)
# ---------------------------
class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False, index=True)

    name = db.Column(db.String(200), nullable=False, index=True)
    # Stato coerente con il frontend (“Preventivo” | “Confermato”)
    status = db.Column(db.String(32), nullable=False, default="Preventivo", index=True)

    start_date = db.Column(db.Date, nullable=True, index=True)
    end_date = db.Column(db.Date, nullable=True, index=True)

    location_city = db.Column(db.String(120), nullable=True, index=True)
    location_address = db.Column(db.String(255), nullable=True)

    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relazioni
    company = db.relationship("Company", back_populates="projects")
    documents = db.relationship("ProjectDocument", back_populates="project", cascade="all, delete-orphan")
    # Relationship verso Assignment definito nel file dedicato models/assignment.py
    # assignments = db.relationship("Assignment", back_populates="project", cascade="all, delete-orphan")

    # (Opzionale) relazione materiali di progetto, se la definisci in un modello separato:
    # project_materials = db.relationship("ProjectMaterial", back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (
        db.Index("ix_projects_company_status", "company_id", "status"),
        db.Index("ix_projects_dates", "start_date", "end_date"),
        db.UniqueConstraint("company_id", "name", name="uq_projects_company_name"),
        # Vincolo di coerenza sullo stato (funziona anche su SQLite)
        CheckConstraint("status in ('Preventivo','Confermato')", name="ck_projects_status"),
    )

    # ---------- Helper ----------
    @property
    def is_confirmed(self) -> bool:
        return (self.status or "").lower() == "confermato"

    def pretty_status(self) -> str:
        return "Confermato" if self.is_confirmed else "Da approvare"

    @property
    def duration_days(self) -> int | None:
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return None

    @property
    def documents_count(self) -> int:
        return len(self.documents or [])

    # @property
    # def assignments_count(self) -> int:
    #     return len(self.assignments or [])

    def to_dict(self, with_children: bool = False) -> dict:
        data = {
            "id": self.id,
            "company_id": self.company_id,
            "name": self.name,
            "status": self.status,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "location_city": self.location_city,
            "location_address": self.location_address,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            # helper utili in UI/API
            "duration_days": self.duration_days,
            "documents_count": self.documents_count,
            # "assignments_count": self.assignments_count,
        }
        if with_children:
            data["documents"] = [d.to_dict() for d in self.documents]
            # data["assignments"] = [a.to_dict() for a in self.assignments]
            # Se usi ProjectMaterial:
            # data["materials"] = [pm.to_dict() for pm in self.project_materials]
        return data

    def __repr__(self) -> str:
        return f"<Project {self.id} {self.name!r} ({self.status})>"


# ---------------------------
# ProjectDocument (file del cantiere)
# ---------------------------
class ProjectDocument(db.Model):
    __tablename__ = "project_documents"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)

    filename = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(255), nullable=True)      # es: path o nome originale
    mime_type = db.Column(db.String(100), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    project = db.relationship("Project", back_populates="documents")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "filename": self.filename,
            "source": self.source,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<ProjectDocument {self.id} {self.filename!r} proj={self.project_id}>"