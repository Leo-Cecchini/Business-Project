"""
Migrazione Qdrant: imposta metadata.project_id (o project_id) dove mancante.

- Per gli asset aziendali: project_id = "GLOBAL"
- Per i documenti di cantiere: inferiti da filename (es. "C-1234_relazione.pdf" -> "C-1234")

Uso:
    python scripts/migrate_set_project_id.py --collection documents
Opzioni:
    --collection/-c       Nome della collection Qdrant (default: documents)
    --batch-size/-b       Dimensione batch per scroll (default: 256)
    --dry-run/-n          Non scrive, stampa soltanto cosa farebbe
    --regex/-r            Regex per inferire l'ID cantiere (default: (C-\d+))

Connessione Qdrant (scegli uno):
    - Env QDRANT_URL (+ QDRANT_API_KEY opzionale)
    - Env QDRANT_PATH (persistenza su disco)
"""

import os
import re
import argparse
from typing import Any, Dict, Optional, Tuple

from qdrant_client import QdrantClient


def make_client() -> QdrantClient:
    url = os.getenv("QDRANT_URL")
    api_key = os.getenv("QDRANT_API_KEY")
    path = os.getenv("QDRANT_PATH")
    if url:
        return QdrantClient(url=url, api_key=api_key)
    if path:
        return QdrantClient(path=path)
    # Fallback locale standard
    return QdrantClient(path="./qdrant_data")


def infer_project_id(meta: Dict[str, Any], pattern: re.Pattern) -> str:
    """
    Cerca di inferire il project_id dalla sorgente del documento.
    Se non trova nulla, ritorna 'GLOBAL'.
    """
    source = (meta or {}).get("source") or meta.get("file") or meta.get("filename") or ""
    m = pattern.search(str(source))
    return m.group(1) if m else "GLOBAL"


def extract_metadata(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    Restituisce (metadata_dict, is_nested) dove:
    - metadata_dict: dict dei metadati da aggiornare
    - is_nested: True se i metadati stanno in payload['metadata'], False se sono top-level
    """
    if isinstance(payload.get("metadata"), dict):
        return payload["metadata"], True
    return payload, False


def set_project_id_on_point(client: QdrantClient, coll: str, point, pid: str, is_nested: bool, dry_run: bool = False):
    """
    Aggiorna il payload del punto, rispettando la struttura (annidata o flat).
    """
    if dry_run:
        print(f"[DRY-RUN] Would set project_id={pid} on point id={point.id} (nested={is_nested})")
        return

    if is_nested:
        # ricostruisci l'intero dict 'metadata' con project_id aggiornato
        meta = dict(point.payload.get("metadata", {}))
        meta["project_id"] = pid
        client.set_payload(collection_name=coll, payload={"metadata": meta}, points=[point.id])
    else:
        # struttura flat: project_id al top-level
        pl = dict(point.payload or {})
        pl["project_id"] = pid
        client.set_payload(collection_name=coll, payload=pl, points=[point.id])


def main():
    parser = argparse.ArgumentParser(description="Migrazione Qdrant: set metadata.project_id dove mancante")
    parser.add_argument("--collection", "-c", default="documents")
    parser.add_argument("--batch-size", "-b", type=int, default=256)
    parser.add_argument("--dry-run", "-n", action="store_true", default=False)
    parser.add_argument("--regex", "-r", default=r"(C-\d+)")
    args = parser.parse_args()

    pattern = re.compile(args.regex)
    client = make_client()
    coll = args.collection

    updated = 0
    skipped_has_pid = 0
    total = 0
    offset = None

    print(f"Starting migration on collection='{coll}' (batch={args.batch_size}) dry_run={args.dry_run}")

    while True:
        points, offset = client.scroll(
            collection_name=coll,
            with_payload=True,
            with_vectors=False,
            offset=offset,
            limit=args.batch_size,
        )
        if not points:
            break

        for pt in points:
            total += 1

            payload = pt.payload or {}

            # 1) Verifica presenza project_id (nested o flat)
            nested_meta = payload.get("metadata")
            has_pid = False
            if isinstance(nested_meta, dict) and nested_meta.get("project_id"):
                has_pid = True
            if payload.get("project_id"):
                has_pid = True

            if has_pid:
                skipped_has_pid += 1
                continue

            # 2) Estrai metadati e inferisci pid
            meta_dict, is_nested = extract_metadata(payload)
            pid = infer_project_id(meta_dict, pattern)

            # 3) Aggiorna il punto
            set_project_id_on_point(client, coll, pt, pid, is_nested, dry_run=args.dry_run)
            updated += 1

    print("---- SUMMARY ----")
    print(f"Total scanned : {total}")
    print(f"Already had pid: {skipped_has_pid}")
    print(f"Updated       : {updated}")
    if args.dry_run:
        print("Dry-run mode: no changes were written.")


if __name__ == "__main__":
    main()
