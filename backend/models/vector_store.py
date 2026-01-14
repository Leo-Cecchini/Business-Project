# models/vector_store.py
# Vector store management with Qdrant — robust + rerank + per-cantiere filter

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, MatchAny
)
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Optional
import uuid
import math
import re
import os

# Optional: Google embeddings (se EMBEDDING_MODEL è del tipo "models/text-embedding-004")
try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
except Exception:  # pragma: no cover
    GoogleGenerativeAIEmbeddings = None

# --- Heuristics di dominio per l'edilizia ------------------------------------
PRIORITY_SOURCES = [
    "capitolato", "computo", "computo metrico", "preventivo",
    "offerta", "contratto", "scheda tecnica", "analisi prezzi",
]

def _priority_score(source: str) -> int:
    s = (source or "").lower()
    for i, key in enumerate(PRIORITY_SOURCES):
        if key in s:
            return 100 - i * 10  # 100, 90, 80, ...
    return 0

def _keyword_boost(text: str, query: str) -> float:
    """
    Boost lessicale leggero: +log(1+hits) se i token della query compaiono nel chunk.
    Evita di “dopare” troppo: è solo un tie-breaker.
    """
    if not text or not query:
        return 0.0
    q_tokens = [t for t in re.findall(r"[a-zà-ù0-9]+", query.lower()) if len(t) > 2]
    if not q_tokens:
        return 0.0
    t = text.lower()
    hits = sum(1 for qt in q_tokens if qt in t)
    return math.log(1 + hits)

