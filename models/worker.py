from datetime import date, datetime
from models import db

# -----------------------
# Tabella di join molti-a-molti tra operai e competenze
# -----------------------
worker_skills = db.Table(
    "worker_skills",
    db.Column("worker_id", db.Integer, db.ForeignKey("workers.id"), primary_key=True),
    db.Column("skill_id", db.Integer, db.ForeignKey("skills.id"), primary_key=True),
)

# -----------------------
# Modello principale: Worker (dipendente/operaio)
# -----------------------
class Worker(db.Model):
    __tablename__ = "workers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    role = db.Column(db.String(80), nullable=True, index=True)       # es. "muratore", "capocantiere"
    hourly_rate = db.Column(db.Float, nullable=True)                  # €/h
    home_city = db.Column(db.String(120), nullable=True, index=True)  # base o città di residenza
    certifications = db.Column(db.String(255), nullable=True)         # CSV es: "PONTEGGI,ESCAVATORI"
    availability = db.Column(db.String(64), nullable=True, index=True)# es. "FT", "PT", "OUT"
    current_load = db.Column(db.Float, default=0.0)                   # ore già allocate questa settimana

    skills = db.relationship("Skill", secondary=worker_skills, backref="workers")

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # ✅ chiave “posizione”: stessa persona può avere più ruoli e/o città
        db.UniqueConstraint("name", "role", "home_city", name="uq_worker_name_role_city"),
        # indice composito utile per query frequenti
        db.Index("ix_workers_role_city", "role", "home_city"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "hourly_rate": self.hourly_rate,
            "home_city": self.home_city,
            "certifications": self.certifications,
            "availability": self.availability,
            "current_load": self.current_load,
            "skills": [s.name for s in self.skills] if self.skills else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

# -----------------------
# Modello per le competenze
# -----------------------
class Skill(db.Model):
    __tablename__ = "skills"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)

# -----------------------
# Modello per i lavori o progetti (Job)
# -----------------------
class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    site_city = db.Column(db.String(120), nullable=True)
    required_hours = db.Column(db.Float, nullable=False)        # ore totali
    required_role = db.Column(db.String(80), nullable=True)
    required_skills = db.Column(db.String(255), nullable=True)  # CSV: "muratura,pavimenti"
    required_certs = db.Column(db.String(255), nullable=True)   # CSV: "PONTEGGI"
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)

# -----------------------
# Modello per l'assegnazione (Worker ↔ Job)
# -----------------------
class Assignment(db.Model):
    __tablename__ = "assignments"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("jobs.id"), nullable=False)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id"), nullable=False)
    hours = db.Column(db.Float, nullable=False)

    job = db.relationship("Job", backref="assignments")
    worker = db.relationship("Worker", backref="assignments")