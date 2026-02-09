"""Agent factory for creating AgentRunner instances."""

import logging
from collections.abc import Callable
from typing import Any

from openpaw.agent import AgentRunner
from openpaw.core.config import WorkspaceToolsConfig


class AgentFactory:
    """Factory for creating configured AgentRunner instances."""

    def __init__(
        self,
        workspace: Any,
        model: str,
        api_key: str | None,
        max_turns: int,
        temperature: float,
        region: str | None,
        timeout_seconds: float,
        builtin_tools: list[Any],
        workspace_tools: list[Any],
        enabled_builtin_names: list[str],
        extra_model_kwargs: dict[str, Any],
        middleware: list[Any],
        logger: logging.Logger,
    ):
        """Initialize agent factory.

        Args:
            workspace: AgentWorkspace instance.
            model: Model identifier string.
            api_key: API key for model provider.
            max_turns: Maximum agent turns.
            temperature: Model temperature.
            region: AWS region for Bedrock models.
            timeout_seconds: Request timeout.
            builtin_tools: List of builtin tools.
            workspace_tools: List of workspace-specific tools.
            enabled_builtin_names: Names of enabled builtins.
            extra_model_kwargs: Additional model parameters.
            middleware: List of middleware instances.
            logger: Logger instance.
        """
        self._workspace = workspace
        self._model = model
        self._api_key = api_key
        self._max_turns = max_turns
        self._temperature = temperature
        self._region = region
        self._timeout_seconds = timeout_seconds
        self._builtin_tools = builtin_tools
        self._workspace_tools = workspace_tools
        self._enabled_builtin_names = enabled_builtin_names
        self._extra_model_kwargs = extra_model_kwargs
        self._middleware = middleware
        self._logger = logger

    def create_agent(self, checkpointer: Any | None = None) -> AgentRunner:
        """Create a configured AgentRunner instance.

        Args:
            checkpointer: Optional checkpointer for conversation state.

        Returns:
            Configured AgentRunner instance.
        """
        all_tools = list(self._builtin_tools) + list(self._workspace_tools)

        return AgentRunner(
            workspace=self._workspace,
            model=self._model,
            api_key=self._api_key,
            max_turns=self._max_turns,
            temperature=self._temperature,
            checkpointer=checkpointer,
            tools=all_tools if all_tools else None,
            region=self._region,
            timeout_seconds=self._timeout_seconds,
            enabled_builtins=self._enabled_builtin_names,
            extra_model_kwargs=self._extra_model_kwargs,
            middleware=self._middleware,
        )

    def create_stateless_agent(self) -> AgentRunner:
        """Create a stateless agent for scheduled tasks (no checkpointer).

        Returns:
            AgentRunner without conversation state.
        """
        all_tools = list(self._builtin_tools) + list(self._workspace_tools)

        return AgentRunner(
            workspace=self._workspace,
            model=self._model,
            api_key=self._api_key,
            max_turns=self._max_turns,
            temperature=self._temperature,
            checkpointer=None,  # No checkpointer for scheduled tasks
            tools=all_tools if all_tools else None,
            region=self._region,
            timeout_seconds=self._timeout_seconds,
            enabled_builtins=self._enabled_builtin_names,
            extra_model_kwargs=self._extra_model_kwargs,
            middleware=[],  # No middleware for stateless agents
        )

    def get_agent_factory_closure(self) -> Callable[[], AgentRunner]:
        """Create a closure for spawning stateless agents.

        Returns:
            Callable that creates fresh AgentRunner instances.
        """
        return lambda: self.create_stateless_agent()


def filter_workspace_tools(
    tools: list[Any],
    config: Any,
    logger: logging.Logger,
) -> list[Any]:
    """Filter workspace tools based on allow/deny lists.

    Args:
        tools: List of workspace tools to filter.
        config: WorkspaceToolsConfig with allow/deny lists.
        logger: Logger for reporting filtered tools.

    Returns:
        Filtered list of tools.
    """
    # Handle case where config might not be WorkspaceToolsConfig
    if not isinstance(config, WorkspaceToolsConfig):
        return tools

    deny = config.deny
    allow = config.allow

    # No filtering if both lists are empty
    if not deny and not allow:
        return tools

    filtered = []
    filtered_out = []

    for tool in tools:
        tool_name = tool.name

        # Deny takes precedence
        if deny and tool_name in deny:
            filtered_out.append(tool_name)
            continue

        # Allow list filtering (if populated)
        if allow and tool_name not in allow:
            filtered_out.append(tool_name)
            continue

        filtered.append(tool)

    if filtered_out:
        logger.info(f"Filtered out workspace tools: {filtered_out}")

    if filtered:
        tool_names = [t.name for t in filtered]
        logger.info(f"Active workspace tools after filtering: {tool_names}")

    return filtered
