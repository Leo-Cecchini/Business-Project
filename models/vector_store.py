# Vector store management with Qdrant

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from typing import List, Dict
import uuid

class VectorStore:
    def __init__(self, path: str, collection_name: str, api_key: str):
        # Use local file-based storage instead of server
        self.client = QdrantClient(path=path)
        self.collection_name = collection_name
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="models/embedding-001",
            google_api_key=api_key
        )
        self._ensure_collection()
    
    def _ensure_collection(self):
        """Create collection if it doesn't exist"""
        collections = self.client.get_collections().collections
        collection_names = [col.name for col in collections]
        
        if self.collection_name not in collection_names:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=768, distance=Distance.COSINE)
            )
    
    def add_documents(self, texts: List[str], metadatas: List[Dict]) -> int:
        """Add documents to vector store"""
        embeddings = self.embeddings.embed_documents(texts)
        
        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={
                    "text": text,
                    "metadata": metadata
                }
            )
            for text, embedding, metadata in zip(texts, embeddings, metadatas)
        ]
        
        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )
        
        return len(points)
    
    def search(self, query: str, limit: int = 4) -> List[Dict]:
        """Search for similar documents"""
        query_vector = self.embeddings.embed_query(query)
        
        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit
        )
        
        return [
            {
                "text": hit.payload["text"],
                "metadata": hit.payload["metadata"],
                "score": hit.score
            }
            for hit in results
        ]
    
    def get_all_documents(self) -> List[Dict]:
        """Get all document sources"""
        try:
            result = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                with_payload=True,
                with_vectors=False
            )
            
            sources = set()
            for point in result[0]:
                source = point.payload.get("metadata", {}).get("source", "Unknown")
                sources.add(source)
            
            return [{"source": src, "chunks": 0} for src in sorted(sources)]
        except Exception:
            return []
    
    def delete_all(self):
        """Delete all documents from collection"""
        self.client.delete_collection(self.collection_name)
        self._ensure_collection()