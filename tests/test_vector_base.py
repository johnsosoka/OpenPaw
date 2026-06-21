"""Tests for vector store base abstractions."""

from typing import Any

import pytest

from openpaw.stores.vector.base import BaseVectorStore, VectorDocument, VectorSearchResult


class TestVectorDocument:
    """Test suite for VectorDocument dataclass."""

    def test_create_with_defaults(self):
        """Can create VectorDocument with minimal fields."""
        doc = VectorDocument(id="doc1", content="Hello world")

        assert doc.id == "doc1"
        assert doc.content == "Hello world"
        assert doc.metadata == {}
        assert doc.embedding is None

    def test_create_with_all_fields(self):
        """Can create VectorDocument with all fields specified."""
        metadata = {"source": "test", "timestamp": "2026-02-16"}
        embedding = [0.1, 0.2, 0.3, 0.4]

        doc = VectorDocument(
            id="doc2",
            content="Test content",
            metadata=metadata,
            embedding=embedding
        )

        assert doc.id == "doc2"
        assert doc.content == "Test content"
        assert doc.metadata == metadata
        assert doc.embedding == embedding

    def test_create_with_embedding_only(self):
        """Can create VectorDocument with embedding but default metadata."""
        embedding = [0.5, 0.6, 0.7, 0.8]

        doc = VectorDocument(
            id="doc3",
            content="Content",
            embedding=embedding
        )

        assert doc.id == "doc3"
        assert doc.embedding == embedding
        assert doc.metadata == {}

    def test_metadata_default_is_new_dict(self):
        """Each VectorDocument gets its own metadata dict."""
        doc1 = VectorDocument(id="doc1", content="Content 1")
        doc2 = VectorDocument(id="doc2", content="Content 2")

        doc1.metadata["key"] = "value"

        assert "key" in doc1.metadata
        assert "key" not in doc2.metadata


class TestVectorSearchResult:
    """Test suite for VectorSearchResult dataclass."""

    def test_create_search_result(self):
        """Can create VectorSearchResult with document and score."""
        doc = VectorDocument(id="doc1", content="Test")
        result = VectorSearchResult(document=doc, score=0.95)

        assert result.document == doc
        assert result.score == 0.95

    def test_search_result_with_high_score(self):
        """Search result can have high similarity score."""
        doc = VectorDocument(id="doc2", content="Match")
        result = VectorSearchResult(document=doc, score=0.99)

        assert result.score == 0.99

    def test_search_result_with_low_score(self):
        """Search result can have low similarity score."""
        doc = VectorDocument(id="doc3", content="Weak match")
        result = VectorSearchResult(document=doc, score=0.42)

        assert result.score == 0.42


class TestBaseVectorStore:
    """Test suite for BaseVectorStore ABC."""

    def test_cannot_instantiate_directly(self):
        """BaseVectorStore cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseVectorStore()

    def test_concrete_subclass_must_implement_all_methods(self):
        """Concrete subclass must implement all abstract methods."""
        class IncompleteStore(BaseVectorStore):
            async def initialize(self) -> None:
                pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteStore()

    def test_concrete_subclass_with_all_methods(self):
        """Concrete subclass can be instantiated if all methods implemented."""
        class CompleteStore(BaseVectorStore):
            async def initialize(self) -> None:
                pass

            async def add_documents(self, documents: list[VectorDocument]) -> int:
                return 0

            async def search(
                self,
                query_embedding: list[float],
                limit: int = 5,
                metadata_filter: dict[str, Any] | None = None
            ) -> list[VectorSearchResult]:
                return []

            async def delete_by_metadata(self, key: str, value: str) -> int:
                return 0

            async def count(self) -> int:
                return 0

            async def close(self) -> None:
                pass

        store = CompleteStore()
        assert isinstance(store, BaseVectorStore)
