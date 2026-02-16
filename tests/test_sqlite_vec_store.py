"""Tests for sqlite-vec backed vector store implementation."""

import pytest

sqlite_vec = pytest.importorskip("sqlite_vec")

from openpaw.stores.vector.base import VectorDocument  # noqa: E402
from openpaw.stores.vector.sqlite_vec import SqliteVecStore  # noqa: E402


@pytest.fixture
async def store(tmp_path):
    """Create a SqliteVecStore instance for testing."""
    db_path = tmp_path / "test_vectors.db"
    store = SqliteVecStore(db_path=db_path, dimensions=4)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def sample_documents():
    """Create sample documents with 4-dimensional embeddings."""
    return [
        VectorDocument(
            id="doc1",
            content="Python programming",
            metadata={"topic": "coding", "language": "python"},
            embedding=[0.1, 0.2, 0.3, 0.4]
        ),
        VectorDocument(
            id="doc2",
            content="Machine learning basics",
            metadata={"topic": "ai", "language": "python"},
            embedding=[0.2, 0.3, 0.4, 0.5]
        ),
        VectorDocument(
            id="doc3",
            content="JavaScript frameworks",
            metadata={"topic": "coding", "language": "javascript"},
            embedding=[0.8, 0.7, 0.6, 0.5]
        ),
    ]


class TestSqliteVecStoreInitialization:
    """Test suite for SqliteVecStore initialization."""

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, tmp_path):
        """Initialize creates necessary database tables."""
        db_path = tmp_path / "test.db"
        store = SqliteVecStore(db_path=db_path, dimensions=4)

        await store.initialize()

        assert db_path.exists()
        await store.close()

    @pytest.mark.asyncio
    async def test_initialize_can_be_called_multiple_times(self, tmp_path):
        """Initialize is idempotent and can be called multiple times."""
        db_path = tmp_path / "test.db"
        store = SqliteVecStore(db_path=db_path, dimensions=4)

        await store.initialize()
        await store.initialize()

        assert db_path.exists()
        await store.close()

    @pytest.mark.asyncio
    async def test_operations_before_initialize_raise_error(self, tmp_path):
        """Operations before initialize raise RuntimeError."""
        db_path = tmp_path / "test.db"
        store = SqliteVecStore(db_path=db_path, dimensions=4)

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.add_documents([])

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.search([0.1, 0.2, 0.3, 0.4])

        with pytest.raises(RuntimeError, match="not initialized"):
            await store.delete_by_metadata("key", "value")


class TestSqliteVecStoreAddDocuments:
    """Test suite for adding documents to vector store."""

    @pytest.mark.asyncio
    async def test_add_documents_inserts_correctly(self, store, sample_documents):
        """Add documents inserts them correctly."""
        count = await store.add_documents(sample_documents)

        assert count == 3
        total = await store.count()
        assert total == 3

    @pytest.mark.asyncio
    async def test_add_documents_returns_count(self, store):
        """Add documents returns the number of documents added."""
        docs = [
            VectorDocument(id="doc1", content="Content 1", embedding=[0.1, 0.2, 0.3, 0.4]),
            VectorDocument(id="doc2", content="Content 2", embedding=[0.5, 0.6, 0.7, 0.8]),
        ]

        count = await store.add_documents(docs)

        assert count == 2

    @pytest.mark.asyncio
    async def test_add_documents_skips_without_embeddings(self, store):
        """Add documents skips documents without embeddings."""
        docs = [
            VectorDocument(id="doc1", content="With embedding", embedding=[0.1, 0.2, 0.3, 0.4]),
            VectorDocument(id="doc2", content="Without embedding"),
            VectorDocument(id="doc3", content="Also with embedding", embedding=[0.5, 0.6, 0.7, 0.8]),
        ]

        count = await store.add_documents(docs)

        assert count == 2
        total = await store.count()
        assert total == 2

    @pytest.mark.asyncio
    async def test_add_documents_replaces_existing(self, store):
        """Add documents with same ID replaces existing document."""
        doc1 = VectorDocument(
            id="doc1",
            content="Original content",
            metadata={"version": "1"},
            embedding=[0.1, 0.2, 0.3, 0.4]
        )
        await store.add_documents([doc1])

        doc1_updated = VectorDocument(
            id="doc1",
            content="Updated content",
            metadata={"version": "2"},
            embedding=[0.5, 0.6, 0.7, 0.8]
        )
        count = await store.add_documents([doc1_updated])

        assert count == 1
        total = await store.count()
        assert total == 1

        results = await store.search([0.5, 0.6, 0.7, 0.8], limit=1)
        assert results[0].document.content == "Updated content"
        assert results[0].document.metadata["version"] == "2"


