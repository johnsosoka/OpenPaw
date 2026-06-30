"""Regression tests for AgentFactory MCP tool inclusion.

Bug: create_agent() built `all_tools = builtin_tools + workspace_tools`, silently
dropping MCP tools.  Connectors that rebuild the agent after startup (e.g.
connect_memory_search_tool removing search_conversations when the vector store
isn't ready) called create_agent() and lost every MCP tool that had been injected
via update_tools() during start().

Fix: AgentFactory stores MCP tools via set_mcp_tools() and includes them in every
subsequent create_agent() call.  create_stateless_agent() and create_profiled_agent()
also include MCP tools so that cron/heartbeat/profiled-spawn agents can use them.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from openpaw.workspace.agent_factory import AgentFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_tool(name: str) -> Mock:
    """Lightweight stand-in for a LangChain tool."""
    tool = Mock()
    tool.name = name
    return tool


def _make_factory(
    builtin_tools: list[Any] | None = None,
    workspace_tools: list[Any] | None = None,
) -> AgentFactory:
    """Build an AgentFactory with every heavy dependency mocked out.

    AgentRunner is patched at the module level so no LangChain model
    initialisation occurs — we only test factory bookkeeping.
    """
    with patch("openpaw.workspace.agent_factory.AgentRunner"):
        return AgentFactory(
            workspace=MagicMock(),
            model="anthropic:claude-test",
            api_key="fake-key",
            max_turns=10,
            temperature=0.7,
            region=None,
            timeout_seconds=30.0,
            builtin_tools=builtin_tools or [],
            workspace_tools=workspace_tools or [],
            enabled_builtin_names=[],
            extra_model_kwargs={},
            middleware=[],
            logger=logging.getLogger("test"),
        )


def _tools_from_call(mock_agent_runner_cls: Any) -> list[Any]:
    """Extract the `tools` kwarg from the most recent AgentRunner() call.

    AgentFactory passes ``tools=None`` when the combined list is empty, so
    normalise that to an empty list for simpler assertion code.
    """
    return mock_agent_runner_cls.call_args.kwargs["tools"] or []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentFactoryMcpTools:
    """Contract tests for set_mcp_tools() / create_agent() interaction."""

    def test_baseline_no_mcp_tools(self) -> None:
        """create_agent without set_mcp_tools produces builtin + workspace only."""
        builtin = _mock_tool("send_message")
        workspace = _mock_tool("my_custom_tool")
        factory = _make_factory(builtin_tools=[builtin], workspace_tools=[workspace])

        with patch("openpaw.workspace.agent_factory.AgentRunner") as MockRunner:
            factory.create_agent()
            tools = _tools_from_call(MockRunner)

        assert builtin in tools
        assert workspace in tools
        # No extra tools should appear.
        assert len(tools) == 2

    def test_create_agent_includes_mcp_tools_after_set(self) -> None:
        """After set_mcp_tools, create_agent includes the MCP tools."""
        builtin = _mock_tool("send_message")
        workspace = _mock_tool("my_custom_tool")
        mcp_1 = _mock_tool("weather_get_forecast")
        mcp_2 = _mock_tool("weather_get_alerts")

        factory = _make_factory(builtin_tools=[builtin], workspace_tools=[workspace])
        factory.set_mcp_tools([mcp_1, mcp_2])

        with patch("openpaw.workspace.agent_factory.AgentRunner") as MockRunner:
            factory.create_agent()
            tools = _tools_from_call(MockRunner)

        assert builtin in tools
        assert workspace in tools
        assert mcp_1 in tools
        assert mcp_2 in tools
        assert len(tools) == 4

    def test_set_mcp_tools_replaces_not_appends(self) -> None:
        """Calling set_mcp_tools twice uses only the second list."""
        factory = _make_factory()
        first_mcp = _mock_tool("first_tool")
        second_mcp = _mock_tool("second_tool")

        factory.set_mcp_tools([first_mcp])
        factory.set_mcp_tools([second_mcp])

        with patch("openpaw.workspace.agent_factory.AgentRunner") as MockRunner:
            factory.create_agent()
            tools = _tools_from_call(MockRunner)

        assert second_mcp in tools
        assert first_mcp not in tools

    def test_connector_rebuild_pattern_retains_mcp_tools(self) -> None:
        """Calling create_agent() twice (connector rebuild) both times includes MCP tools.

        This is the direct regression test for the original bug: a connector that
        removes a broken builtin tool and calls create_agent() again must not lose
        the MCP tools that were registered via set_mcp_tools().
        """
        builtin = _mock_tool("search_conversations")
        mcp = _mock_tool("weather_get_forecast")

        factory = _make_factory(builtin_tools=[builtin])
        factory.set_mcp_tools([mcp])

        with patch("openpaw.workspace.agent_factory.AgentRunner") as MockRunner:
            # First call — agent created normally during start()
            factory.create_agent()
            first_tools = list(_tools_from_call(MockRunner))

            # Simulate connector removing a broken builtin, then rebuilding agent
            factory.remove_builtin_tools({"search_conversations"})
            factory.create_agent()
            second_tools = list(_tools_from_call(MockRunner))

        # Both agents must include the MCP tool.
        assert mcp in first_tools, "MCP tool missing from first agent build"
        assert mcp in second_tools, "MCP tool missing from post-connector-rebuild agent"

        # The broken builtin was removed — the second agent must not contain it.
        assert builtin not in second_tools

    def test_set_mcp_tools_empty_clears_previous(self) -> None:
        """set_mcp_tools([]) removes all previously stored MCP tools."""
        mcp = _mock_tool("weather_get_forecast")
        factory = _make_factory()
        factory.set_mcp_tools([mcp])

        factory.set_mcp_tools([])

        with patch("openpaw.workspace.agent_factory.AgentRunner") as MockRunner:
            factory.create_agent()
            tools = _tools_from_call(MockRunner)

        assert mcp not in tools

    def test_create_stateless_agent_includes_mcp_tools(self) -> None:
        """create_stateless_agent includes MCP tools alongside builtin and workspace tools.

        Cron and heartbeat agents now receive the full tool set so that scheduled
        work can use the same MCP-provided capabilities as the main channel agent.
        MCP tools are fully loaded at startup before any scheduler fires, so there
        is no ordering hazard.
        """
        builtin = _mock_tool("send_message")
        mcp = _mock_tool("weather_get_forecast")

        factory = _make_factory(builtin_tools=[builtin])
        factory.set_mcp_tools([mcp])

        with patch("openpaw.workspace.agent_factory.AgentRunner") as MockRunner:
            factory.create_stateless_agent()
            tools = _tools_from_call(MockRunner)

        assert builtin in tools
        assert mcp in tools

    def test_create_profiled_agent_includes_mcp_tools(self) -> None:
        """create_profiled_agent includes MCP tools alongside builtin and workspace tools.

        Profiled spawns are the same class of background/scheduled work as stateless
        agents.  They should have access to MCP tools for the same reason.
        """
        from openpaw.model.spawn_profile import SpawnProfile

        builtin = _mock_tool("send_message")
        workspace = _mock_tool("my_custom_tool")
        mcp = _mock_tool("weather_get_forecast")

        factory = _make_factory(builtin_tools=[builtin], workspace_tools=[workspace])
        factory.set_mcp_tools([mcp])

        profile = SpawnProfile(name="test-profile", description="Test")

        with patch("openpaw.workspace.agent_factory.AgentRunner") as MockRunner:
            factory.create_profiled_agent(profile)
            tools = _tools_from_call(MockRunner)

        assert builtin in tools
        assert workspace in tools
        assert mcp in tools
