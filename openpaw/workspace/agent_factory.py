"""Agent factory for creating AgentRunner instances."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from openpaw.agent import AgentRunner
from openpaw.agent.harness import AgentHarness, HarnessKind
from openpaw.agent.harness.balanced import BalancedHarness, build_balanced_middleware
from openpaw.agent.harness.checkpoint_reflection import CheckpointReflector
from openpaw.agent.harness.lenses import create_explore_lenses_tool
from openpaw.agent.harness.ultra import UltraHarness
from openpaw.core.config.models import HarnessConfig, ProviderDefinition
from openpaw.model.spawn_profile import SpawnProfile
from openpaw.model.status_event import StatusEmitter
from openpaw.workspace.model_resolver import ModelResolver
from openpaw.workspace.node_model_resolver import NodeModelResolver
from openpaw.workspace.tool_filter import filter_workspace_tools

__all__ = ["AgentFactory", "RuntimeModelOverride", "filter_workspace_tools"]


@dataclass
class RuntimeModelOverride:
    """Runtime override for model parameters. Ephemeral (lost on restart)."""
    model: str | None = None
    temperature: float | None = None


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
        provider_catalog: dict[str, ProviderDefinition] | None = None,
        channel_logging_enabled: bool = False,
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
            provider_catalog: Named provider catalog from global config. When
                provided, provider names are resolved before being passed to
                LangChain so that catalog entries (e.g. ``moonshot``) map to
                the correct LangChain type (e.g. ``openai``).
            channel_logging_enabled: Whether persistent channel logging is active.
        """
        self._workspace = workspace
        self._configured_model = model
        self._max_turns = max_turns
        self._temperature = temperature
        self._timeout_seconds = timeout_seconds
        self._builtin_tools = builtin_tools
        self._workspace_tools = workspace_tools
        self._mcp_tools: list[Any] = []
        self._enabled_builtin_names = enabled_builtin_names
        self._middleware = middleware
        self._logger = logger
        self._channel_logging_enabled = channel_logging_enabled

        self._resolver = ModelResolver(
            provider_catalog=provider_catalog or {},
            configured_model=model,
            api_key=api_key,
            region=region,
            extra_model_kwargs=extra_model_kwargs,
        )
        self._runtime_override: RuntimeModelOverride | None = None
        self._status_emitter: StatusEmitter | None = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def active_model(self) -> str:
        """Return the user-facing display name of the currently active model.

        When a runtime override is set the override's display string is
        returned; otherwise the configured model's display string is used.
        """
        if self._runtime_override and self._runtime_override.model:
            return self._resolver.display_str(self._runtime_override.model)
        return self._resolver.display_str(self._configured_model)

    @property
    def configured_model(self) -> str:
        """Return the user-facing display name of the statically configured model."""
        return self._resolver.display_str(self._configured_model)

    # ------------------------------------------------------------------
    # Runtime override management
    # ------------------------------------------------------------------

    def set_runtime_override(self, override: RuntimeModelOverride) -> None:
        """Apply a runtime model override for the main agent."""
        self._runtime_override = override

    def clear_runtime_override(self) -> None:
        """Clear runtime override, reverting to configured model."""
        self._runtime_override = None

    # ------------------------------------------------------------------
    # Agent creation
    # ------------------------------------------------------------------

    def set_mcp_tools(self, tools: list[Any]) -> None:
        """Register MCP-sourced tools so subsequent agent rebuilds include them.

        Without this, connectors that rebuild via create_agent() (e.g. when
        removing search_conversations after vector-store init failure) would
        silently drop the MCP tools previously injected via update_tools().
        """
        self._mcp_tools = list(tools)

    @property
    def status_emitter(self) -> StatusEmitter | None:
        """The wired status event emitter, if any (used by SkillStore wiring)."""
        return self._status_emitter

    def set_status_emitter(self, emitter: StatusEmitter) -> None:
        """Wire the status event emitter used by harness nodes (ADR-106).

        Call before create_harness(); defaults to a no-op emitter when unset.
        """
        self._status_emitter = emitter

    def create_harness(self, checkpointer: Any | None = None) -> AgentHarness:
        """Create the interactive agent harness for this workspace.

        The seam callers (WorkspaceRunner/MessageProcessor/connector) hold —
        they never depend on the underlying graph topology (ADR-101 §2).
        Dispatches on ``workspace.config.harness.type``: react (default) is
        the exact current AgentRunner path; balanced is that same runner with
        the todo/plan middleware appended (ADR-111); ultra wraps the runner
        as the execution engine inside the ADR-101 graph.

        Args:
            checkpointer: Optional checkpointer for conversation state.

        Returns:
            The configured AgentHarness.
        """
        harness_config: HarnessConfig | None = (
            self._workspace.config.harness if getattr(self._workspace, "config", None) else None
        )
        if harness_config is not None and harness_config.type == HarnessKind.BALANCED.value:
            return self._create_balanced_harness(harness_config, checkpointer)
        if harness_config is None or harness_config.type != HarnessKind.ULTRA.value:
            return self.create_agent(checkpointer=checkpointer)

        inner = self.create_agent(checkpointer=checkpointer)
        node_resolver = self._build_node_resolver()
        self._logger.info("Creating ultra harness for workspace: %s", self._workspace.name)
        return UltraHarness(
            workspace=self._workspace,
            inner=inner,
            harness_config=harness_config,
            node_resolver=node_resolver,
            emitter=self._status_emitter,
            # Tool equipping (ADR-104): step-scoped executors are built here,
            # in the factory, because it owns every construction param — the
            # subset agent matches the inner runner's workspace, model
            # resolution, and middleware, just with fewer tools and no
            # checkpointer (step runs are unpersisted by design).
            step_agent_builder=lambda tools: self.create_agent(checkpointer=None, tools_override=tools),
        )

    def _build_node_resolver(self) -> NodeModelResolver:
        """Node-model resolution over the workspace baseline (ADR-103).

        Shared by the ultra harness (per-node models) and the balanced
        harness (optional checkpoint-verdict model pointer).
        """
        return NodeModelResolver(
            resolver=self._resolver,
            workspace_model=self._configured_model,
            workspace_api_key=self._resolver.resolve_api_key(self._configured_model),
            workspace_temperature=self._temperature,
            workspace_region=self._resolver._region,
            workspace_extra_kwargs=self._resolver._extra_model_kwargs,
        )

    def _build_checkpoint_reflector(
        self, harness_config: HarnessConfig
    ) -> CheckpointReflector | None:
        """The checkpoint reflector when ``harness.reflection.mode: checkpoint``.

        An explicit ``reflection.model`` pointer resolves like ultra's node
        models (NodeModelResolver -> create_node_model, lazily); unset falls
        back to the runner's workspace model, wired by BalancedHarness.
        """
        reflection = harness_config.reflection
        if reflection.mode != "checkpoint":
            return None
        model_factory = None
        if reflection.model is not None:
            model_factory = partial(
                self._build_node_resolver().create_node_model, reflection
            )
        return CheckpointReflector(every=reflection.every, model_factory=model_factory)

    def _create_balanced_harness(
        self, harness_config: HarnessConfig, checkpointer: Any | None
    ) -> BalancedHarness:
        """Construct the balanced harness (ADR-111).

        Same runner kwargs as the react path, with the todo/plan middleware
        appended after the workspace stack, the ``explore_lenses`` tool
        registered when ``harness.ideation.lens_tool`` is enabled (balanced
        workspaces only, DESIGN §10.3), checkpoint reflection wired when
        configured (DESIGN §3), and the optional
        ``harness.execution.timeout_seconds`` override applied.
        """
        ideation = harness_config.ideation
        kwargs = self._runner_kwargs(checkpointer, tools_override=None)
        kwargs["middleware"] = [
            *kwargs["middleware"],
            *build_balanced_middleware(
                emitter=self._status_emitter,
                workspace_name=self._workspace.name,
                plan_visibility=harness_config.plan.visibility,
                lens_guidance=ideation.lens_tool,
                lens_count=ideation.lens_count,
                reflector=self._build_checkpoint_reflector(harness_config),
            ),
        ]
        if ideation.lens_tool:
            kwargs["tools"] = [
                *(kwargs["tools"] or []),
                create_explore_lenses_tool(ideation.lens_count),
            ]
        self._logger.info("Creating balanced harness for workspace: %s", self._workspace.name)
        harness = BalancedHarness(**kwargs)
        if harness_config.execution.timeout_seconds is not None:
            harness.timeout_seconds = harness_config.execution.timeout_seconds
        return harness

    def _runner_kwargs(
        self, checkpointer: Any | None, tools_override: list[Any] | None
    ) -> dict[str, Any]:
        """Resolve the constructor kwargs shared by the react and balanced paths."""
        all_tools = (
            list(tools_override)
            if tools_override is not None
            else list(self._builtin_tools) + list(self._workspace_tools) + list(self._mcp_tools)
        )

        raw_model = (
            self._runtime_override.model
            if self._runtime_override and self._runtime_override.model
            else self._configured_model
        )
        resolved = self._resolver.resolve(raw_model)

        api_key = (
            resolved.api_key
            if resolved.api_key is not None
            else (
                self._resolver.resolve_api_key(raw_model)
                if self._runtime_override
                else self._resolver.resolve_api_key(self._configured_model)
            )
        )

        temperature = self._temperature
        if self._runtime_override and self._runtime_override.temperature is not None:
            temperature = self._runtime_override.temperature

        # Merge catalog extras with workspace-level extras; workspace wins.
        merged_extra = {**resolved.extra_kwargs, **self._resolver._extra_model_kwargs}
        region = resolved.region or self._resolver._region

        return {
            "workspace": self._workspace,
            "model": resolved.model_str,
            "api_key": api_key,
            "max_turns": self._max_turns,
            "temperature": temperature,
            "checkpointer": checkpointer,
            "tools": all_tools if all_tools else None,
            "region": region,
            "timeout_seconds": self._timeout_seconds,
            "enabled_builtins": self._enabled_builtin_names,
            "extra_model_kwargs": merged_extra,
            "middleware": self._middleware,
            "channel_logging_enabled": self._channel_logging_enabled,
        }

    def create_agent(
        self, checkpointer: Any | None = None, tools_override: list[Any] | None = None
    ) -> AgentRunner:
        """Create a configured AgentRunner instance.

        Args:
            checkpointer: Optional checkpointer for conversation state.
            tools_override: Replace the additional-tools set (builtin +
                workspace + MCP) with an explicit list. Used by tool
                equipping to build step-scoped executors over a subset.

        Returns:
            Configured AgentRunner instance.
        """
        return AgentRunner(**self._runner_kwargs(checkpointer, tools_override))

    def create_stateless_agent(
        self, extra_overrides: dict[str, Any] | None = None
    ) -> AgentRunner:
        """Create a stateless agent for scheduled tasks (no checkpointer).

        Always uses configured model, ignoring runtime overrides.
        """
        all_tools = list(self._builtin_tools) + list(self._workspace_tools) + list(self._mcp_tools)

        resolved = self._resolver.resolve(self._configured_model)
        api_key = (
            resolved.api_key
            if resolved.api_key is not None
            else self._resolver.resolve_api_key(self._configured_model)
        )
        # Resolution order: catalog extras < workspace extras < per-call overrides
        merged_extra = {**resolved.extra_kwargs, **self._resolver._extra_model_kwargs}
        if extra_overrides:
            merged_extra.update(extra_overrides)
        region = resolved.region or self._resolver._region

        return AgentRunner(
            workspace=self._workspace,
            model=resolved.model_str,
            api_key=api_key,
            max_turns=self._max_turns,
            temperature=self._temperature,
            checkpointer=None,
            tools=all_tools if all_tools else None,
            region=region,
            timeout_seconds=self._timeout_seconds,
            enabled_builtins=self._enabled_builtin_names,
            extra_model_kwargs=merged_extra,
            middleware=[],
            channel_logging_enabled=self._channel_logging_enabled,
        )

    def create_profiled_agent(
        self,
        profile: SpawnProfile,
        extra_overrides: dict[str, Any] | None = None,
    ) -> AgentRunner:
        """Create a stateless agent with profile-driven overrides.

        Uses the profile's model, temperature, and max_turns when set,
        falling back to workspace defaults.
        """
        all_tools = list(self._builtin_tools) + list(self._workspace_tools) + list(self._mcp_tools)

        if profile.model is not None:
            resolved = self._resolver.resolve(profile.model)
            api_key = (
                resolved.api_key
                if resolved.api_key is not None
                else self._resolver.resolve_api_key(profile.model)
            )
        else:
            resolved = self._resolver.resolve(self._configured_model)
            api_key = (
                resolved.api_key
                if resolved.api_key is not None
                else self._resolver.resolve_api_key(self._configured_model)
            )

        temperature = (
            profile.temperature
            if profile.temperature is not None
            else self._temperature
        )
        max_turns = (
            profile.max_turns if profile.max_turns is not None else self._max_turns
        )
        # Resolution order: catalog extras < workspace extras < per-call overrides
        merged_extra = {**resolved.extra_kwargs, **self._resolver._extra_model_kwargs}
        if extra_overrides:
            merged_extra.update(extra_overrides)
        region = resolved.region or self._resolver._region

        return AgentRunner(
            workspace=self._workspace,
            model=resolved.model_str,
            api_key=api_key,
            max_turns=max_turns,
            temperature=temperature,
            checkpointer=None,
            tools=all_tools if all_tools else None,
            region=region,
            timeout_seconds=self._timeout_seconds,
            enabled_builtins=self._enabled_builtin_names,
            extra_model_kwargs=merged_extra,
            middleware=[],
            channel_logging_enabled=self._channel_logging_enabled,
        )

    # ------------------------------------------------------------------
    # Tool management
    # ------------------------------------------------------------------

    def remove_builtin_tools(self, tool_names: set[str]) -> None:
        """Remove builtin tools by LangChain tool name."""
        before_count = len(self._builtin_tools)
        self._builtin_tools = [t for t in self._builtin_tools if t.name not in tool_names]
        removed = before_count - len(self._builtin_tools)
        if removed:
            self._logger.info(f"Removed {removed} builtin tool(s): {tool_names}")
        else:
            self._logger.debug(f"No matching builtin tools found to remove: {tool_names}")

    def remove_enabled_builtin(self, name: str) -> None:
        """Remove a builtin name from the enabled list."""
        if name in self._enabled_builtin_names:
            self._enabled_builtin_names.remove(name)

    def get_agent_factory_closure(self) -> Callable[..., AgentRunner]:
        """Create a closure for spawning stateless agents."""
        return lambda **kwargs: self.create_stateless_agent(**kwargs)

    # ------------------------------------------------------------------
    # Delegated methods (backward compatibility)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Backward-compatible internal accessors
    # ------------------------------------------------------------------

    @property
    def _provider_catalog(self) -> dict[str, Any]:
        """Backward-compatible accessor for internal provider catalog."""
        return self._resolver._provider_catalog

    @_provider_catalog.setter
    def _provider_catalog(self, value: dict[str, Any]) -> None:
        """Backward-compatible setter for internal provider catalog."""
        self._resolver._provider_catalog = value

    @property
    def _extra_model_kwargs(self) -> dict[str, Any]:
        """Backward-compatible accessor for internal extra model kwargs."""
        return self._resolver._extra_model_kwargs

    @_extra_model_kwargs.setter
    def _extra_model_kwargs(self, value: dict[str, Any]) -> None:
        """Backward-compatible setter for internal extra model kwargs."""
        self._resolver._extra_model_kwargs = value

    def _resolve_for_model(self, model_str: str) -> Any:
        """Resolve a model string through the provider catalog.

        Backward-compatible delegate to ModelResolver.
        """
        return self._resolver.resolve(model_str)

    def _resolve_api_key(self, model_str: str) -> str | None:
        """Resolve API key for the given model's provider.

        Backward-compatible delegate to ModelResolver.
        """
        return self._resolver.resolve_api_key(model_str)

    def validate_model(self, model_str: str) -> tuple[bool, str]:
        """Validate a model string by attempting instantiation.

        Backward-compatible delegate to ModelResolver.
        """
        return self._resolver.validate(model_str, self._temperature)


