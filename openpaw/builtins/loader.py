"""Builtin loader for workspace-aware instantiation."""

import logging
from typing import TYPE_CHECKING, Any

from openpaw.builtins.base import BaseBuiltinProcessor
from openpaw.builtins.registry import BuiltinRegistry

if TYPE_CHECKING:
    from openpaw.api.services.builtin_service import BuiltinService
    from openpaw.core.config import BuiltinsConfig, WorkspaceBuiltinsConfig

logger = logging.getLogger(__name__)


class BuiltinLoader:
    """Loads and configures builtins for a workspace.

    Handles:
    - Allow/deny list evaluation (deny wins)
    - Prerequisite checking (API keys, packages)
    - Config merging (workspace overrides global)
    - Instantiation with merged config
    - Database integration for API keys and allow/deny lists (optional)

    Priority Order:
    - API keys: env var > database > YAML config
    - Allow/deny: database extends YAML config (both are merged)
    """

    def __init__(
        self,
        global_config: "BuiltinsConfig | None" = None,
        workspace_config: "WorkspaceBuiltinsConfig | None" = None,
        builtin_service: "BuiltinService | None" = None,
    ):
        """Initialize the loader.

        Args:
            global_config: Global builtins configuration.
            workspace_config: Workspace-specific overrides.
            builtin_service: Optional database service for API keys and allow/deny lists.
                If provided, database values will be checked before falling back to config.
        """
        self.global_config = global_config
        self.workspace_config = workspace_config
        self.builtin_service = builtin_service
        self.registry = BuiltinRegistry.get_instance()

        # Cache for database allow/deny lists (populated on first load)
        self._db_allow_deny: dict[str, list[str]] | None = None

    async def _load_db_allow_deny(self) -> dict[str, list[str]]:
        """Load allow/deny lists from database (cached).

        Returns:
            Dictionary with "allow" and "deny" keys.
        """
        if self._db_allow_deny is not None:
            return self._db_allow_deny

        if self.builtin_service is None:
            self._db_allow_deny = {"allow": [], "deny": []}
            return self._db_allow_deny

        try:
            self._db_allow_deny = await self.builtin_service.get_allowlist()
            logger.debug(f"Loaded allow/deny from database: {self._db_allow_deny}")
        except Exception as e:
            logger.warning(f"Failed to load allow/deny from database: {e}")
            self._db_allow_deny = {"allow": [], "deny": []}

        return self._db_allow_deny

    async def _get_api_key_from_db(self, builtin_name: str) -> str | None:
        """Get API key from database for a builtin.

        Maps builtin name to expected API key environment variable name.

        Args:
            builtin_name: The builtin name (e.g., "brave_search")

        Returns:
            Decrypted API key value or None if not found
        """
        if self.builtin_service is None:
            return None

        # Map builtin names to expected env var names
        env_var_map = {
            "brave_search": "BRAVE_API_KEY",
            "elevenlabs": "ELEVENLABS_API_KEY",
            "whisper": "OPENAI_API_KEY",
        }

        key_name = env_var_map.get(builtin_name)
        if not key_name:
            logger.debug(f"No env var mapping for builtin: {builtin_name}")
            return None

        try:
            value = await self.builtin_service.get_api_key_value(key_name)
            if value:
                logger.debug(f"Using database API key for: {builtin_name}")
            return value
        except Exception as e:
            logger.warning(f"Failed to get API key from database for {builtin_name}: {e}")
            return None

    def _is_allowed(self, name: str, group: str | None, db_allow_deny: dict[str, list[str]] | None = None) -> bool:
        """Check if a builtin is allowed based on allow/deny lists.

        Deny takes precedence over allow. Empty allow list means allow all.
        Database lists extend YAML config lists.

        Args:
            name: The builtin name.
            group: The builtin's group (if any).
            db_allow_deny: Optional database allow/deny lists to merge.

        Returns:
            True if the builtin should be loaded.
        """
        # Collect deny lists (YAML + database)
        deny: list[str] = []
        if self.global_config:
            deny.extend(self.global_config.deny)
        if self.workspace_config:
            deny.extend(self.workspace_config.deny)
        if db_allow_deny:
            deny.extend(db_allow_deny.get("deny", []))

        # Check deny (takes precedence)
        if name in deny:
            return False
        if group and f"group:{group}" in deny:
            return False

        # Collect allow lists (YAML + database)
        allow: list[str] = []
        if self.global_config:
            allow.extend(self.global_config.allow)
        if self.workspace_config:
            allow.extend(self.workspace_config.allow)
        if db_allow_deny:
            allow.extend(db_allow_deny.get("allow", []))

        # Empty allow = allow all
        if not allow:
            return True

        # Check allow
        return name in allow or (group is not None and f"group:{group}" in allow)

    async def _get_builtin_config(self, name: str) -> dict[str, Any]:
        """Get merged configuration for a builtin.

        Priority order for API keys: env var > database > YAML config.
        Workspace config overrides global config for other settings.

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

        # Check for API key in priority order: env var > database > YAML config
        # Only check database if not in env var and not in YAML config
        if "api_key" not in config or not config["api_key"]:
            # Check if env var is set (higher priority than database)
            metadata = None
            for meta in self.registry.list_all()["tools"]:
                if meta.name == name:
                    metadata = meta
                    break
            if not metadata:
                for meta in self.registry.list_all()["processors"]:
                    if meta.name == name:
                        metadata = meta
                        break

            # If env var not set, try database
            if metadata and not metadata.prerequisites.is_satisfied():
                db_key = await self._get_api_key_from_db(name)
                if db_key:
                    config["api_key"] = db_key
                    logger.info(f"Using database API key for builtin: {name}")

        return config

    def _get_builtin_config_sync(self, name: str) -> dict[str, Any]:
        """Get merged configuration for a builtin (synchronous, no database).

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

    async def _has_api_key_available(self, name: str) -> bool:
        """Check if an API key is available from any source (env, database, or config).

        Args:
            name: The builtin name.

        Returns:
            True if an API key is available from any source.
        """
        # Check environment variable first
        metadata = None
        for meta in self.registry.list_all()["tools"]:
            if meta.name == name:
                metadata = meta
                break
        if not metadata:
            for meta in self.registry.list_all()["processors"]:
                if meta.name == name:
                    metadata = meta
                    break

        if metadata and metadata.prerequisites.is_satisfied():
            return True

        # Check database
        if self.builtin_service:
            db_key = await self._get_api_key_from_db(name)
            if db_key:
                return True

        # Check YAML config
        config = self._get_builtin_config_sync(name)
        return bool(config.get("api_key"))

    def _has_config_api_key_sync(self, name: str) -> bool:
        """Check if config provides an api_key for this builtin (synchronous)."""
        config = self._get_builtin_config_sync(name)
        return bool(config.get("api_key"))

    async def load_tools_async(self) -> list[Any]:
        """Load all allowed and available tool builtins (async, with database support).

        A tool is available if either:
        - Its prerequisites are satisfied (env vars set), OR
        - An API key is available from database, OR
        - Its config contains an api_key

        Returns:
            List of LangChain-compatible tool instances.
        """
        tools: list[Any] = []

        # Load database allow/deny lists if available
        db_allow_deny = await self._load_db_allow_deny() if self.builtin_service else None

        # Check all registered tools, not just those with satisfied prerequisites
        all_tools = self.registry.list_all()["tools"]
        for metadata in all_tools:
            name = metadata.name

            # Check if available via env vars OR database OR config api_key
            if not await self._has_api_key_available(name):
                logger.debug(f"Tool '{name}' not available (no API key from any source)")
                continue

            if not self._is_allowed(name, metadata.group, db_allow_deny):
                logger.debug(f"Tool '{name}' denied by config")
                continue

            if not self._is_enabled(name):
                logger.debug(f"Tool '{name}' disabled")
                continue

            tool_class = self.registry.get_tool_class(name)
            if tool_class:
                config = await self._get_builtin_config(name)
                try:
                    instance = tool_class(config=config)
                    tools.append(instance.get_langchain_tool())
                    logger.info(f"Loaded tool builtin: {name}")
                except Exception as e:
                    logger.warning(f"Failed to load tool '{name}': {e}")

        return tools

    def load_tools(self) -> list[Any]:
        """Load all allowed and available tool builtins (synchronous, no database).

        A tool is available if either:
        - Its prerequisites are satisfied (env vars set), OR
        - Its config contains an api_key

        Returns:
            List of LangChain-compatible tool instances.

        Note:
            This is the synchronous version for backward compatibility.
            It does not check the database for API keys or allow/deny lists.
            Use load_tools_async() for full database integration.
        """
        if self.builtin_service is not None:
            logger.warning(
                "BuiltinLoader has database service but load_tools() was called "
                "synchronously. Database API keys and allow/deny lists will be ignored. "
                "Use load_tools_async() instead."
            )

        tools: list[Any] = []

        # Check all registered tools, not just those with satisfied prerequisites
        all_tools = self.registry.list_all()["tools"]
        for metadata in all_tools:
            name = metadata.name

            # Check if available via env vars OR config api_key
            if not metadata.prerequisites.is_satisfied() and not self._has_config_api_key_sync(name):
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
                config = self._get_builtin_config_sync(name)
                try:
                    instance = tool_class(config=config)
                    tools.append(instance.get_langchain_tool())
                    logger.info(f"Loaded tool builtin: {name}")
                except Exception as e:
                    logger.warning(f"Failed to load tool '{name}': {e}")

        return tools

    async def load_processors_async(self) -> list[BaseBuiltinProcessor]:
        """Load all allowed and available processor builtins (async, with database support).

        A processor is available if either:
        - Its prerequisites are satisfied (env vars set), OR
        - An API key is available from database, OR
        - Its config contains an api_key

        Returns:
            List of processor instances.
        """
        processors: list[BaseBuiltinProcessor] = []

        # Load database allow/deny lists if available
        db_allow_deny = await self._load_db_allow_deny() if self.builtin_service else None

        # Check all registered processors, not just those with satisfied prerequisites
        all_processors = self.registry.list_all()["processors"]
        for metadata in all_processors:
            name = metadata.name

            # Check if available via env vars OR database OR config api_key
            if not await self._has_api_key_available(name):
                logger.debug(f"Processor '{name}' not available (no API key from any source)")
                continue

            if not self._is_allowed(name, metadata.group, db_allow_deny):
                logger.debug(f"Processor '{name}' denied by config")
                continue

            if not self._is_enabled(name):
                logger.debug(f"Processor '{name}' disabled")
                continue

            processor_class = self.registry.get_processor_class(name)
            if processor_class:
                config = await self._get_builtin_config(name)
                try:
                    instance = processor_class(config=config)
                    processors.append(instance)
                    logger.info(f"Loaded processor builtin: {name}")
                except Exception as e:
                    logger.warning(f"Failed to load processor '{name}': {e}")

        return processors

    def load_processors(self) -> list[BaseBuiltinProcessor]:
        """Load all allowed and available processor builtins (synchronous, no database).

        A processor is available if either:
        - Its prerequisites are satisfied (env vars set), OR
        - Its config contains an api_key

        Returns:
            List of processor instances.

        Note:
            This is the synchronous version for backward compatibility.
            It does not check the database for API keys or allow/deny lists.
            Use load_processors_async() for full database integration.
        """
        if self.builtin_service is not None:
            logger.warning(
                "BuiltinLoader has database service but load_processors() was called "
                "synchronously. Database API keys and allow/deny lists will be ignored. "
                "Use load_processors_async() instead."
            )

        processors: list[BaseBuiltinProcessor] = []

        # Check all registered processors, not just those with satisfied prerequisites
        all_processors = self.registry.list_all()["processors"]
        for metadata in all_processors:
            name = metadata.name

            # Check if available via env vars OR config api_key
            if not metadata.prerequisites.is_satisfied() and not self._has_config_api_key_sync(name):
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
                config = self._get_builtin_config_sync(name)
                try:
                    instance = processor_class(config=config)
                    processors.append(instance)
                    logger.info(f"Loaded processor builtin: {name}")
                except Exception as e:
                    logger.warning(f"Failed to load processor '{name}': {e}")

        return processors
