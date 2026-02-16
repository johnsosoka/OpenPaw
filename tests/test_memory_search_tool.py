"""Tests for memory search tool builtin."""

from unittest.mock import AsyncMock

import pytest

from openpaw.builtins.tools.memory_search import MemorySearchToolBuiltin
from openpaw.stores.vector.base import VectorDocument, VectorSearchResult


@pytest.fixture
def mock_vector_store():
    """Create a mock vector store."""
    store = AsyncMock()
    store.search = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_embedding_provider():
    """Create a mock embedding provider."""
    provider = AsyncMock()
    provider.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
    return provider


@pytest.fixture
def memory_search_tool():
    """Create a memory search tool builtin."""
    return MemorySearchToolBuiltin()


class TestMemorySearchToolMetadata:
    """Tests for MemorySearchToolBuiltin metadata."""

    def test_metadata_name(self, memory_search_tool):
        """Test builtin name is 'memory_search'."""
        assert memory_search_tool.metadata.name == "memory_search"

    def test_metadata_group(self, memory_search_tool):
        """Test builtin group is 'memory'."""
        assert memory_search_tool.metadata.group == "memory"

    def test_metadata_display_name(self, memory_search_tool):
        """Test builtin has display name."""
        assert memory_search_tool.metadata.display_name == "Memory Search"

    def test_metadata_description(self, memory_search_tool):
        """Test builtin has description."""
        assert "semantic search" in memory_search_tool.metadata.description.lower()


class TestSetContext:
    """Tests for set_context method."""

    def test_set_context_stores_references(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test set_context stores vector store and embedding provider references."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        assert memory_search_tool._vector_store is mock_vector_store
        assert memory_search_tool._embedding_provider is mock_embedding_provider


class TestGetLangChainTool:
    """Tests for get_langchain_tool method."""

    def test_returns_structured_tool(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test get_langchain_tool returns StructuredTool."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        tool = memory_search_tool.get_langchain_tool()
        assert tool is not None
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")

    def test_tool_name_is_search_conversations(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test tool name is 'search_conversations'."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        tool = memory_search_tool.get_langchain_tool()
        assert tool.name == "search_conversations"


class TestAsyncSearch:
    """Tests for async search functionality."""

    @pytest.mark.asyncio
    async def test_search_when_context_not_set_returns_error(self, memory_search_tool):
        """Test async search when context not set returns error message."""
        result = await memory_search_tool._search_async("test query", 5)
        assert "[Error: Memory search not available" in result

    @pytest.mark.asyncio
    async def test_search_with_mock_dependencies(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test async search with mock vector store and embedding provider."""
        # Set up context
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)

        # Mock embedding generation
        mock_embedding_provider.embed_query.return_value = [0.1, 0.2, 0.3]

        # Mock search results
        doc = VectorDocument(
            id="conv_123:chunk:0",
            content="User: Hello\nAgent: Hi there",
            metadata={
                "conversation_id": "conv_123",
                "session_key": "telegram:456",
                "chunk_index": 0,
                "timestamp_start": "2024-01-01T10:00:00",
            },
            embedding=[0.1, 0.2, 0.3],
        )
        result = VectorSearchResult(document=doc, score=0.95)
        mock_vector_store.search.return_value = [result]

        # Execute search
        output = await memory_search_tool._search_async("test query", 5)

        # Verify embedding provider was called
        mock_embedding_provider.embed_query.assert_called_once_with("test query")

        # Verify vector store was called
        mock_vector_store.search.assert_called_once()
        call_kwargs = mock_vector_store.search.call_args[1]
        assert call_kwargs["query_embedding"] == [0.1, 0.2, 0.3]
        assert call_kwargs["limit"] == 5

        # Verify output format
        assert "Found 1 relevant conversation" in output

    @pytest.mark.asyncio
    async def test_search_with_no_results(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test search with no results returns appropriate message."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        mock_vector_store.search.return_value = []

        output = await memory_search_tool._search_async("test query", 5)
        assert "No relevant conversations found" in output

    @pytest.mark.asyncio
    async def test_search_formats_results_correctly(
        self, memory_search_tool, mock_vector_store, mock_embedding_provider
    ):
        """Test search formats results with score, conversation ID, and content."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)

        # Create mock results
        doc1 = VectorDocument(
            id="conv_abc:chunk:0",
            content="User: Question 1\nAgent: Answer 1",
            metadata={
                "conversation_id": "conv_abc",
                "session_key": "telegram:123",
                "chunk_index": 0,
                "timestamp_start": "2024-01-01T10:00:00",
            },
        )
        doc2 = VectorDocument(
            id="conv_xyz:chunk:2",
            content="User: Question 2\nAgent: Answer 2",
            metadata={
                "conversation_id": "conv_xyz",
                "session_key": "telegram:456",
                "chunk_index": 2,
            },
        )
        results = [
            VectorSearchResult(document=doc1, score=0.95),
            VectorSearchResult(document=doc2, score=0.85),
        ]
        mock_vector_store.search.return_value = results

        output = await memory_search_tool._search_async("test query", 5)

        # Check header
        assert "Found 2 relevant conversation(s)" in output

        # Check result 1
        assert "Result 1 (score: 0.95)" in output
        assert "Conversation: conv_abc" in output
        assert "Chunk: 0" in output
        assert "Time: 2024-01-01T10:00:00" in output
        assert "User: Question 1" in output
        assert "Agent: Answer 1" in output

        # Check result 2
        assert "Result 2 (score: 0.85)" in output
        assert "Conversation: conv_xyz" in output
        assert "Chunk: 2" in output
        assert "User: Question 2" in output
        assert "Agent: Answer 2" in output

    @pytest.mark.asyncio
    async def test_search_handles_exceptions_gracefully(
        self, memory_search_tool, mock_vector_store, mock_embedding_provider
    ):
        """Test search handles exceptions and returns error message."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        mock_vector_store.search.side_effect = Exception("Database connection failed")

        output = await memory_search_tool._search_async("test query", 5)
        assert "[Error: Memory search failed:" in output
        assert "Database connection failed" in output
