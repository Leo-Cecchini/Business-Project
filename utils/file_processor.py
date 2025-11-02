# File processing utilities

import PyPDF2
import io, csv
from io import BytesIO
from typing import List, Tuple, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter

class FileProcessor:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""]
        )

    # -----------------------
    # PDF
    # -----------------------
    def extract_text_from_pdf(self, file_data: bytes) -> str:
        """Extract text from PDF."""
        try:
            pdf_reader = PyPDF2.PdfReader(BytesIO(file_data))
            text = ""
            for page in pdf_reader.pages:
                text += (page.extract_text() or "") + "\n"
            return text
        except Exception as e:
            raise ValueError(f"Error reading PDF: {str(e)}")

    # -----------------------
    # CSV
    # -----------------------
    def _csv_to_text(self, file_bytes: bytes, max_rows: int = 200) -> str:
        """
        Converte un CSV in testo lineare leggibile.
        - Rileva delimitatore (',' o ';')
        - Supporta UTF-8 (con/senza BOM) o Latin-1
        - Limita a max_rows per evitare testi enormi
        """
        # decode robusto
        try:
            text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = file_bytes.decode("latin-1")

        # sniff delimiter
        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        except Exception:
            class Dialect(csv.Dialect):
                delimiter = ","
                quotechar = '"'
                doublequote = True
                skipinitialspace = True
                lineterminator = "\n"
                quoting = csv.QUOTE_MINIMAL
            dialect = Dialect()

        reader = csv.reader(io.StringIO(text), dialect=dialect)
        rows = list(reader)
        if not rows:
            return ""

        header = [h.strip() for h in (rows[0] or [])]
        body = rows[1:max_rows+1]

        # Trasforma ogni riga in: "col1: val1 | col2: val2 | ..."
        lines = []
        # prima riga: header compatto per riferimento
        lines.append("; ".join(header))
        for r in body:
            pairs = []
            for col, val in zip(header, r):
                col = (col or "").strip()
                val = (val or "").strip()
                if val:
                    pairs.append(f"{col}: {val}")
            if pairs:
                lines.append(" | ".join(pairs))

        return "\n".join(lines)

    # -----------------------
    # FILE GENERICO
    # -----------------------
    def _bytes_to_text(self, file_data: bytes) -> str:
        """Decode generico robusto per .txt/.md e fallback."""
        try:
            return file_data.decode('utf-8-sig')
        except UnicodeDecodeError:
            return file_data.decode('latin-1', errors='ignore')

    # -----------------------
    # ENTRYPOINT
    # -----------------------
    def process_file(self, file_data: bytes, filename: str, project_id: Optional[str] = None) -> Tuple[List[str], List[dict]]:
        """
        Process uploaded file and return chunks with metadata.
        Supporta: .pdf, .csv, .txt/.md (fallback).
        Parametri:
        - file_data: contenuto del file in bytes
        - filename: nome del file originale
        - project_id: opzionale; usare "GLOBAL" per asset aziendali o l'ID del cantiere per asset di cantiere
        """
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

        if ext == "pdf":
            text = self.extract_text_from_pdf(file_data)
            meta_type = "pdf"
        elif ext == "csv":
            text = self._csv_to_text(file_data)
            meta_type = "csv"
        else:
            text = self._bytes_to_text(file_data)
            meta_type = ext or "txt"

        if not text or not text.strip():
            raise ValueError("File is empty or unreadable")

        # Split into chunks
        chunks = self.text_splitter.split_text(text)

        # Metadata: includiamo source, tipo file, chunk_id e project_id per abilitare filtri per cantiere/GLOBAL
        metadatas = [
            {
                "source": filename,
                "type": meta_type,
                "chunk_id": i,
                "project_id": project_id,
            }
            for i in range(len(chunks))
        ]

        return chunks, metadatas