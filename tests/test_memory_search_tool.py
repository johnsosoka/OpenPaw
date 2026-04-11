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

    def test_set_context_defaults_conversations_enabled_true(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test set_context defaults conversations_enabled to True."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        assert memory_search_tool._conversations_enabled is True

    def test_set_context_defaults_files_enabled_false(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test set_context defaults files_enabled to False."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        assert memory_search_tool._files_enabled is False

    def test_set_context_accepts_conversations_enabled_kwarg(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test set_context accepts and stores conversations_enabled kwarg."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider, conversations_enabled=False)
        assert memory_search_tool._conversations_enabled is False

    def test_set_context_accepts_files_enabled_kwarg(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test set_context accepts and stores files_enabled kwarg."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider, files_enabled=True)
        assert memory_search_tool._files_enabled is True


class TestGetLangChainTool:
    """Tests for get_langchain_tool method."""

    def test_returns_list(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test get_langchain_tool returns a list."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        tools = memory_search_tool.get_langchain_tool()
        assert isinstance(tools, list)

    def test_returns_search_conversations_when_conversations_enabled(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test get_langchain_tool returns search_conversations when conversations enabled."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider, conversations_enabled=True)
        tools = memory_search_tool.get_langchain_tool()
        tool_names = [t.name for t in tools]
        assert "search_conversations" in tool_names

    def test_excludes_search_conversations_when_conversations_disabled(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test get_langchain_tool omits search_conversations when conversations disabled."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider, conversations_enabled=False, files_enabled=False)
        tools = memory_search_tool.get_langchain_tool()
        tool_names = [t.name for t in tools]
        assert "search_conversations" not in tool_names

    def test_returns_search_workspace_when_files_enabled(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test get_langchain_tool returns search_workspace when files enabled."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider, files_enabled=True)
        tools = memory_search_tool.get_langchain_tool()
        tool_names = [t.name for t in tools]
        assert "search_workspace" in tool_names

    def test_excludes_search_workspace_when_files_disabled(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test get_langchain_tool omits search_workspace when files disabled."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider, files_enabled=False)
        tools = memory_search_tool.get_langchain_tool()
        tool_names = [t.name for t in tools]
        assert "search_workspace" not in tool_names

    def test_returns_both_tools_when_both_enabled(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test get_langchain_tool returns both tools when both sources are enabled."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider, conversations_enabled=True, files_enabled=True)
        tools = memory_search_tool.get_langchain_tool()
        tool_names = [t.name for t in tools]
        assert "search_conversations" in tool_names
        assert "search_workspace" in tool_names
        assert len(tools) == 2

    def test_returns_empty_list_when_both_disabled(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test get_langchain_tool returns empty list when both sources are disabled."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider, conversations_enabled=False, files_enabled=False)
        tools = memory_search_tool.get_langchain_tool()
        assert tools == []


class TestAsyncSearchConversations:
    """Tests for _search_conversations_async."""

    @pytest.mark.asyncio
    async def test_search_when_context_not_set_returns_no_results(self, memory_search_tool):
        """Test async conversation search when context not set returns no-results message.

        _query() returns [] early when the vector store is unset; the outer sync
        wrapper is responsible for the "[Error: Memory search not available]" guard.
        """
        result = await memory_search_tool._search_conversations_async("test query", 5)
        assert "No relevant conversations found" in result

    @pytest.mark.asyncio
    async def test_search_with_mock_dependencies(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test async conversation search with mock vector store and embedding provider."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        mock_embedding_provider.embed_query.return_value = [0.1, 0.2, 0.3]

        doc = VectorDocument(
            id="conv_123:chunk:0",
            content="User: Hello\nAgent: Hi there",
            metadata={
                "conversation_id": "conv_123",
                "session_key": "telegram:456",
                "chunk_index": 0,
                "source_type": "conversation",
                "timestamp_start": "2024-01-01T10:00:00",
            },
            embedding=[0.1, 0.2, 0.3],
        )
        result = VectorSearchResult(document=doc, score=0.95)
        mock_vector_store.search.return_value = [result]

        output = await memory_search_tool._search_conversations_async("test query", 5)

        mock_embedding_provider.embed_query.assert_called_once_with("test query")
        mock_vector_store.search.assert_called_once()
        call_kwargs = mock_vector_store.search.call_args[1]
        assert call_kwargs["query_embedding"] == [0.1, 0.2, 0.3]

        assert "Found 1 relevant conversation" in output

    @pytest.mark.asyncio
    async def test_search_passes_conversation_source_type(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test conversation search passes source_type='conversation' to the store."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        mock_vector_store.search.return_value = []

        await memory_search_tool._search_conversations_async("test query", 5)

        call_kwargs = mock_vector_store.search.call_args[1]
        assert call_kwargs.get("source_type") == "conversation"

    @pytest.mark.asyncio
    async def test_search_with_no_results(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test conversation search with no results returns appropriate message."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        mock_vector_store.search.return_value = []

        output = await memory_search_tool._search_conversations_async("test query", 5)
        assert "No relevant conversations found" in output

    @pytest.mark.asyncio
    async def test_search_formats_results_correctly(
        self, memory_search_tool, mock_vector_store, mock_embedding_provider
    ):
        """Test conversation search formats results with score, conversation ID, and content."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)

        doc1 = VectorDocument(
            id="conv_abc:chunk:0",
            content="User: Question 1\nAgent: Answer 1",
            metadata={
                "conversation_id": "conv_abc",
                "session_key": "telegram:123",
                "chunk_index": 0,
                "source_type": "conversation",
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
                "source_type": "conversation",
            },
        )
        results = [
            VectorSearchResult(document=doc1, score=0.95),
            VectorSearchResult(document=doc2, score=0.85),
        ]
        mock_vector_store.search.return_value = results

        output = await memory_search_tool._search_conversations_async("test query", 5)

        assert "Found 2 relevant conversation(s)" in output
        assert "Result 1 (score: 0.95)" in output
        assert "Conversation: conv_abc" in output
        assert "Time: 2024-01-01T10:00:00" in output
        assert "User: Question 1" in output
        assert "Agent: Answer 1" in output
        assert "Result 2 (score: 0.85)" in output
        assert "Conversation: conv_xyz" in output
        assert "User: Question 2" in output
        assert "Agent: Answer 2" in output

    @pytest.mark.asyncio
    async def test_search_handles_exceptions_gracefully(
        self, memory_search_tool, mock_vector_store, mock_embedding_provider
    ):
        """Test conversation search handles exceptions and returns error message."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        mock_vector_store.search.side_effect = Exception("Database connection failed")

        output = await memory_search_tool._search_conversations_async("test query", 5)
        assert "[Error: Memory search failed:" in output
        assert "Database connection failed" in output


class TestAsyncSearchWorkspace:
    """Tests for _search_workspace_async."""

    @pytest.mark.asyncio
    async def test_search_workspace_when_context_not_set_returns_no_results(self, memory_search_tool):
        """Test workspace search when context not set returns no-results message.

        _query() returns [] early when the vector store is unset; the outer sync
        wrapper is responsible for the "[Error: Memory search not available]" guard.
        """
        result = await memory_search_tool._search_workspace_async("test query", 5)
        assert "No relevant workspace files found" in result

    @pytest.mark.asyncio
    async def test_search_workspace_passes_file_source_type(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test workspace search passes source_type='file' to the store."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        mock_vector_store.search.return_value = []

        await memory_search_tool._search_workspace_async("test query", 5)

        call_kwargs = mock_vector_store.search.call_args[1]
        assert call_kwargs.get("source_type") == "file"

    @pytest.mark.asyncio
    async def test_search_workspace_with_no_results(self, memory_search_tool, mock_vector_store, mock_embedding_provider):
        """Test workspace search with no results returns appropriate message."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        mock_vector_store.search.return_value = []

        output = await memory_search_tool._search_workspace_async("test query", 5)
        assert "No relevant workspace files found" in output

    @pytest.mark.asyncio
    async def test_search_workspace_formats_results_correctly(
        self, memory_search_tool, mock_vector_store, mock_embedding_provider
    ):
        """Test workspace search formats results with file path and chunk info."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)

        doc = VectorDocument(
            id="agent/notes.md:chunk:0",
            content="# Project notes\nThis is a note about the project.",
            metadata={
                "file_path": "agent/notes.md",
                "chunk_index": 0,
                "source_type": "file",
                "indexed_at": "2024-01-01T10:00:00",
            },
        )
        results = [VectorSearchResult(document=doc, score=0.88)]
        mock_vector_store.search.return_value = results

        output = await memory_search_tool._search_workspace_async("test query", 5)

        assert "Found 1 relevant file section(s)" in output
        assert "Result 1 (score: 0.88)" in output
        assert "File: agent/notes.md" in output
        assert "Indexed: 2024-01-01T10:00:00" in output
        assert "Project notes" in output

    @pytest.mark.asyncio
    async def test_search_workspace_handles_exceptions_gracefully(
        self, memory_search_tool, mock_vector_store, mock_embedding_provider
    ):
        """Test workspace search handles exceptions and returns error message."""
        memory_search_tool.set_context(mock_vector_store, mock_embedding_provider)
        mock_vector_store.search.side_effect = Exception("Storage failure")

        output = await memory_search_tool._search_workspace_async("test query", 5)
        assert "[Error: Workspace search failed:" in output
        assert "Storage failure" in output
