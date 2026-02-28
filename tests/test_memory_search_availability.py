"""Tests for memory search tool availability bugfix.

Covers the fix where memory_search was always loaded (empty prerequisites) but
the vector store only initialized when memory.enabled=True. Agents saw a broken
tool when the vector store was not available.

Changes tested:
- MemoryConfig.enabled defaults to True
- AgentFactory.remove_builtin_tools() filters tools by LangChain name
- AgentFactory.remove_enabled_builtin() removes name from enabled list
- WorkspaceRunner._connect_memory_search_tool() removes broken tool when
  vector store is unavailable and rebuilds the agent
"""

import logging
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from openpaw.core.config.models import MemoryConfig
from openpaw.workspace.agent_factory import AgentFactory
from openpaw.workspace.runner import WorkspaceRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_tool(name: str) -> Mock:
    """Create a mock LangChain tool with a .name attribute."""
    tool = Mock()
    tool.name = name
    return tool


def _make_agent_factory(
    builtin_tools: list[Mock] | None = None,
    enabled_builtin_names: list[str] | None = None,
) -> AgentFactory:
    """Create an AgentFactory with lightweight mocks for unit tests.

    AgentRunner is never instantiated here; we only test factory bookkeeping.
    """
    mock_workspace = MagicMock()
    mock_workspace.path = "/fake/workspace"

    with patch("openpaw.workspace.agent_factory.AgentRunner"):
        factory = AgentFactory(
            workspace=mock_workspace,
            model="anthropic:claude-3-haiku-20240307",
            api_key="fake-key",
            max_turns=10,
            temperature=0.7,
            region=None,
            timeout_seconds=30.0,
            builtin_tools=builtin_tools or [],
            workspace_tools=[],
            enabled_builtin_names=enabled_builtin_names or [],
            extra_model_kwargs={},
            middleware=[],
            logger=logging.getLogger("test"),
        )
    return factory


# ---------------------------------------------------------------------------
# A. MemoryConfig default tests
# ---------------------------------------------------------------------------


class TestMemoryConfigDefaults:
    """MemoryConfig default value tests."""

    def test_enabled_defaults_to_true(self):
        """MemoryConfig with no args should have enabled=True."""
        config = MemoryConfig()
        assert config.enabled is True

    def test_enabled_can_be_set_to_false(self):
        """MemoryConfig(enabled=False) should work."""
        config = MemoryConfig(enabled=False)
        assert config.enabled is False

    def test_enabled_can_be_explicitly_set_to_true(self):
        """MemoryConfig(enabled=True) should work."""
        config = MemoryConfig(enabled=True)
        assert config.enabled is True

    def test_other_fields_have_defaults(self):
        """Default construction should not raise; nested configs are present."""
        config = MemoryConfig()
        assert config.vector_store is not None
        assert config.embedding is not None


# ---------------------------------------------------------------------------
# B. AgentFactory.remove_builtin_tools tests
# ---------------------------------------------------------------------------


