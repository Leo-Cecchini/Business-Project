#!/usr/bin/env python3
import csv, os, sys, sqlite3
from datetime import datetime

USAGE = "Usage: python scripts/import_materials.py <CSV path> [DB path (default: data.db)]"

def norm(s): return (s or "").strip()

def to_float(v):
    if v is None: return None
    s = str(v).strip().replace(",", ".")
    if s == "": return None
    try: return float(s)
    except: return None

def table_info(cur, table):
    cur.execute(f"PRAGMA table_info({table});")
    # returns: cid, name, type, notnull, dflt_value, pk
    cols = cur.fetchall()
    by_name = {row[1]: {"type": row[2], "notnull": bool(row[3]), "pk": bool(row[5])} for row in cols}
    return by_name

def has_unique_index(cur, table, cols):
    # verifica se esiste un indice unico esattamente su quell’insieme di colonne (ordine irrilevante)
    cur.execute(f"PRAGMA index_list({table});")
    for (seq, name, unique, _, _) in cur.fetchall():
        if not unique: continue
        cur.execute(f"PRAGMA index_info({name});")
        idx_cols = [r[2] for r in cur.fetchall()]
        if set(idx_cols) == set(cols):
            return True
    return False

def main():
    if len(sys.argv) < 2:
        print(USAGE); sys.exit(1)

    csv_path = sys.argv[1]
    db_path  = sys.argv[2] if len(sys.argv) >= 3 else "data.db"

    if not os.path.exists(csv_path):
        print(f"CSV non trovato: {csv_path}"); sys.exit(2)
    if not os.path.exists(db_path):
        print(f"DB non trovato: {db_path}"); sys.exit(3)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Assicura esistenza tabella minima se non c’è (NON tocca tabelle già esistenti)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        unit TEXT,
        unit_price_eur_2025 REAL,
        sku TEXT,
        category TEXT,
        notes TEXT
    );
    """)

    # Leggi schema reale (può avere created_at / updated_at NOT NULL)
    cols = table_info(cur, "materials")
    has_created_at = "created_at" in cols
    has_updated_at = "updated_at" in cols
    created_notnull = has_created_at and cols["created_at"]["notnull"]
    updated_notnull = has_updated_at and cols["updated_at"]["notnull"]

    # Crea indice unico se non esiste (name, unit)
    try:
        if not has_unique_index(cur, "materials", ["name", "unit"]):
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_materials_name_unit ON materials(name, unit);")
    except Exception:
        # in caso di schema con chiavi diverse, ignoriamo
        pass

    created = 0
    updated = 0
    errors  = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        header = [h.strip() for h in (rdr.fieldnames or [])]
        lc = {h.lower(): h for h in header}

        # mappa flessibile dei nomi colonna nel CSV
        col_name  = lc.get("name") or lc.get("material") or lc.get("material_name")
        col_unit  = lc.get("unit") or lc.get("uom") or lc.get("unità") or lc.get("unita")
        col_price = lc.get("unit_price_eur_2025") or lc.get("price") or lc.get("unit_price") or lc.get("prezzo")
        col_sku   = lc.get("sku") or lc.get("code") or lc.get("codice")
        col_cat   = lc.get("category") or lc.get("categoria")
        col_notes = lc.get("notes") or lc.get("note") or lc.get("description") or lc.get("descrizione")

        if not col_name:
            print("Colonna 'name' (o equivalente) non trovata nel CSV."); sys.exit(4)

        for i, row in enumerate(rdr, start=2):
            try:
                name  = norm(row.get(col_name))
                if not name:
                    continue
                unit  = norm(row.get(col_unit)) if col_unit else None
                price = to_float(row.get(col_price)) if col_price else None
                sku   = norm(row.get(col_sku)) if col_sku else None
                cat   = norm(row.get(col_cat)) if col_cat else None
                notes = norm(row.get(col_notes)) if col_notes else None

                now = datetime.utcnow().isoformat(timespec="seconds")

                # --- UPDATE: prova ad aggiornare record esistente
                set_parts = []
                params = []

                if "unit_price_eur_2025" in cols and price is not None:
                    set_parts.append("unit_price_eur_2025 = ?"); params.append(price)
                if "sku" in cols and sku is not None:
                    set_parts.append("sku = NULLIF(?, '')"); params.append(sku)
                if "category" in cols and cat is not None:
                    set_parts.append("category = NULLIF(?, '')"); params.append(cat)
                if "notes" in cols and notes is not None:
                    set_parts.append("notes = NULLIF(?, '')"); params.append(notes)
                if has_updated_at:
                    set_parts.append("updated_at = ?"); params.append(now)

                where = "name = ? AND COALESCE(unit,'') = COALESCE(?, '')"
                params += [name, unit]

                did_update = False
                if set_parts:
                    sql_up = f"UPDATE materials SET {', '.join(set_parts)} WHERE {where}"
                    cur.execute(sql_up, params)
                    did_update = (cur.rowcount > 0)

                if did_update:
                    updated += 1
                    continue

                # --- INSERT: costruisci la lista colonne che esistono davvero
                insert_cols = ["name"]
                insert_vals = [name]

                if "unit" in cols:
                    insert_cols.append("unit"); insert_vals.append(unit)
                if "unit_price_eur_2025" in cols:
                    insert_cols.append("unit_price_eur_2025"); insert_vals.append(price)
                if "sku" in cols:
                    insert_cols.append("sku"); insert_vals.append(sku)
                if "category" in cols:
                    insert_cols.append("category"); insert_vals.append(cat)
                if "notes" in cols:
                    insert_cols.append("notes"); insert_vals.append(notes)

                # gestisci created_at / updated_at se presenti e NOT NULL
                if has_created_at:
                    insert_cols.append("created_at")
                    insert_vals.append(now if created_notnull else now)  # valorizziamo comunque
                if has_updated_at:
                    insert_cols.append("updated_at")
                    insert_vals.append(now if updated_notnull else now)

                placeholders = ",".join(["?"] * len(insert_cols))
                sql_in = f"INSERT INTO materials ({', '.join(insert_cols)}) VALUES ({placeholders})"
                cur.execute(sql_in, insert_vals)
                created += 1

            except Exception as e:
                errors.append({"row": i, "err": str(e)})

    conn.commit()
    conn.close()

    print({
        "created": created,
        "updated": updated,
        "errors": errors[:5],
        "errors_count": len(errors),
    })

if __name__ == "__main__":
    main()