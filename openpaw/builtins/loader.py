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
        workspace_timezone: str = "UTC",
        task_store: Any | None = None,
    ):
        """Initialize the loader.

        Args:
            global_config: Global builtins configuration.
            workspace_config: Workspace-specific overrides.
            workspace_path: Path to the workspace directory (for tools that need it).
            channel_config: Channel configuration for routing (e.g., telegram allowed_users).
            workspace_timezone: Workspace timezone for temporal operations (e.g., 'America/Los_Angeles').
            task_store: TaskStore instance for task management builtins.
        """
        self.global_config = global_config
        self.workspace_config = workspace_config
        self.workspace_path = workspace_path
        self.channel_config = channel_config or {}
        self.workspace_timezone = workspace_timezone
        self.task_store = task_store
        self.registry = BuiltinRegistry.get_instance()
        self._tool_instances: dict[str, Any] = {}  # Track loaded tool instances

    @staticmethod
    def _get_field(obj: Any, field: str, default: Any = None) -> Any:
        """Get a field from a Pydantic model or dict.

        Args:
            obj: Object to extract field from (can be Pydantic model or dict).
            field: Field name to extract.
            default: Default value if field not found.

        Returns:
            Field value or default.
        """
        if isinstance(obj, dict):
            return obj.get(field, default)
        return getattr(obj, field, default)

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
        Automatically injects workspace_path and timezone for tools that need it.

        Args:
            name: The builtin name.

        Returns:
            Merged configuration dict.
        """
        config: dict[str, Any] = {}

        # Inject workspace_path for tools that need it
        if self.workspace_path:
            config["workspace_path"] = self.workspace_path

        # Inject workspace timezone for all builtins (can be overridden by explicit config)
        config["timezone"] = self.workspace_timezone

        # Inject task_store for task management builtins
        if self.task_store and name in ("task_tracker", "tasks"):
            config["task_store"] = self.task_store

        # Inject channel routing config for cron tool
        if name == "cron" and self.channel_config:
            channel_type = self.channel_config.get("type", "telegram")
            config["default_channel"] = channel_type
            # Use first allowed user as default chat_id for routing
            allowed_users = self.channel_config.get("allowed_users", [])
            if allowed_users:
                config["default_chat_id"] = allowed_users[0]

        # Inject channel routing config for send_message tool
        if name == "send_message" and self.channel_config:
            channel_type = self.channel_config.get("type", "telegram")
            config["default_channel"] = channel_type

        # Extract max_file_size from SendFileBuiltinConfig if present
        if name == "send_file":
            if self.global_config:
                global_cfg = getattr(self.global_config, name, None)
                if global_cfg and hasattr(global_cfg, "max_file_size"):
                    config["max_file_size"] = global_cfg.max_file_size
            if self.workspace_config:
                workspace_cfg = getattr(self.workspace_config, name, None)
                if workspace_cfg and hasattr(workspace_cfg, "max_file_size"):
                    config["max_file_size"] = workspace_cfg.max_file_size

        # Extract typed fields from DoclingBuiltinConfig
        if name == "docling":
            _docling_fields = [
                "max_file_size", "ocr_backend", "ocr_languages",
                "force_full_page_ocr", "document_timeout", "do_ocr", "do_table_structure",
            ]
            if self.global_config:
                global_cfg = getattr(self.global_config, name, None)
                if global_cfg:
                    for field in _docling_fields:
                        if hasattr(global_cfg, field):
                            config[field] = getattr(global_cfg, field)
            if self.workspace_config:
                workspace_cfg = getattr(self.workspace_config, name, None)
                if workspace_cfg:
                    for field in _docling_fields:
                        if hasattr(workspace_cfg, field):
                            config[field] = getattr(workspace_cfg, field)

        # Extract typed fields from BrowserBuiltinConfig
        if name == "browser":
            _browser_fields = [
                "headless", "allowed_domains", "blocked_domains",
                "timeout_seconds", "persist_cookies", "downloads_dir", "screenshots_dir",
            ]
            if self.global_config:
                global_cfg = getattr(self.global_config, name, None)
                if global_cfg:
                    for fld in _browser_fields:
                        if hasattr(global_cfg, fld):
                            config[fld] = getattr(global_cfg, fld)
            if self.workspace_config:
                workspace_cfg = getattr(self.workspace_config, name, None)
                if workspace_cfg:
                    for fld in _browser_fields:
                        if hasattr(workspace_cfg, fld):
                            config[fld] = getattr(workspace_cfg, fld)

        # Extract typed fields from SpawnBuiltinConfig
        if name == "spawn":
            _spawn_fields = ["max_concurrent"]
            if self.global_config:
                global_cfg = getattr(self.global_config, name, None)
                if global_cfg:
                    for fld in _spawn_fields:
                        if hasattr(global_cfg, fld):
                            config[fld] = getattr(global_cfg, fld)
            if self.workspace_config:
                workspace_cfg = getattr(self.workspace_config, name, None)
                if workspace_cfg:
                    for fld in _spawn_fields:
                        if hasattr(workspace_cfg, fld):
                            config[fld] = getattr(workspace_cfg, fld)

        # Extract typed fields from FilePersistenceBuiltinConfig
        if name == "file_persistence":
            _fp_fields = ["max_file_size", "clear_data_after_save"]
            if self.global_config:
                global_cfg = getattr(self.global_config, name, None)
                if global_cfg:
                    for fld in _fp_fields:
                        if hasattr(global_cfg, fld):
                            config[fld] = getattr(global_cfg, fld)
            if self.workspace_config:
                workspace_cfg = getattr(self.workspace_config, name, None)
                if workspace_cfg:
                    for fld in _fp_fields:
                        if hasattr(workspace_cfg, fld):
                            config[fld] = getattr(workspace_cfg, fld)

        # Global config
        if self.global_config:
            global_cfg = getattr(self.global_config, name, None)
            cfg_dict = self._get_field(global_cfg, "config")
            if cfg_dict:
                config.update(cfg_dict)

        # Workspace config (overrides)
        if self.workspace_config:
            workspace_cfg = getattr(self.workspace_config, name, None)
            cfg_dict = self._get_field(workspace_cfg, "config")
            if cfg_dict:
                config.update(cfg_dict)

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
            if workspace_cfg is not None:
                enabled = self._get_field(workspace_cfg, "enabled")
                if enabled is not None:
                    return bool(enabled)

        # Check global
        if self.global_config:
            global_cfg = getattr(self.global_config, name, None)
            if global_cfg is not None:
                enabled = self._get_field(global_cfg, "enabled")
                if enabled is not None:
                    return bool(enabled)

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

    def get_loaded_tool_names(self) -> list[str]:
        """Get names of all loaded tool instances.

        Returns:
            List of builtin tool names that were successfully loaded.
        """
        return list(self._tool_instances.keys())

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

        # Sort by priority (lower = runs first in pipeline)
        processors.sort(key=lambda p: p.metadata.priority)

        return processors