class TestRemoveBuiltinTools:
    """Tests for AgentFactory.remove_builtin_tools()."""

    def test_removes_tool_matching_name(self):
        """Tool with matching name is removed from builtin tools."""
        tools = [
            _make_mock_tool("search_conversations"),
            _make_mock_tool("brave_search"),
        ]
        factory = _make_agent_factory(builtin_tools=tools)

        factory.remove_builtin_tools({"search_conversations"})

        remaining_names = [t.name for t in factory._builtin_tools]
        assert "search_conversations" not in remaining_names

    def test_leaves_non_matching_tools_untouched(self):
        """Tools with non-matching names are preserved."""
        tools = [
            _make_mock_tool("search_conversations"),
            _make_mock_tool("brave_search"),
            _make_mock_tool("send_message"),
        ]
        factory = _make_agent_factory(builtin_tools=tools)

        factory.remove_builtin_tools({"search_conversations"})

        remaining_names = [t.name for t in factory._builtin_tools]
        assert "brave_search" in remaining_names
        assert "send_message" in remaining_names

    def test_noop_when_name_not_present(self):
        """No error and no change when tool name is not in list."""
        tools = [_make_mock_tool("brave_search")]
        factory = _make_agent_factory(builtin_tools=tools)

        factory.remove_builtin_tools({"search_conversations"})

        assert len(factory._builtin_tools) == 1
        assert factory._builtin_tools[0].name == "brave_search"

    def test_noop_on_empty_tool_list(self):
        """No error when builtin_tools list is empty."""
        factory = _make_agent_factory(builtin_tools=[])

        factory.remove_builtin_tools({"search_conversations"})

        assert factory._builtin_tools == []

    def test_removes_multiple_tools_at_once(self):
        """Multiple tool names in the set are all removed."""
        tools = [
            _make_mock_tool("tool_a"),
            _make_mock_tool("tool_b"),
            _make_mock_tool("tool_c"),
        ]
        factory = _make_agent_factory(builtin_tools=tools)

        factory.remove_builtin_tools({"tool_a", "tool_b"})

        remaining_names = [t.name for t in factory._builtin_tools]
        assert remaining_names == ["tool_c"]

    def test_logs_removal_when_tools_removed(self):
        """A log message is emitted when tools are actually removed."""
        mock_logger = MagicMock()
        tools = [_make_mock_tool("search_conversations")]
        factory = _make_agent_factory(builtin_tools=tools)
        factory._logger = mock_logger

        factory.remove_builtin_tools({"search_conversations"})

        mock_logger.info.assert_called_once()
        log_message = mock_logger.info.call_args[0][0]
        assert "search_conversations" in log_message

    def test_does_not_log_when_no_tools_removed(self):
        """No log message when no tools matched."""
        mock_logger = MagicMock()
        tools = [_make_mock_tool("brave_search")]
        factory = _make_agent_factory(builtin_tools=tools)
        factory._logger = mock_logger

        factory.remove_builtin_tools({"search_conversations"})

        mock_logger.info.assert_not_called()


# ---------------------------------------------------------------------------
# C. AgentFactory.remove_enabled_builtin tests
# ---------------------------------------------------------------------------


class TestRemoveEnabledBuiltin:
    """Tests for AgentFactory.remove_enabled_builtin()."""

    def test_removes_name_from_enabled_list(self):
        """Name is removed from enabled builtin names."""
        factory = _make_agent_factory(
            enabled_builtin_names=["memory_search", "brave_search"]
        )

        factory.remove_enabled_builtin("memory_search")

        assert "memory_search" not in factory._enabled_builtin_names

    def test_leaves_other_names_untouched(self):
        """Other enabled builtin names are preserved."""
        factory = _make_agent_factory(
            enabled_builtin_names=["memory_search", "brave_search", "send_message"]
        )

        factory.remove_enabled_builtin("memory_search")

        assert "brave_search" in factory._enabled_builtin_names
        assert "send_message" in factory._enabled_builtin_names

    def test_noop_when_name_not_in_list(self):
        """No error and no change when name is absent."""
        factory = _make_agent_factory(
            enabled_builtin_names=["brave_search"]
        )

        factory.remove_enabled_builtin("memory_search")

        assert factory._enabled_builtin_names == ["brave_search"]

    def test_noop_on_empty_enabled_list(self):
        """No error when enabled_builtin_names list is empty."""
        factory = _make_agent_factory(enabled_builtin_names=[])

        factory.remove_enabled_builtin("memory_search")

        assert factory._enabled_builtin_names == []

    def test_removes_only_exact_match(self):
        """Only the exact name is removed, not partial matches."""
        factory = _make_agent_factory(
            enabled_builtin_names=["memory_search", "memory_search_extended"]
        )

        factory.remove_enabled_builtin("memory_search")

        assert "memory_search" not in factory._enabled_builtin_names
        assert "memory_search_extended" in factory._enabled_builtin_names


