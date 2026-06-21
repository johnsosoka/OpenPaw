"""Tests for conversation indexer."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from openpaw.stores.vector.indexer import ConversationIndexer


@pytest.fixture
def mock_vector_store():
    """Create a mock vector store."""
    store = AsyncMock()
    store.add_documents = AsyncMock(return_value=5)
    store.delete_by_metadata = AsyncMock(return_value=3)
    return store


@pytest.fixture
def mock_embedding_provider():
    """Create a mock embedding provider."""
    provider = AsyncMock()
    provider.embed_texts = AsyncMock(return_value=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
    return provider


@pytest.fixture
def indexer(mock_vector_store, mock_embedding_provider):
    """Create a conversation indexer."""
    return ConversationIndexer(mock_vector_store, mock_embedding_provider)


class TestExtractTurns:
    """Tests for _extract_turns method."""

    def test_valid_human_ai_pairs(self, indexer):
        """Test extracting valid human+ai pairs."""
        messages = [
            {"role": "human", "content": "Hello"},
            {"role": "ai", "content": "Hi there"},
            {"role": "human", "content": "How are you?"},
            {"role": "ai", "content": "I'm good"},
        ]
        turns = indexer._extract_turns(messages)
        assert len(turns) == 2
        assert turns[0][0]["content"] == "Hello"
        assert turns[0][1]["content"] == "Hi there"
        assert turns[1][0]["content"] == "How are you?"
        assert turns[1][1]["content"] == "I'm good"

    def test_only_human_messages(self, indexer):
        """Test with only human messages (no turns)."""
        messages = [
            {"role": "human", "content": "Hello"},
            {"role": "human", "content": "Anyone there?"},
        ]
        turns = indexer._extract_turns(messages)
        assert len(turns) == 0

    def test_orphaned_ai_message(self, indexer):
        """Test with orphaned AI message (no preceding human)."""
        messages = [
            {"role": "ai", "content": "Random AI response"},
            {"role": "human", "content": "Hello"},
            {"role": "ai", "content": "Hi there"},
        ]
        turns = indexer._extract_turns(messages)
        assert len(turns) == 1
        assert turns[0][0]["content"] == "Hello"
        assert turns[0][1]["content"] == "Hi there"

    def test_consecutive_human_messages(self, indexer):
        """Test with consecutive human messages (only last one before AI counts)."""
        messages = [
            {"role": "human", "content": "First message"},
            {"role": "human", "content": "Second message"},
            {"role": "human", "content": "Third message"},
            {"role": "ai", "content": "Response"},
        ]
        turns = indexer._extract_turns(messages)
        assert len(turns) == 1
        assert turns[0][0]["content"] == "Third message"
        assert turns[0][1]["content"] == "Response"

    def test_empty_messages(self, indexer):
        """Test with empty messages list."""
        turns = indexer._extract_turns([])
        assert len(turns) == 0


class TestCreateChunks:
    """Tests for _create_chunks method."""

    def test_single_turn_produces_one_chunk(self, indexer):
        """Test that a single turn produces one chunk."""
        turns = [
            (
                {"content": "Hello", "timestamp": "2024-01-01T10:00:00"},
                {"content": "Hi there", "timestamp": "2024-01-01T10:00:01"},
            )
        ]
        chunks = indexer._create_chunks(turns, "conv_1", "telegram:123")
        assert len(chunks) == 1
        assert "User: Hello" in chunks[0].content
        assert "Agent: Hi there" in chunks[0].content
        assert chunks[0].metadata["conversation_id"] == "conv_1"
        assert chunks[0].metadata["session_key"] == "telegram:123"
        assert chunks[0].metadata["chunk_index"] == 0

    def test_three_turns_produces_two_chunks(self, indexer):
        """Test that 3 turns produces 2 chunks with step size of 2."""
        turns = [
            ({"content": "Q1"}, {"content": "A1"}),
            ({"content": "Q2"}, {"content": "A2"}),
            ({"content": "Q3"}, {"content": "A3"}),
        ]
        chunks = indexer._create_chunks(turns, "conv_1", "telegram:123")
        # With window_size=3 and overlap=1, step size = 2
        # Chunk 0: turns 0-2 (all 3)
        # Chunk 2: turn 2 only (remainder)
        assert len(chunks) == 2
        assert "User: Q1" in chunks[0].content
        assert "Agent: A1" in chunks[0].content
        assert "User: Q2" in chunks[0].content
        assert "Agent: A2" in chunks[0].content
        assert "User: Q3" in chunks[0].content
        assert "Agent: A3" in chunks[0].content

    def test_five_turns_produces_chunks_with_overlap(self, indexer):
        """Test that 5 turns produces 3 chunks with overlap."""
        turns = [
            ({"content": "Q1"}, {"content": "A1"}),
            ({"content": "Q2"}, {"content": "A2"}),
            ({"content": "Q3"}, {"content": "A3"}),
            ({"content": "Q4"}, {"content": "A4"}),
            ({"content": "Q5"}, {"content": "A5"}),
        ]
        chunks = indexer._create_chunks(turns, "conv_1", "telegram:123")
        # With window_size=3 and overlap=1, step size = 2
        # Chunk 0: turns 0-2
        # Chunk 2: turns 2-4 (step size = window_size - overlap = 2)
        # Chunk 4: turn 4 only (remainder)
        assert len(chunks) == 3
        assert chunks[0].metadata["chunk_index"] == 0
        assert chunks[1].metadata["chunk_index"] == 2
        assert chunks[2].metadata["chunk_index"] == 4

    def test_chunk_content_formatting(self, indexer):
        """Test chunk content has User: / Agent: prefix."""
        turns = [
            ({"content": "Hello world"}, {"content": "Greetings"}),
        ]
        chunks = indexer._create_chunks(turns, "conv_1", "telegram:123")
        content = chunks[0].content
        assert "User: Hello world" in content
        assert "Agent: Greetings" in content

    def test_chunk_metadata_includes_required_fields(self, indexer):
        """Test chunk metadata includes conversation_id, session_key, chunk_index."""
        turns = [
            ({"content": "Q1"}, {"content": "A1"}),
        ]
        chunks = indexer._create_chunks(turns, "conv_123", "telegram:456")
        metadata = chunks[0].metadata
        assert metadata["conversation_id"] == "conv_123"
        assert metadata["session_key"] == "telegram:456"
        assert metadata["chunk_index"] == 0

    def test_chunk_metadata_includes_timestamps_when_present(self, indexer):
        """Test chunk metadata includes timestamps when present."""
        turns = [
            (
                {"content": "Q1", "timestamp": "2024-01-01T10:00:00"},
                {"content": "A1", "timestamp": "2024-01-01T10:00:01"},
            ),
            (
                {"content": "Q2", "timestamp": "2024-01-01T10:00:10"},
                {"content": "A2", "timestamp": "2024-01-01T10:00:11"},
            ),
        ]
        chunks = indexer._create_chunks(turns, "conv_1", "telegram:123")
        metadata = chunks[0].metadata
        assert "timestamp_start" in metadata
        assert "timestamp_end" in metadata
        assert metadata["timestamp_start"] == "2024-01-01T10:00:00"
        assert metadata["timestamp_end"] == "2024-01-01T10:00:10"

    def test_chunk_id_format(self, indexer):
        """Test chunk ID format is conversation_id:chunk:index."""
        turns = [
            ({"content": "Q1"}, {"content": "A1"}),
        ]
        chunks = indexer._create_chunks(turns, "conv_abc", "telegram:123")
        assert chunks[0].id == "conv_abc:chunk:0"


class TestIndexArchive:
    """Tests for index_archive method."""

    @pytest.mark.asyncio
    async def test_index_archive_end_to_end(self, indexer, mock_vector_store, mock_embedding_provider, tmp_path):
        """Test index_archive end-to-end with mocked dependencies."""
        # Create test archive JSON
        archive_data = {
            "conversation_id": "conv_123",
            "session_key": "telegram:456",
            "messages": [
                {"role": "human", "content": "Hello", "timestamp": "2024-01-01T10:00:00"},
                {"role": "ai", "content": "Hi there", "timestamp": "2024-01-01T10:00:01"},
            ],
        }
        archive_path = tmp_path / "archive.json"
        archive_path.write_text(json.dumps(archive_data), encoding="utf-8")

        # Mock embedding provider to return embeddings
        mock_embedding_provider.embed_texts.return_value = [[0.1, 0.2, 0.3]]

        # Mock vector store to return count
        mock_vector_store.add_documents.return_value = 1

        count = await indexer.index_archive(archive_path)

        # Verify embedding provider was called
        mock_embedding_provider.embed_texts.assert_called_once()
        call_args = mock_embedding_provider.embed_texts.call_args[0][0]
        assert len(call_args) == 1
        assert "User: Hello" in call_args[0]
        assert "Agent: Hi there" in call_args[0]

        # Verify vector store was called
        mock_vector_store.add_documents.assert_called_once()
        docs = mock_vector_store.add_documents.call_args[0][0]
        assert len(docs) == 1
        assert docs[0].embedding == [0.1, 0.2, 0.3]

        assert count == 1

    @pytest.mark.asyncio
    async def test_index_archive_empty_messages(self, indexer, tmp_path):
        """Test index_archive with empty messages returns 0."""
        archive_data = {
            "conversation_id": "conv_123",
            "session_key": "telegram:456",
            "messages": [],
        }
        archive_path = tmp_path / "archive.json"
        archive_path.write_text(json.dumps(archive_data), encoding="utf-8")

        count = await indexer.index_archive(archive_path)
        assert count == 0

    @pytest.mark.asyncio
    async def test_index_archive_invalid_json_path(self, indexer):
        """Test index_archive with invalid JSON path returns 0."""
        invalid_path = Path("/nonexistent/path/archive.json")
        count = await indexer.index_archive(invalid_path)
        assert count == 0

    @pytest.mark.asyncio
    async def test_index_archive_embedding_failure(self, indexer, mock_embedding_provider, tmp_path):
        """Test index_archive when embedding generation fails returns 0."""
        archive_data = {
            "conversation_id": "conv_123",
            "session_key": "telegram:456",
            "messages": [
                {"role": "human", "content": "Hello"},
                {"role": "ai", "content": "Hi"},
            ],
        }
        archive_path = tmp_path / "archive.json"
        archive_path.write_text(json.dumps(archive_data), encoding="utf-8")

        # Mock embedding provider to raise exception
        mock_embedding_provider.embed_texts.side_effect = Exception("API error")

        count = await indexer.index_archive(archive_path)
        assert count == 0


class TestRemoveConversation:
    """Tests for remove_conversation method."""

    @pytest.mark.asyncio
    async def test_remove_conversation_delegates_to_store(self, indexer, mock_vector_store):
        """Test remove_conversation delegates to store.delete_by_metadata."""
        mock_vector_store.delete_by_metadata.return_value = 5

        count = await indexer.remove_conversation("conv_123")

        mock_vector_store.delete_by_metadata.assert_called_once_with("conversation_id", "conv_123")
        assert count == 5
