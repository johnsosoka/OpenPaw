"""Agent factory for creating AgentRunner instances."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from openpaw.agent import AgentRunner
from openpaw.core.config import WorkspaceToolsConfig


@dataclass
class RuntimeModelOverride:
    """Runtime override for model parameters. Ephemeral (lost on restart)."""
    model: str | None = None
    temperature: float | None = None


class AgentFactory:
    """Factory for creating configured AgentRunner instances."""

    # Provider to environment variable mapping for API keys
    _PROVIDER_KEY_ENV_VARS = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "bedrock_converse": None,
        "bedrock": None,
        "xai": "XAI_API_KEY",
    }

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
        self._configured_model = model
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
        self._runtime_override: RuntimeModelOverride | None = None

    @property
    def active_model(self) -> str:
        """Return currently active model (runtime override or configured)."""
        if self._runtime_override and self._runtime_override.model:
            return self._runtime_override.model
        return self._configured_model

    @property
    def configured_model(self) -> str:
        """Return statically configured model (ignoring overrides)."""
        return self._configured_model

    def set_runtime_override(self, override: RuntimeModelOverride) -> None:
        """Apply a runtime model override for the main agent."""
        self._runtime_override = override

    def clear_runtime_override(self) -> None:
        """Clear runtime override, reverting to configured model."""
        self._runtime_override = None

    def _resolve_api_key(self, model_str: str) -> str | None:
        """Resolve API key for the given model's provider."""
        import os

        provider = model_str.split(":")[0] if ":" in model_str else "openai"
        configured_provider = self._configured_model.split(":")[0] if ":" in self._configured_model else "openai"

        if provider == configured_provider:
            return self._api_key
        if provider in ("bedrock_converse", "bedrock"):
            return None

        env_var = self._PROVIDER_KEY_ENV_VARS.get(provider)
        if env_var:
            return os.environ.get(env_var)
        return None

    def validate_model(self, model_str: str) -> tuple[bool, str]:
        """Validate a model string by attempting instantiation."""
        from openpaw.agent.runner import create_chat_model

        if ":" in model_str:
            provider, _model_name = model_str.split(":", 1)
        else:
            provider = "openai"

        supported = {"openai", "anthropic", "bedrock_converse", "bedrock", "xai"}
        if provider not in supported:
            return False, f"Unsupported provider: '{provider}'. Supported: {', '.join(sorted(supported))}"

        api_key = self._resolve_api_key(model_str)
        if provider not in ("bedrock_converse", "bedrock") and not api_key:
            env_var = self._PROVIDER_KEY_ENV_VARS.get(provider, f"{provider.upper()}_API_KEY")
            return False, f"No API key for provider '{provider}'. Set {env_var} in environment."

        try:
            create_chat_model(model_str, api_key, self._temperature, self._region)
            return True, f"Model validated: {model_str}"
        except Exception as e:
            return False, f"Invalid model '{model_str}': {e}"

    def create_agent(self, checkpointer: Any | None = None) -> AgentRunner:
        """Create a configured AgentRunner instance.

        Args:
            checkpointer: Optional checkpointer for conversation state.

        Returns:
            Configured AgentRunner instance.
        """
        all_tools = list(self._builtin_tools) + list(self._workspace_tools)

        model = self.active_model
        api_key = self._resolve_api_key(model) if self._runtime_override else self._api_key
        temperature = self._temperature
        if self._runtime_override and self._runtime_override.temperature is not None:
            temperature = self._runtime_override.temperature

        return AgentRunner(
            workspace=self._workspace,
            model=model,
            api_key=api_key,
            max_turns=self._max_turns,
            temperature=temperature,
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

        Always uses configured model, ignoring runtime overrides.

        Returns:
            AgentRunner without conversation state.
        """
        all_tools = list(self._builtin_tools) + list(self._workspace_tools)

        return AgentRunner(
            workspace=self._workspace,
            model=self._configured_model,
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

    def remove_builtin_tools(self, tool_names: set[str]) -> None:
        """Remove builtin tools by LangChain tool name.

        Filters tools from the factory's builtin tool list and enabled names.
        Subsequent create_agent() calls will exclude these tools.

        Args:
            tool_names: Set of LangChain tool names to remove (e.g., {"search_conversations"}).
        """
        before_count = len(self._builtin_tools)
        self._builtin_tools = [t for t in self._builtin_tools if t.name not in tool_names]
        removed = before_count - len(self._builtin_tools)
        if removed:
            self._logger.info(f"Removed {removed} builtin tool(s): {tool_names}")
        else:
            self._logger.debug(f"No matching builtin tools found to remove: {tool_names}")

    def remove_enabled_builtin(self, name: str) -> None:
        """Remove a builtin name from the enabled list.

        This affects framework prompt generation (conditional sections).

        Args:
            name: Builtin name to remove (e.g., "memory_search").
        """
        if name in self._enabled_builtin_names:
            self._enabled_builtin_names.remove(name)

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