# ---------------------------------------------------------------------------
# D. WorkspaceRunner._connect_memory_search_tool integration tests
# ---------------------------------------------------------------------------


def _make_mock_runner(
    memory_tool: Mock | None = None,
    vector_store: Mock | None = None,
    embedding_provider: Mock | None = None,
    agent_factory: Mock | None = None,
    agent_runner: Mock | None = None,
    message_processor: Mock | None = None,
) -> MagicMock:
    """Build a minimal mock WorkspaceRunner for _connect_memory_search_tool tests.

    Uses the same pattern as test_lifecycle_notifications.py: construct a
    MagicMock(spec=WorkspaceRunner) and attach the attributes that the real
    method reads.
    """
    runner = MagicMock(spec=WorkspaceRunner)
    runner.workspace_name = "test_workspace"
    runner.logger = MagicMock()

    # Builtin loader returns memory_tool (or None)
    runner._builtin_loader = MagicMock()
    runner._builtin_loader.get_tool_instance.return_value = memory_tool

    runner._vector_store = vector_store
    runner._embedding_provider = embedding_provider

    # Agent factory (real or mock)
    if agent_factory is None:
        runner._agent_factory = MagicMock()
        runner._agent_factory.create_agent.return_value = MagicMock()
    else:
        runner._agent_factory = agent_factory

    # Agent runner
    if agent_runner is None:
        runner._agent_runner = MagicMock()
    else:
        runner._agent_runner = agent_runner

    # Message processor references the agent runner
    if message_processor is None:
        runner._message_processor = MagicMock()
    else:
        runner._message_processor = message_processor

    runner._checkpointer = MagicMock()

    return runner


