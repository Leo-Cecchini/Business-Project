# models/worker.py
from models import db

class Worker(db.Model):
    __tablename__ = "workers"

    # DB reale: TEXT (es. "W-1048")
    id = db.Column(db.String, primary_key=True)

    name = db.Column(db.String(120), nullable=False, index=True)
    role = db.Column(db.String(80), nullable=True, index=True)
    hourly_rate = db.Column(db.Float, nullable=True)

    # 0/1 in SQLite; db.Boolean lo mappa correttamente
    available = db.Column(db.Boolean, nullable=False, default=True, index=True)

    home_city = db.Column(db.String(120), nullable=True, index=True)
    skills = db.Column(db.Text, nullable=True)            # CSV testo: "muratura, cartongesso"
    certifications = db.Column(db.Text, nullable=True)    # CSV testo

    __table_args__ = (db.Index("ix_workers_role_city", "role", "home_city"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "hourly_rate": self.hourly_rate,
            "available": bool(self.available) if self.available is not None else None,
            "home_city": self.home_city,
            "skills": self.skills,
            "certifications": self.certifications,
        }

    def __repr__(self) -> str:
        return f"<Worker id={self.id!r} name={self.name!r} role={self.role!r} available={self.available}>"