"""sqlite-vec backed vector store implementation."""

import json
import logging
import struct
from pathlib import Path
from typing import Any

import aiosqlite

from openpaw.stores.vector.base import (
    BaseVectorStore,
    VectorDocument,
    VectorSearchResult,
)

logger = logging.getLogger(__name__)


class SqliteVecStore(BaseVectorStore):
    """sqlite-vec backed vector store.

    Storage: {workspace}/.openpaw/vectors.db
    Uses aiosqlite + sqlite-vec extension for vector similarity search.

    Tables:
    - documents: Standard table for document content and metadata
    - vec_documents: Virtual table for vector similarity search
    """

    def __init__(self, db_path: Path, dimensions: int = 1536):
        """Initialize the sqlite-vec store.

        Args:
            db_path: Path to the SQLite database file.
            dimensions: Dimensionality of embedding vectors (default: 1536).
        """
        self._db_path = Path(db_path)
        self._dimensions = dimensions
        self._conn: aiosqlite.Connection | None = None

        logger.info(f"SqliteVecStore initialized (db: {db_path}, dims: {dimensions})")

    async def initialize(self) -> None:
        """Initialize the database and create tables.

        Loads the sqlite-vec extension and creates the necessary tables.
        """
        import sqlite_vec

        self._conn = await aiosqlite.connect(str(self._db_path))

        # Enable sqlite-vec extension
        await self._conn.enable_load_extension(True)
        await self._conn.load_extension(sqlite_vec.loadable_path())
        await self._conn.enable_load_extension(False)

        # Create documents table for content and metadata
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                conversation_id TEXT
            )
        """)

        # Create vec_documents virtual table for vector search
        await self._conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_documents USING vec0(
                id TEXT PRIMARY KEY,
                embedding float[{self._dimensions}]
            )
        """)

        await self._conn.commit()
        logger.info("SqliteVecStore tables initialized")

    async def add_documents(self, documents: list[VectorDocument]) -> int:
        """Add or update documents in the vector store.

        Args:
            documents: List of documents with embeddings to store.

        Returns:
            Number of documents successfully added.
        """
        if not self._conn:
            raise RuntimeError("Vector store not initialized - call initialize() first")

        count = 0
        for doc in documents:
            if doc.embedding is None:
                logger.warning(f"Skipping document without embedding: {doc.id}")
                continue

            # Insert into documents table
            await self._conn.execute(
                "INSERT OR REPLACE INTO documents (id, content, metadata_json, conversation_id) VALUES (?, ?, ?, ?)",
                (doc.id, doc.content, json.dumps(doc.metadata), doc.metadata.get("conversation_id", ""))
            )

            # Serialize embedding for sqlite-vec
            embedding_bytes = struct.pack(f'{len(doc.embedding)}f', *doc.embedding)

            # Upsert into vec_documents virtual table (vec0 doesn't support INSERT OR REPLACE)
            await self._conn.execute("DELETE FROM vec_documents WHERE id = ?", (doc.id,))
            await self._conn.execute(
                "INSERT INTO vec_documents (id, embedding) VALUES (?, ?)",
                (doc.id, embedding_bytes)
            )

            count += 1

        await self._conn.commit()
        logger.info(f"Added {count} documents to vector store")
        return count

    async def search(
        self,
        query_embedding: list[float],
        limit: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Search for similar documents by embedding.

        Args:
            query_embedding: Query vector to search for.
            limit: Maximum number of results to return.
            metadata_filter: Optional metadata filters (key-value pairs).

        Returns:
            List of search results sorted by relevance (highest first).
        """
        if not self._conn:
            raise RuntimeError("Vector store not initialized - call initialize() first")

        # Serialize query embedding
        query_bytes = struct.pack(f'{len(query_embedding)}f', *query_embedding)

        # Over-fetch if filtering (we'll post-filter metadata)
        fetch_limit = limit * 3 if metadata_filter else limit

        # Vector similarity search: CTE with k= constraint, then JOIN to documents
        cursor = await self._conn.execute(
            """
            WITH knn_matches AS (
                SELECT id, distance
                FROM vec_documents
                WHERE embedding MATCH ? AND k = ?
            )
            SELECT d.id, d.content, d.metadata_json, d.conversation_id, knn.distance
            FROM knn_matches knn
            JOIN documents d ON d.id = knn.id
            ORDER BY knn.distance
            """,
            (query_bytes, fetch_limit)
        )

        rows = await cursor.fetchall()

        results = []
        for row in rows:
            metadata = json.loads(row[2])

            # Apply metadata filter (post-filter)
            if metadata_filter:
                if not all(metadata.get(k) == v for k, v in metadata_filter.items()):
                    continue

            doc = VectorDocument(id=row[0], content=row[1], metadata=metadata)
            # Convert distance to similarity score (1.0 - distance)
            score = 1.0 - row[4]
            results.append(VectorSearchResult(document=doc, score=score))

            if len(results) >= limit:
                break

        logger.debug(f"Vector search returned {len(results)} results")
        return results

    async def delete_by_metadata(self, key: str, value: str) -> int:
        """Delete documents matching a metadata filter.

        Args:
            key: Metadata key to match.
            value: Metadata value to match.

        Returns:
            Number of documents deleted.
        """
        if not self._conn:
            raise RuntimeError("Vector store not initialized - call initialize() first")

        # Find matching document IDs using JSON extraction
        cursor = await self._conn.execute(
            "SELECT id FROM documents WHERE json_extract(metadata_json, ?) = ?",
            (f'$.{key}', value)
        )
        rows = await cursor.fetchall()
        ids = [row[0] for row in rows]

        if not ids:
            return 0

        # Delete from both tables
        placeholders = ','.join('?' * len(ids))
        await self._conn.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", ids)
        await self._conn.execute(f"DELETE FROM vec_documents WHERE id IN ({placeholders})", ids)
        await self._conn.commit()

        logger.info(f"Deleted {len(ids)} documents with {key}={value}")
        return len(ids)

    async def count(self) -> int:
        """Get total number of documents in the store.

        Returns:
            Document count.
        """
        if not self._conn:
            return 0

        cursor = await self._conn.execute("SELECT COUNT(*) FROM documents")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("SqliteVecStore connection closed")
