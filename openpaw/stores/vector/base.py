"""Base abstractions for vector storage and retrieval."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VectorDocument:
    """A document stored in the vector store.

    Attributes:
        id: Unique document identifier.
        content: Text content of the document.
        metadata: Key-value metadata for filtering.
        embedding: Vector embedding (set after embedding generation).
    """

    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None


@dataclass
class VectorSearchResult:
    """A search result with relevance score.

    Attributes:
        document: The matched document.
        score: Relevance score (0-1, higher is more relevant).
    """

    document: VectorDocument
    score: float


class BaseVectorStore(ABC):
    """Abstract base class for vector storage backends.

    Provides a common interface for storing and searching document embeddings.
    Implementations can use different backends (sqlite-vec, pgvector, etc.).
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the vector store (create tables, load extensions, etc.).

        Must be called before any other operations.
        """
        ...

    @abstractmethod
    async def add_documents(self, documents: list[VectorDocument]) -> int:
        """Add or update documents in the vector store.

        Args:
            documents: List of documents with embeddings to store.

        Returns:
            Number of documents successfully added.
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def delete_by_metadata(self, key: str, value: str) -> int:
        """Delete documents matching a metadata filter.

        Args:
            key: Metadata key to match.
            value: Metadata value to match.

        Returns:
            Number of documents deleted.
        """
        ...

    @abstractmethod
    async def count(self) -> int:
        """Get total number of documents in the store.

        Returns:
            Document count.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close any open connections and clean up resources."""
        ...
