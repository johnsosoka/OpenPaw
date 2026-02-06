"""Builtin loader for workspace-aware instantiation."""

import logging
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
    """

    def __init__(
        self,
        global_config: "BuiltinsConfig | None" = None,
        workspace_config: "WorkspaceBuiltinsConfig | None" = None,
    ):
        """Initialize the loader.

        Args:
            global_config: Global builtins configuration.
            workspace_config: Workspace-specific overrides.
        """
        self.global_config = global_config
        self.workspace_config = workspace_config
        self.registry = BuiltinRegistry.get_instance()

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

        Args:
            name: The builtin name.

        Returns:
            Merged configuration dict.
        """
        config: dict[str, Any] = {}

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

    def load_tools(self) -> list[Any]:
        """Load all allowed and available tool builtins.

        Returns:
            List of LangChain-compatible tool instances.
        """
        tools: list[Any] = []

        for name, metadata in self.registry.get_available_tools().items():
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
                    tools.append(instance.get_langchain_tool())
                    logger.info(f"Loaded tool builtin: {name}")
                except Exception as e:
                    logger.warning(f"Failed to load tool '{name}': {e}")

        return tools

    def load_processors(self) -> list[BaseBuiltinProcessor]:
        """Load all allowed and available processor builtins.

        Returns:
            List of processor instances.
        """
        processors: list[BaseBuiltinProcessor] = []

        for name, metadata in self.registry.get_available_processors().items():
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