class TestConnectMemorySearchTool:
    """Integration tests for WorkspaceRunner._connect_memory_search_tool."""

    def test_set_context_called_when_vector_store_available(self):
        """When vector store is available, set_context is called on the memory tool."""
        mock_memory_tool = MagicMock()
        mock_vector_store = MagicMock()
        mock_embedding_provider = MagicMock()

        runner = _make_mock_runner(
            memory_tool=mock_memory_tool,
            vector_store=mock_vector_store,
            embedding_provider=mock_embedding_provider,
        )

        WorkspaceRunner._connect_memory_search_tool(runner)

        mock_memory_tool.set_context.assert_called_once_with(
            mock_vector_store, mock_embedding_provider
        )

    def test_agent_not_rebuilt_when_vector_store_available(self):
        """Agent is not rebuilt when the vector store is present."""
        mock_memory_tool = MagicMock()

        runner = _make_mock_runner(
            memory_tool=mock_memory_tool,
            vector_store=MagicMock(),
            embedding_provider=MagicMock(),
        )

        WorkspaceRunner._connect_memory_search_tool(runner)

        runner._agent_factory.create_agent.assert_not_called()

    def test_tools_removed_when_vector_store_unavailable(self):
        """When vector store is None, broken tool is removed from factory."""
        mock_memory_tool = MagicMock()

        runner = _make_mock_runner(
            memory_tool=mock_memory_tool,
            vector_store=None,
            embedding_provider=None,
        )

        WorkspaceRunner._connect_memory_search_tool(runner)

        runner._agent_factory.remove_builtin_tools.assert_called_once_with(
            {"search_conversations"}
        )

    def test_enabled_builtin_removed_when_vector_store_unavailable(self):
        """When vector store is None, memory_search is removed from enabled list."""
        mock_memory_tool = MagicMock()

        runner = _make_mock_runner(
            memory_tool=mock_memory_tool,
            vector_store=None,
            embedding_provider=None,
        )

        WorkspaceRunner._connect_memory_search_tool(runner)

        runner._agent_factory.remove_enabled_builtin.assert_called_once_with(
            "memory_search"
        )

    def test_agent_rebuilt_when_vector_store_unavailable(self):
        """When vector store is unavailable, a new agent is created via factory."""
        mock_memory_tool = MagicMock()
        new_agent = MagicMock()
        runner = _make_mock_runner(
            memory_tool=mock_memory_tool,
            vector_store=None,
            embedding_provider=None,
        )
        runner._agent_factory.create_agent.return_value = new_agent

        WorkspaceRunner._connect_memory_search_tool(runner)

        runner._agent_factory.create_agent.assert_called_once_with(
            checkpointer=runner._checkpointer
        )
        assert runner._agent_runner is new_agent

    def test_message_processor_agent_runner_updated_on_rebuild(self):
        """After rebuild, message processor receives the new agent runner."""
        mock_memory_tool = MagicMock()
        new_agent = MagicMock()
        runner = _make_mock_runner(
            memory_tool=mock_memory_tool,
            vector_store=None,
            embedding_provider=None,
        )
        runner._agent_factory.create_agent.return_value = new_agent

        WorkspaceRunner._connect_memory_search_tool(runner)

        assert runner._message_processor._agent_runner is new_agent

    def test_set_context_not_called_when_vector_store_unavailable(self):
        """When vector store is None, set_context is never called."""
        mock_memory_tool = MagicMock()

        runner = _make_mock_runner(
            memory_tool=mock_memory_tool,
            vector_store=None,
            embedding_provider=None,
        )

        WorkspaceRunner._connect_memory_search_tool(runner)

        mock_memory_tool.set_context.assert_not_called()

    def test_debug_log_when_tool_not_loaded(self):
        """When memory_search builtin is not loaded at all, a debug log is emitted."""
        runner = _make_mock_runner(memory_tool=None)

        WorkspaceRunner._connect_memory_search_tool(runner)

        runner.logger.debug.assert_called_once()
        debug_message = runner.logger.debug.call_args[0][0]
        assert "MemorySearchTool" in debug_message

    def test_no_factory_calls_when_tool_not_loaded(self):
        """When builtin is not loaded, no factory methods are touched."""
        runner = _make_mock_runner(memory_tool=None)

        WorkspaceRunner._connect_memory_search_tool(runner)

        runner._agent_factory.remove_builtin_tools.assert_not_called()
        runner._agent_factory.remove_enabled_builtin.assert_not_called()
        runner._agent_factory.create_agent.assert_not_called()

    def test_exception_is_caught_and_logged_as_warning(self):
        """If an unexpected exception occurs, it is caught and logged as warning."""
        runner = _make_mock_runner()
        runner._builtin_loader.get_tool_instance.side_effect = RuntimeError("unexpected")

        # Should not propagate
        WorkspaceRunner._connect_memory_search_tool(runner)

        runner.logger.warning.assert_called_once()
        warning_message = runner.logger.warning.call_args[0][0]
        assert "MemorySearchTool" in warning_message

    def test_vector_store_present_but_no_embedding_provider_removes_tool(self):
        """Vector store present but embedding provider absent still removes tool."""
        mock_memory_tool = MagicMock()

        runner = _make_mock_runner(
            memory_tool=mock_memory_tool,
            vector_store=MagicMock(),
            embedding_provider=None,  # no embedding provider
        )

        WorkspaceRunner._connect_memory_search_tool(runner)

        # Condition requires BOTH vector_store AND embedding_provider
        runner._agent_factory.remove_builtin_tools.assert_called_once_with(
            {"search_conversations"}
        )

    def test_embedding_provider_present_but_no_vector_store_removes_tool(self):
        """Embedding provider present but vector store absent still removes tool."""
        mock_memory_tool = MagicMock()

        runner = _make_mock_runner(
            memory_tool=mock_memory_tool,
            vector_store=None,
            embedding_provider=MagicMock(),  # has embedding provider
        )

        WorkspaceRunner._connect_memory_search_tool(runner)

        runner._agent_factory.remove_builtin_tools.assert_called_once_with(
            {"search_conversations"}
        )
