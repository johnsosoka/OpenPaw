"""Builtin loader for workspace-aware instantiation."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openpaw.builtins.base import BaseBuiltinProcessor
from openpaw.builtins.registry import BuiltinRegistry

if TYPE_CHECKING:
    from openpaw.core.config import BuiltinsConfig, WorkspaceBuiltinsConfig

logger = logging.getLogger(__name__)


class BuiltinLoader:
    """Loads and configures builtins for a workspace.

    Handles:
    - Allow/deny list evaluation (deny wins)
    - Prerequisite checking (API keys, packages)
    - Config merging (workspace overrides global)
    - Instantiation with merged config
    - Workspace path injection for tools that need it
    """

    def __init__(
        self,
        global_config: "BuiltinsConfig | None" = None,
        workspace_config: "WorkspaceBuiltinsConfig | None" = None,
        workspace_path: Path | None = None,
        channel_config: dict[str, Any] | None = None,
    ):
        """Initialize the loader.

        Args:
            global_config: Global builtins configuration.
            workspace_config: Workspace-specific overrides.
            workspace_path: Path to the workspace directory (for tools that need it).
            channel_config: Channel configuration for routing (e.g., telegram allowed_users).
        """
        self.global_config = global_config
        self.workspace_config = workspace_config
        self.workspace_path = workspace_path
        self.channel_config = channel_config or {}
        self.registry = BuiltinRegistry.get_instance()
        self._tool_instances: dict[str, Any] = {}  # Track loaded tool instances

    def _is_allowed(self, name: str, group: str | None) -> bool:
        """Check if a builtin is allowed based on allow/deny lists.

        Deny takes precedence over allow. Empty allow list means allow all.

        Args:
            name: The builtin name.
            group: The builtin's group (if any).

        Returns:
            True if the builtin should be loaded.
        """
        # Collect deny lists
        deny: list[str] = []
        if self.global_config:
            deny.extend(self.global_config.deny)
        if self.workspace_config:
            deny.extend(self.workspace_config.deny)

        # Check deny (takes precedence)
        if name in deny:
            return False
        if group and f"group:{group}" in deny:
            return False

        # Collect allow lists
        allow: list[str] = []
        if self.global_config:
            allow.extend(self.global_config.allow)
        if self.workspace_config:
            allow.extend(self.workspace_config.allow)

        # Empty allow = allow all
        if not allow:
            return True

        # Check allow
        return name in allow or (group is not None and f"group:{group}" in allow)

    def _get_builtin_config(self, name: str) -> dict[str, Any]:
        """Get merged configuration for a builtin.

        Workspace config overrides global config.
        Automatically injects workspace_path for tools that need it.

        Args:
            name: The builtin name.

        Returns:
            Merged configuration dict.
        """
        config: dict[str, Any] = {}

        # Inject workspace_path for tools that need it
        if self.workspace_path:
            config["workspace_path"] = self.workspace_path

        # Inject channel routing config for cron tool
        if name == "cron" and self.channel_config:
            channel_type = self.channel_config.get("type", "telegram")
            config["default_channel"] = channel_type
            # Use first allowed user as default chat_id for routing
            allowed_users = self.channel_config.get("allowed_users", [])
            if allowed_users:
                config["default_chat_id"] = allowed_users[0]

        # Global config
        if self.global_config:
            global_cfg = getattr(self.global_config, name, None)
            if global_cfg and hasattr(global_cfg, "config"):
                config.update(global_cfg.config)

        # Workspace config (overrides)
        if self.workspace_config:
            workspace_cfg = getattr(self.workspace_config, name, None)
            if workspace_cfg and hasattr(workspace_cfg, "config"):
                config.update(workspace_cfg.config)

        return config

    def _is_enabled(self, name: str) -> bool:
        """Check if a builtin is explicitly enabled/disabled.

        Workspace setting takes precedence over global.

        Args:
            name: The builtin name.

        Returns:
            True if enabled (default is True).
        """
        # Check workspace first
        if self.workspace_config:
            workspace_cfg = getattr(self.workspace_config, name, None)
            if workspace_cfg is not None and hasattr(workspace_cfg, "enabled"):
                return bool(workspace_cfg.enabled)

        # Check global
        if self.global_config:
            global_cfg = getattr(self.global_config, name, None)
            if global_cfg is not None and hasattr(global_cfg, "enabled"):
                return bool(global_cfg.enabled)

        return True  # Default enabled

    def _has_config_api_key(self, name: str) -> bool:
        """Check if config provides an api_key for this builtin."""
        config = self._get_builtin_config(name)
        return bool(config.get("api_key"))

    def load_tools(self) -> list[Any]:
        """Load all allowed and available tool builtins.

        A tool is available if either:
        - Its prerequisites are satisfied (env vars set), OR
        - Its config contains an api_key

        Returns:
            List of LangChain-compatible tool instances.
        """
        tools: list[Any] = []

        # Check all registered tools, not just those with satisfied prerequisites
        all_tools = self.registry.list_all()["tools"]
        for metadata in all_tools:
            name = metadata.name

            # Check if available via env vars OR config api_key
            if not metadata.prerequisites.is_satisfied() and not self._has_config_api_key(name):
                logger.debug(f"Tool '{name}' not available (no env var or config api_key)")
                continue

            if not self._is_allowed(name, metadata.group):
                logger.debug(f"Tool '{name}' denied by config")
                continue

            if not self._is_enabled(name):
                logger.debug(f"Tool '{name}' disabled")
                continue

            tool_class = self.registry.get_tool_class(name)
            if tool_class:
                config = self._get_builtin_config(name)
                try:
                    instance = tool_class(config=config)
                    self._tool_instances[name] = instance  # Store for later access
                    tool_result = instance.get_langchain_tool()
                    # Handle tools that return a list (like CronTool with multiple methods)
                    if isinstance(tool_result, list):
                        tools.extend(tool_result)
                    else:
                        tools.append(tool_result)
                    logger.info(f"Loaded tool builtin: {name}")
                except Exception as e:
                    logger.warning(f"Failed to load tool '{name}': {e}")

        return tools

    def get_tool_instance(self, name: str) -> Any | None:
        """Get a loaded tool instance by name.

        Args:
            name: The builtin name (e.g., 'cron').

        Returns:
            The tool instance, or None if not loaded.
        """
        return self._tool_instances.get(name)

    def load_processors(self) -> list[BaseBuiltinProcessor]:
        """Load all allowed and available processor builtins.

        A processor is available if either:
        - Its prerequisites are satisfied (env vars set), OR
        - Its config contains an api_key

        Returns:
            List of processor instances.
        """
        processors: list[BaseBuiltinProcessor] = []

        # Check all registered processors, not just those with satisfied prerequisites
        all_processors = self.registry.list_all()["processors"]
        for metadata in all_processors:
            name = metadata.name

            # Check if available via env vars OR config api_key
            if not metadata.prerequisites.is_satisfied() and not self._has_config_api_key(name):
                logger.debug(f"Processor '{name}' not available (no env var or config api_key)")
                continue

            if not self._is_allowed(name, metadata.group):
                logger.debug(f"Processor '{name}' denied by config")
                continue

            if not self._is_enabled(name):
                logger.debug(f"Processor '{name}' disabled")
                continue

            processor_class = self.registry.get_processor_class(name)
            if processor_class:
                config = self._get_builtin_config(name)
                try:
                    instance = processor_class(config=config)
                    processors.append(instance)
                    logger.info(f"Loaded processor builtin: {name}")
                except Exception as e:
                    logger.warning(f"Failed to load processor '{name}': {e}")

        return processors
