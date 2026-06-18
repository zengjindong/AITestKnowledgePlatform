"""
Memory system for storing and retrieving business rules, experience, and context.

This module provides a SQLite-based storage system for:
- Memory Units (business rules and experience)
- Question & Answer records
- Evidence chains
- Test cases
"""
import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import DB_CONFIG, STORAGE_CONFIG

logger = logging.getLogger(__name__)


@dataclass
class MemoryUnit:
    """A memory unit storing business rules or experience."""
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    vector: Optional[List[float]] = None
    source_type: str = "user_answer"  # user_answer, code_analysis, llm_inference
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "vector": self.vector,
            "source_type": self.source_type,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryUnit":
        return cls(**data)


@dataclass
class QARecord:
    """Question and Answer record."""
    q_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    context: str = ""
    question: str = ""
    answer: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "q_id": self.q_id,
            "context": self.context,
            "question": self.question,
            "answer": self.answer,
            "created_at": self.created_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QARecord":
        return cls(**data)


@dataclass
class TestCaseRecord:
    """Stored test case with evidence chain."""
    tc_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    requirement_id: str = ""
    title: str = ""
    content: str = ""  # JSON string of the full test case
    evidence_chain: str = ""  # JSON string of evidence chain
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tc_id": self.tc_id,
            "requirement_id": self.requirement_id,
            "title": self.title,
            "content": self.content,
            "evidence_chain": self.evidence_chain,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestCaseRecord":
        return cls(**data)

