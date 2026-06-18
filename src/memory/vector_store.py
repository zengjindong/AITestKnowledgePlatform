"""
Vector embedding module for semantic memory search.

This module provides embedding generation and vector storage capabilities:
- Text embedding using multiple backends (sentence-transformers, TF-IDF fallback)
- Cosine similarity search
- Integration with MemoryStorage for hybrid search

PRD Reference: Section 6.2.1 - Vector database for memory embeddings
"""
import json
import logging
import math
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EmbeddingGenerator:
    """
    Generate embeddings for text using available backends.

    Priority:
    1. sentence-transformers (best quality)
    2. TF-IDF (fallback, no external dependencies)
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._backend = None
        self._init_backend()

    def _init_backend(self) -> None:
        """Initialize the best available embedding backend."""
        # Try sentence-transformers first
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            self._backend = "sentence_transformers"
            logger.info(f"Initialized sentence-transformers with model: {self.model_name}")
            return
        except ImportError:
            logger.warning("sentence-transformers not available, falling back to TF-IDF")

        # Fallback to TF-IDF
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            self._model = TfidfVectorizer(max_features=384)
            self._backend = "tfidf"
            logger.info("Initialized TF-IDF embedding backend")
        except ImportError:
            logger.warning("sklearn not available, using simple hash embeddings")
            self._model = None
            self._backend = "hash"

    def encode(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to encode

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        if self._backend == "sentence_transformers":
            return self._encode_sentence_transformers(texts)
        elif self._backend == "tfidf":
            return self._encode_tfidf(texts)
        else:
            return self._encode_hash(texts)

    def _encode_sentence_transformers(self, texts: List[str]) -> List[List[float]]:
        """Encode using sentence-transformers."""
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    def _encode_tfidf(self, texts: List[str]) -> List[List[float]]:
        """Encode using TF-IDF."""
        from sklearn.feature_extraction.text import TfidfVectorizer

        # Fit on all texts
        tfidf = TfidfVectorizer(max_features=384)
        try:
            matrix = tfidf.fit_transform(texts).toarray()
            return matrix.tolist()
        except Exception as e:
            logger.warning(f"TF-IDF encoding failed: {e}, using hash fallback")
            return self._encode_hash(texts)

    def _encode_hash(self, texts: List[str]) -> List[List[float]]:
        """Simple hash-based embedding as last resort."""
        embeddings = []
        for text in texts:
            # Create a simple pseudo-embedding from text hash
            vec = [0.0] * 128
            for i, c in enumerate(text[:128]):
                vec[i] = (ord(c) / 255.0) * 0.1
            embeddings.append(vec)
        return embeddings

    @property
    def embedding_dim(self) -> int:
        """Get embedding dimension."""
        if self._backend == "sentence_transformers":
            return self._model.get_sentence_embedding_dimension()
        elif self._backend == "tfidf":
            return 384
        return 128


class VectorStore:
    """
    Vector storage for semantic search.

    Provides cosine similarity search over embedded memory units.
    Uses SQLite with JSON-encoded vectors for simplicity.
    For production, consider Milvus or Weaviate.

    PRD Reference: Section 6.2.1 - Vector database requirement
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(Path(__file__).parent.parent / "data" / "vectors.db")
        self._ensure_data_dir()
        self._init_db()
        self.embedding_generator = EmbeddingGenerator()

    def _ensure_data_dir(self) -> None:
        """Ensure data directory exists."""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    def _init_db(self) -> None:
        """Initialize vector store database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vector_store (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    content TEXT,
                    vector TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_id
                ON vector_store(memory_id)
            """)
            conn.commit()
        logger.info(f"VectorStore initialized at {self.db_path}")

    def add_vector(
        self,
        memory_id: str,
        content: str,
        vector: List[float]
    ) -> bool:
        """
        Add a vector to the store.

        Args:
            memory_id: Associated memory unit ID
            content: Original text content
            vector: Embedding vector

        Returns:
            True if successful
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO vector_store
                    (id, memory_id, content, vector, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    str(uuid.uuid4()),
                    memory_id,
                    content,
                    json.dumps(vector),
                    datetime.now().isoformat()
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding vector: {e}")
            return False

    def search_similar(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Search for similar memory units using cosine similarity.

        Args:
            query: Search query text
            limit: Maximum number of results
            threshold: Minimum similarity threshold (0-1)

        Returns:
            List of matching memory units with similarity scores
        """
        try:
            # Generate query embedding
            query_embedding = self.embedding_generator.encode([query])[0]

            # Get all vectors from DB
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM vector_store")
                rows = cursor.fetchall()

            # Calculate similarities
            results = []
            for row in rows:
                stored_vector = json.loads(row["vector"])
                similarity = self._cosine_similarity(query_embedding, stored_vector)

                if similarity >= threshold:
                    results.append({
                        "memory_id": row["memory_id"],
                        "content": row["content"],
                        "similarity": similarity,
                        "created_at": row["created_at"]
                    })

            # Sort by similarity and limit
            results.sort(key=lambda x: x["similarity"], reverse=True)
            return results[:limit]

        except Exception as e:
            logger.error(f"Error searching vectors: {e}")
            return []

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(a) != len(b):
            # Pad shorter vector
            max_len = max(len(a), len(b))
            a = a + [0.0] * (max_len - len(a))
            b = b + [0.0] * (max_len - len(b))

        dot_product = sum(x * y for x, y in zip(a, b))
        magnitude_a = math.sqrt(sum(x * x for x in a))
        magnitude_b = math.sqrt(sum(x * x for x in b))

        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0

        return dot_product / (magnitude_a * magnitude_b)

    def delete_by_memory_id(self, memory_id: str) -> bool:
        """Delete vectors associated with a memory ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM vector_store WHERE memory_id = ?",
                    (memory_id,)
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting vectors: {e}")
            return False

    def get_stats(self) -> Dict[str, int]:
        """Get vector store statistics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as count FROM vector_store")
                return {"vectors": cursor.fetchone()["count"]}
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"vectors": 0}


# Import uuid and Path for this module
import uuid
from pathlib import Path
from datetime import datetime


# Singleton instance
_vector_store: Optional[VectorStore] = None


def get_vector_store(db_path: str = None) -> VectorStore:
    """Get singleton vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(db_path)
    return _vector_store


def generate_embedding(text: str) -> Optional[List[float]]:
    """Convenience function to generate embedding for a single text."""
    try:
        generator = EmbeddingGenerator()
        embeddings = generator.encode([text])
        return embeddings[0] if embeddings else None
    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        return None