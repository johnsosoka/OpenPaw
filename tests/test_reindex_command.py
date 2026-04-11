"""Tests for the /reindex command handler."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.commands.handlers.reindex import ReindexCommand
from openpaw.stores.vector.file_indexer import IndexingResult


@pytest.fixture
def command():
    """A ReindexCommand instance."""
    return ReindexCommand()


@pytest.fixture
def mock_message():
    """A minimal mock Message."""
    return MagicMock()


@pytest.fixture
def mock_context_with_indexer():
    """A CommandContext mock that has a file_indexer attached."""
    context = MagicMock()
    indexer = AsyncMock()
    indexer.index_workspace = AsyncMock(
        return_value=IndexingResult(
            files_indexed=4,
            files_skipped=1,
            files_errored=0,
            chunks_created=12,
            duration_ms=42.0,
        )
    )
    context.file_indexer = indexer
    return context


@pytest.fixture
def mock_context_without_indexer():
    """A CommandContext mock where file_indexer is not set (None via getattr)."""
    context = MagicMock(spec=[])  # spec=[] means getattr returns AttributeError
    return context


class TestReindexCommand:
    """Tests for ReindexCommand."""

    def test_definition_returns_correct_name(self, command):
        """The command name must be 'reindex'."""
        assert command.definition.name == "reindex"

    def test_definition_returns_description(self, command):
        """The command must include a non-empty description."""
        assert command.definition.description

    @pytest.mark.asyncio
    async def test_handle_returns_not_enabled_when_file_indexer_is_none(
        self, command, mock_message
    ):
        """When no file_indexer is on the context, the response should say not enabled."""
        context = MagicMock()
        context.file_indexer = None

        result = await command.handle(mock_message, "", context)

        assert "not enabled" in result.response.lower()

    @pytest.mark.asyncio
    async def test_handle_returns_not_enabled_when_attribute_missing(
        self, command, mock_message, mock_context_without_indexer
    ):
        """getattr safety: missing file_indexer attribute should return not-enabled."""
        result = await command.handle(mock_message, "", mock_context_without_indexer)

        assert "not enabled" in result.response.lower()

    @pytest.mark.asyncio
    async def test_handle_calls_index_workspace_with_force_true(
        self, command, mock_message, mock_context_with_indexer
    ):
        """handle must call index_workspace(force=True) to bypass hash caching."""
        await command.handle(mock_message, "", mock_context_with_indexer)

        mock_context_with_indexer.file_indexer.index_workspace.assert_called_once_with(
            force=True
        )

    @pytest.mark.asyncio
    async def test_handle_returns_formatted_result_string(
        self, command, mock_message, mock_context_with_indexer
    ):
        """The success response should include file count, chunk count, and duration."""
        result = await command.handle(mock_message, "", mock_context_with_indexer)

        assert "4" in result.response   # files_indexed
        assert "12" in result.response  # chunks_created
        assert "42" in result.response  # duration_ms (rounded)

    @pytest.mark.asyncio
    async def test_handle_response_mentions_files_and_chunks(
        self, command, mock_message, mock_context_with_indexer
    ):
        """The formatted response must mention both 'files' and 'chunks'."""
        result = await command.handle(mock_message, "", mock_context_with_indexer)

        assert "files" in result.response.lower()
        assert "chunks" in result.response.lower()