class MemoryStorage:
    """
    SQLite-based memory storage for the multi-agent system.

    Provides methods for storing and retrieving:
    - Memory units (business rules, experience)
    - Q&A records
    - Evidence chains
    - Test cases
    """

    def __init__(self, db_path: str = None):
        """
        Initialize the memory storage.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path or str(DB_CONFIG.get("path", "data/memory.db"))
        self._in_memory = self.db_path == ":memory:"
        self._connection = None  # For in-memory database
        self._ensure_data_dir()
        self._init_database()

        logger.info(f"MemoryStorage initialized with db: {self.db_path}")

    def _ensure_data_dir(self) -> None:
        """Ensure the data directory exists."""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        if self._in_memory:
            if self._connection is None:
                self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
                self._connection.row_factory = sqlite3.Row
            return self._connection
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

    def _init_database(self) -> None:
        """Initialize database tables."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Memory units table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_units (
                    memory_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    vector TEXT,
                    source_type TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Q&A records table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS qa_records (
                    q_id TEXT PRIMARY KEY,
                    context TEXT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # Evidence chains table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS evidence_chains (
                    chain_id TEXT PRIMARY KEY,
                    test_case_id TEXT NOT NULL,
                    evidence_chain TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Test cases table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS test_cases (
                    tc_id TEXT PRIMARY KEY,
                    requirement_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    evidence_chain TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Conversation history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            conn.commit()

    # Memory Unit Operations
    def save_memory_unit(self, memory: MemoryUnit) -> bool:
        """
        Save a memory unit to the database.

        Args:
            memory: MemoryUnit to save

        Returns:
            True if successful
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO memory_units
                    (memory_id, content, vector, source_type, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    memory.memory_id,
                    memory.content,
                    json.dumps(memory.vector) if memory.vector else None,
                    memory.source_type,
                    json.dumps(memory.metadata),
                    memory.created_at,
                    datetime.now().isoformat()
                ))
                conn.commit()
            logger.debug(f"Saved memory unit: {memory.memory_id}")

            # Also store in vector store for semantic search
            self._save_to_vector_store(memory)

            return True
        except Exception as e:
            logger.error(f"Error saving memory unit: {e}")
            return False

    def _save_to_vector_store(self, memory: MemoryUnit) -> None:
        """Save memory unit vector to vector store for semantic search."""
        try:
            from src.memory.vector_store import get_vector_store, generate_embedding

            vector_store = get_vector_store()

            # Generate embedding if not provided
            vector = memory.vector
            if vector is None and memory.content:
                vector = generate_embedding(memory.content)

            if vector:
                vector_store.add_vector(
                    memory_id=memory.memory_id,
                    content=memory.content,
                    vector=vector
                )
                logger.debug(f"Saved vector for memory: {memory.memory_id}")
        except ImportError:
            logger.debug("Vector store not available, skipping vector storage")
        except Exception as e:
            logger.warning(f"Error saving to vector store: {e}")

    def get_memory_unit(self, memory_id: str) -> Optional[MemoryUnit]:
        """Get a memory unit by ID."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM memory_units WHERE memory_id = ?",
                    (memory_id,)
                )
                row = cursor.fetchone()
                if row:
                    return MemoryUnit(
                        memory_id=row["memory_id"],
                        content=row["content"],
                        vector=json.loads(row["vector"]) if row["vector"] else None,
                        source_type=row["source_type"],
                        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                        created_at=row["created_at"],
                        updated_at=row["updated_at"]
                    )
        except Exception as e:
            logger.error(f"Error getting memory unit: {e}")
        return None

    def search_memory_units(
        self,
        query: str = None,
        source_type: str = None,
        limit: int = 10
    ) -> List[MemoryUnit]:
        """
        Search memory units by content or source type.

        Args:
            query: Text search query
            source_type: Filter by source type
            limit: Maximum results

        Returns:
            List of matching MemoryUnits
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                sql = "SELECT * FROM memory_units WHERE 1=1"
                params = []

                if query:
                    sql += " AND content LIKE ?"
                    params.append(f"%{query}%")

                if source_type:
                    sql += " AND source_type = ?"
                    params.append(source_type)

                sql += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)

                cursor.execute(sql, params)
                rows = cursor.fetchall()

                return [
                    MemoryUnit(
                        memory_id=row["memory_id"],
                        content=row["content"],
                        vector=json.loads(row["vector"]) if row["vector"] else None,
                        source_type=row["source_type"],
                        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                        created_at=row["created_at"],
                        updated_at=row["updated_at"]
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error searching memory units: {e}")
            return []

    def search_similar(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.5,
        source_type: str = None
    ) -> List[Dict[str, Any]]:
        """
        Search memory units using semantic vector similarity.

        Args:
            query: Search query text (will be embedded)
            limit: Maximum number of results
            threshold: Minimum similarity threshold (0-1)
            source_type: Optional filter by source type

        Returns:
            List of matching memory units with similarity scores
        """
        try:
            from src.memory.vector_store import get_vector_store

            vector_store = get_vector_store()

            # Search in vector store
            vector_results = vector_store.search_similar(query, limit=limit, threshold=threshold)

            # If no results, fall back to keyword search
            if not vector_results:
                logger.info("Vector search returned no results, falling back to keyword search")
                units = self.search_memory_units(query=query, source_type=source_type, limit=limit)
                return [
                    {
                        "memory": unit,
                        "content": unit.content,
                        "similarity": 1.0,  # Keyword matches get full score
                        "match_type": "keyword"
                    }
                    for unit in units
                ]

            # Enrich with full memory unit data
            results = []
            for vr in vector_results:
                memory = self.get_memory_unit(vr["memory_id"])
                if memory:
                    # Apply source_type filter if specified
                    if source_type and memory.source_type != source_type:
                        continue
                    results.append({
                        "memory": memory,
                        "content": vr["content"],
                        "similarity": vr["similarity"],
                        "match_type": "vector"
                    })

            return results

        except ImportError:
            logger.warning("Vector store not available, using keyword search")
            units = self.search_memory_units(query=query, source_type=source_type, limit=limit)
            return [{"memory": unit, "content": unit.content, "similarity": 1.0, "match_type": "keyword"} for unit in units]
        except Exception as e:
            logger.error(f"Error in semantic search: {e}")
            # Fallback to keyword search on error
            units = self.search_memory_units(query=query, source_type=source_type, limit=limit)
            return [{"memory": unit, "content": unit.content, "similarity": 1.0, "match_type": "keyword"} for unit in units]

    # Q&A Record Operations
    def save_qa_record(self, record: QARecord) -> bool:
        """Save a Q&A record."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO qa_records
                    (q_id, context, question, answer, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    record.q_id,
                    record.context,
                    record.question,
                    record.answer,
                    record.created_at
                ))
                conn.commit()
            logger.debug(f"Saved QA record: {record.q_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving QA record: {e}")
            return False

    def get_qa_records(self, limit: int = 50) -> List[QARecord]:
        """Get recent Q&A records."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM qa_records ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
                rows = cursor.fetchall()
                return [
                    QARecord(
                        q_id=row["q_id"],
                        context=row["context"],
                        question=row["question"],
                        answer=row["answer"],
                        created_at=row["created_at"]
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error getting QA records: {e}")
            return []

    # Evidence Chain Operations
    def save_evidence_chain(
        self,
        chain_id: str,
        test_case_id: str,
        evidence_chain: Dict[str, Any]
    ) -> bool:
        """Save an evidence chain."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                cursor.execute("""
                    INSERT OR REPLACE INTO evidence_chains
                    (chain_id, test_case_id, evidence_chain, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    chain_id,
                    test_case_id,
                    json.dumps(evidence_chain, ensure_ascii=False),
                    now,
                    now
                ))
                conn.commit()
            logger.debug(f"Saved evidence chain: {chain_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving evidence chain: {e}")
            return False

    def get_evidence_chain(self, chain_id: str) -> Optional[Dict[str, Any]]:
        """Get an evidence chain by ID."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT evidence_chain FROM evidence_chains WHERE chain_id = ?",
                    (chain_id,)
                )
                row = cursor.fetchone()
                if row:
                    return json.loads(row["evidence_chain"])
        except Exception as e:
            logger.error(f"Error getting evidence chain: {e}")
        return None

    # Test Case Operations
    def save_test_case(self, test_case: TestCaseRecord) -> bool:
        """Save a test case."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO test_cases
                    (tc_id, requirement_id, title, content, evidence_chain, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    test_case.tc_id,
                    test_case.requirement_id,
                    test_case.title,
                    test_case.content,
                    test_case.evidence_chain,
                    test_case.created_at,
                    datetime.now().isoformat()
                ))
                conn.commit()
            logger.debug(f"Saved test case: {test_case.tc_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving test case: {e}")
            return False

    def get_test_cases(
        self,
        requirement_id: str = None,
        limit: int = 50
    ) -> List[TestCaseRecord]:
        """Get test cases, optionally filtered by requirement ID."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                if requirement_id:
                    cursor.execute(
                        """SELECT * FROM test_cases
                           WHERE requirement_id = ?
                           ORDER BY created_at DESC LIMIT ?""",
                        (requirement_id, limit)
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM test_cases ORDER BY created_at DESC LIMIT ?",
                        (limit,)
                    )

                rows = cursor.fetchall()
                return [
                    TestCaseRecord(
                        tc_id=row["tc_id"],
                        requirement_id=row["requirement_id"],
                        title=row["title"],
                        content=row["content"],
                        evidence_chain=row["evidence_chain"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"]
                    )
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error getting test cases: {e}")
            return []

    # Conversation History
    def save_conversation_message(
        self,
        role: str,
        content: str,
        metadata: Dict[str, Any] = None
    ) -> bool:
        """Save a conversation message."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO conversation_history
                    (role, content, metadata, created_at)
                    VALUES (?, ?, ?, ?)
                """, (
                    role,
                    content,
                    json.dumps(metadata) if metadata else None,
                    datetime.now().isoformat()
                ))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving conversation message: {e}")
            return False

    def get_conversation_history(
        self,
        role: str = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get conversation history."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                if role:
                    cursor.execute(
                        """SELECT * FROM conversation_history
                           WHERE role = ? ORDER BY created_at DESC LIMIT ?""",
                        (role, limit)
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM conversation_history ORDER BY created_at DESC LIMIT ?",
                        (limit,)
                    )

                rows = cursor.fetchall()
                return [
                    {
                        "role": row["role"],
                        "content": row["content"],
                        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                        "created_at": row["created_at"]
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Error getting conversation history: {e}")
            return []

    # Utility Methods
    def get_stats(self) -> Dict[str, int]:
        """Get storage statistics."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                stats = {}

                tables = ["memory_units", "qa_records", "evidence_chains", "test_cases", "conversation_history"]
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
                    stats[table] = cursor.fetchone()["count"]

                return stats
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}

    def clear_all(self) -> bool:
        """Clear all data from the database. Use with caution!"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                for table in ["memory_units", "qa_records", "evidence_chains", "test_cases", "conversation_history"]:
                    cursor.execute(f"DELETE FROM {table}")
                conn.commit()
            logger.warning("Cleared all data from memory storage")
            return True
        except Exception as e:
            logger.error(f"Error clearing data: {e}")
            return False