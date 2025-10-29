import sqlite3, csv, os

# Percorsi
DB_PATH = os.getenv("DATABASE_URL", "sqlite:///data.db").replace("sqlite:///", "")
CSV_PATH = "Workers.csv"  # il tuo file CSV nella root del progetto

# Crea la tabella se non esiste
schema = """
CREATE TABLE IF NOT EXISTS workers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT,
  hourly_rate REAL,
  available INTEGER,
  home_city TEXT,
  skills TEXT,
  certifications TEXT
);
"""

con = sqlite3.connect(DB_PATH)
cur = con.cursor()
cur.executescript(schema)

# Legge il CSV
with open(CSV_PATH, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# Inserisce o aggiorna (upsert)
for r in rows:
    avail_str = str(r.get("available")).strip().lower()
    is_available = 1 if avail_str in {"true","1","yes","y","si","sì","vero","on"} else 0
    cur.execute("""
        INSERT INTO workers (id, name, role, hourly_rate, available, home_city, skills, certifications)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          name=excluded.name,
          role=excluded.role,
          hourly_rate=excluded.hourly_rate,
          available=excluded.available,
          home_city=excluded.home_city,
          skills=excluded.skills,
          certifications=excluded.certifications
    """, (
        r.get("ID"),
        r.get("name"),
        r.get("role"),
        float(r.get("hourly_rate") or 0),
        is_available,
        r.get("home_city"),
        r.get("skills"),
        r.get("certifications"),
    ))

con.commit()
con.close()
print(f"✅ Import completato: {len(rows)} lavoratori inseriti o aggiornati.")