class VectorStore:
    def __init__(self, path: str, collection_name: str, embedding_model: str, embedding_dim: int):
        # Use local file-based storage instead of server
        try:
            self.client = QdrantClient(path=path)
        except RuntimeError as e:
            if "already accessed" in str(e):
                print(f"⚠️  Warning: {path} is locked by another instance.")
                print("Trying to use in-memory storage instead...")
                self.client = QdrantClient(":memory:")
            else:
                raise e
        
        self.collection_name = collection_name
        self.embedding_dim = int(embedding_dim)

        # Embeddings provider:
        # - Default: SentenceTransformer (locale)
        # - Se embedding_model sembra un modello Gemini embeddings (es. "models/text-embedding-004"),
        #   prova ad usare GoogleGenerativeAIEmbeddings.
        self._embedder_kind = "sentence_transformers"
        self._st_model = None
        self._g_embed = None

        if isinstance(embedding_model, str) and embedding_model.strip().startswith("models/"):
            if GoogleGenerativeAIEmbeddings is None:
                raise RuntimeError(
                    "GoogleGenerativeAIEmbeddings non disponibile. Installa/abilita langchain-google-genai."
                )
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise RuntimeError("GOOGLE_API_KEY mancante: necessario per embeddings Google")
            self._g_embed = GoogleGenerativeAIEmbeddings(model=embedding_model.strip(), google_api_key=api_key)
            self._embedder_kind = "google"
        else:
            self._st_model = SentenceTransformer(embedding_model)
        self._ensure_collection()
        print("Vector store initialized\n")
    
    def _ensure_collection(self):
        """Create collection if it doesn't exist"""
        collections = self.client.get_collections().collections
        collection_names = [col.name for col in collections]
        
        if self.collection_name not in collection_names:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=self.embedding_dim, distance=Distance.COSINE)
            )

    # -------------------- Helper filtro Qdrant --------------------
    def _build_filter(self, where: Optional[Dict]) -> Optional[Filter]:
        """
        Crea un filtro Qdrant da un dizionario 'where' semplice.
        Supporta:
          - {"project_id": 12}
          - puoi estendere aggiungendo altre chiavi -> metadata.<key>
        """
        if not where:
            return None

        must = []
        for key, val in where.items():
            if val is None:
                continue
            # Supporta sia match singolo che lista di valori (OR semplice).
            # Esempio: {"project_id": ["123", 123]}
            if isinstance(val, (list, tuple, set)):
                from qdrant_client.models import MatchAny
                must.append(
                    FieldCondition(
                        key=f"metadata.{key}",
                        match=MatchAny(any=list(val))
                    )
                )
            else:
                must.append(
                    FieldCondition(
                        key=f"metadata.{key}",
                        match=MatchValue(value=val)
                    )
                )

        if not must:
            return None
        return Filter(must=must)

    # -------------------- Upsert documenti -----------------------
    def add_documents(self, texts: List[str], metadatas: List[Dict]) -> int:
        """Add documents to vector store.
        Ogni metadata può contenere, ad esempio:
        {
            "source": "file.pdf",
            "page": 3,
            "project_id": 12,  # ⬅️ per filtro per cantiere
            ...
        }
        """
        if len(texts) != len(metadatas):
            raise ValueError("texts e metadatas devono avere la stessa lunghezza")
        if not texts:
            return 0

        # Embeddings
        if self._embedder_kind == "google":
            # LangChain embeddings (batch)
            embeddings = self._g_embed.embed_documents(texts)
        else:
            embeddings = self._st_model.encode(texts, show_progress_bar=False).tolist()
        
        points = []
        for text, embedding, metadata in zip(texts, embeddings, metadatas):
            payload = {
                "text": text or "",
                "metadata": metadata or {}
            }
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    payload=payload
                )
            )
        
        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)
        return len(points)

    # -------------------- Ricerca con rerank + filtro -------------
    def search(self, query: str, limit: int = 12, where: Optional[Dict] = None) -> List[Dict]:
        """
        Search for similar documents con rerank + filtro opzionale:
        - prende più risultati (>=12) dal vettoriale
        - applica filtro per metadata (es. where={"project_id": 12})
        - calcola punteggio combinato: base_score + 0.01*priority + 0.05*keyword_boost
        - ordina e taglia a 'limit'
        Ritorna: [{"text", "metadata": {...}, "score"}]
        """
        if not query or not query.strip():
            return []

        # 1) Vettoriale
        if self._embedder_kind == "google":
            query_vector = self._g_embed.embed_query(query)
        else:
            query_vector = self._st_model.encode([query], show_progress_bar=False)[0].tolist()
        raw_limit = max(limit, 12)  # prendiamo più hit, poi rerankiamo
        q_filter = self._build_filter(where)

        raw_hits = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=raw_limit,
            query_filter=q_filter
        )

        # 2) Normalizza + rerank
        results = []
        for h in raw_hits:
            payload = getattr(h, "payload", {}) or {}
            text = payload.get("text", "")
            md = payload.get("metadata", {}) or {}
            source = md.get("source", "") or ""

            base_score = float(getattr(h, "score", 0.0))  # cosine sim (più alto = meglio)
            prio = _priority_score(source)                # 0..100
            kw = _keyword_boost(text, query)              # 0..~log

            rerank_score = base_score + (0.01 * prio) + (0.05 * kw)

            results.append({
                "text": text,
                "metadata": md,
                "score": rerank_score,   # punteggio finale usato per l'ordinamento
                "_base": base_score,     # (debug) punteggio originale
                "_prio": prio,           # (debug)
                "_kw": kw                # (debug)
            })

        # 3) Ordina per score combinato e taglia
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]
    
    # -------------------- Utility elenco sorgenti -----------------
    def get_all_documents(self, where: Optional[Dict] = None) -> List[Dict]:
        """Get all document sources + conteggio chunk per ciascuna fonte (opz. filtrato)."""
        try:
            result = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                with_payload=True,
                with_vectors=False
            )
            sources = {}
            for point in result[0]:
                payload = point.payload or {}
                md = payload.get("metadata", {}) or {}

                # Filtro lato-client se where presente (alcune versioni locali non supportano Filter in scroll)
                if where:
                    ok = True
                    for k, v in where.items():
                        if v is None:
                            continue
                        if md.get(k) != v:
                            ok = False
                            break
                    if not ok:
                        continue

                src = md.get("source", "Unknown")
                sources[src] = sources.get(src, 0) + 1
            
            return [{"source": src, "chunks": cnt} for src, cnt in sorted(sources.items())]
        except Exception:
            return []
    
    def delete_all(self):
        """Delete all documents from collection"""
        self.client.delete_collection(self.collection_name)
        self._ensure_collection()