class TestSqliteVecStoreSearch:
    """Test suite for searching documents in vector store."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, store, sample_documents):
        """Search returns results sorted by relevance."""
        await store.add_documents(sample_documents)

        results = await store.search([0.1, 0.2, 0.3, 0.4], limit=3)

        assert len(results) > 0
        assert all(hasattr(r, 'document') for r in results)
        assert all(hasattr(r, 'score') for r in results)

    @pytest.mark.asyncio
    async def test_search_respects_limit(self, store, sample_documents):
        """Search respects the limit parameter."""
        await store.add_documents(sample_documents)

        results = await store.search([0.1, 0.2, 0.3, 0.4], limit=2)

        assert len(results) <= 2

    @pytest.mark.asyncio
    async def test_search_with_metadata_filter(self, store, sample_documents):
        """Search with metadata filter returns only matching documents."""
        await store.add_documents(sample_documents)

        results = await store.search(
            [0.1, 0.2, 0.3, 0.4],
            limit=5,
            metadata_filter={"language": "python"}
        )

        assert len(results) == 2
        assert all(r.document.metadata["language"] == "python" for r in results)

    @pytest.mark.asyncio
    async def test_search_with_metadata_filter_multiple_keys(self, store, sample_documents):
        """Search with multiple metadata filter keys."""
        await store.add_documents(sample_documents)

        results = await store.search(
            [0.1, 0.2, 0.3, 0.4],
            limit=5,
            metadata_filter={"topic": "coding", "language": "python"}
        )

        assert len(results) == 1
        assert results[0].document.id == "doc1"

    @pytest.mark.asyncio
    async def test_search_returns_empty_for_no_matches(self, store):
        """Search returns empty list when no documents exist."""
        results = await store.search([0.1, 0.2, 0.3, 0.4], limit=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_scores_are_similarity_not_distance(self, store, sample_documents):
        """Search scores are similarity (1 - distance) not raw distance."""
        await store.add_documents(sample_documents)

        results = await store.search([0.1, 0.2, 0.3, 0.4], limit=3)

        for result in results:
            assert 0.0 <= result.score <= 1.0

    @pytest.mark.asyncio
    async def test_search_results_sorted_by_relevance(self, store, sample_documents):
        """Search results are sorted by relevance (highest score first)."""
        await store.add_documents(sample_documents)

        results = await store.search([0.1, 0.2, 0.3, 0.4], limit=3)

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)


class TestSqliteVecStoreDelete:
    """Test suite for deleting documents from vector store."""

    @pytest.mark.asyncio
    async def test_delete_by_metadata_removes_documents(self, store, sample_documents):
        """Delete by metadata removes matching documents."""
        await store.add_documents(sample_documents)

        deleted_count = await store.delete_by_metadata("language", "python")

        assert deleted_count == 2
        remaining = await store.count()
        assert remaining == 1

    @pytest.mark.asyncio
    async def test_delete_by_metadata_returns_count(self, store, sample_documents):
        """Delete by metadata returns the number of deleted documents."""
        await store.add_documents(sample_documents)

        deleted_count = await store.delete_by_metadata("topic", "coding")

        assert deleted_count == 2

    @pytest.mark.asyncio
    async def test_delete_by_metadata_no_matches(self, store, sample_documents):
        """Delete by metadata returns 0 when no documents match."""
        await store.add_documents(sample_documents)

        deleted_count = await store.delete_by_metadata("language", "rust")

        assert deleted_count == 0
        total = await store.count()
        assert total == 3

    @pytest.mark.asyncio
    async def test_delete_by_conversation_id(self, store):
        """Delete by conversation_id removes all documents from that conversation."""
        docs = [
            VectorDocument(
                id="doc1",
                content="Content 1",
                metadata={"conversation_id": "conv1"},
                embedding=[0.1, 0.2, 0.3, 0.4]
            ),
            VectorDocument(
                id="doc2",
                content="Content 2",
                metadata={"conversation_id": "conv1"},
                embedding=[0.2, 0.3, 0.4, 0.5]
            ),
            VectorDocument(
                id="doc3",
                content="Content 3",
                metadata={"conversation_id": "conv2"},
                embedding=[0.3, 0.4, 0.5, 0.6]
            ),
        ]
        await store.add_documents(docs)

        deleted_count = await store.delete_by_metadata("conversation_id", "conv1")

        assert deleted_count == 2
        remaining = await store.count()
        assert remaining == 1


class TestSqliteVecStoreCount:
    """Test suite for counting documents in vector store."""

    @pytest.mark.asyncio
    async def test_count_returns_zero_for_empty_store(self, store):
        """Count returns 0 for empty store."""
        count = await store.count()

        assert count == 0

    @pytest.mark.asyncio
    async def test_count_returns_correct_total(self, store, sample_documents):
        """Count returns correct total after adding documents."""
        await store.add_documents(sample_documents)

        count = await store.count()

        assert count == 3

    @pytest.mark.asyncio
    async def test_count_after_deletions(self, store, sample_documents):
        """Count returns correct total after deletions."""
        await store.add_documents(sample_documents)
        await store.delete_by_metadata("language", "python")

        count = await store.count()

        assert count == 1

    @pytest.mark.asyncio
    async def test_count_before_initialize(self, tmp_path):
        """Count returns 0 before initialize (no connection)."""
        db_path = tmp_path / "test.db"
        store = SqliteVecStore(db_path=db_path, dimensions=4)

        count = await store.count()

        assert count == 0


class TestSqliteVecStoreClose:
    """Test suite for closing vector store connection."""

    @pytest.mark.asyncio
    async def test_close_cleans_up_connection(self, tmp_path):
        """Close cleans up database connection."""
        db_path = tmp_path / "test.db"
        store = SqliteVecStore(db_path=db_path, dimensions=4)
        await store.initialize()

        await store.close()

        assert store._conn is None

    @pytest.mark.asyncio
    async def test_close_can_be_called_multiple_times(self, tmp_path):
        """Close is idempotent and can be called multiple times."""
        db_path = tmp_path / "test.db"
        store = SqliteVecStore(db_path=db_path, dimensions=4)
        await store.initialize()

        await store.close()
        await store.close()

        assert store._conn is None

    @pytest.mark.asyncio
    async def test_close_without_initialize(self, tmp_path):
        """Close can be called without initialize (no-op)."""
        db_path = tmp_path / "test.db"
        store = SqliteVecStore(db_path=db_path, dimensions=4)

        await store.close()

        assert store._conn is None
