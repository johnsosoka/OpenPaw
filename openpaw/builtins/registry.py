"""Central registry for OpenPaw builtins."""

import logging
from typing import TYPE_CHECKING

from openpaw.builtins.base import BuiltinMetadata

if TYPE_CHECKING:
    from openpaw.builtins.base import BaseBuiltinProcessor, BaseBuiltinTool

logger = logging.getLogger(__name__)


class BuiltinRegistry:
    """Central registry of all available builtins.

    Supports:
    - Registration of tool and processor builtins
    - Lookup by name or group
    - Availability checking based on prerequisites

    This is a singleton - use get_instance() to access.
    """

    _instance: "BuiltinRegistry | None" = None

    def __init__(self) -> None:
        self._tools: dict[str, type[BaseBuiltinTool]] = {}
        self._processors: dict[str, type[BaseBuiltinProcessor]] = {}
        self._groups: dict[str, list[str]] = {}

    @classmethod
    def get_instance(cls) -> "BuiltinRegistry":
        """Get or create the singleton registry instance."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._register_defaults()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance. Useful for testing."""
        cls._instance = None

    def _register_defaults(self) -> None:
        """Register all built-in builtins.

        Uses lazy imports to avoid loading dependencies for unused builtins.
        """
        # Tools
        try:
            from openpaw.builtins.tools.brave_search import BraveSearchTool

            self.register_tool(BraveSearchTool)
        except ImportError as e:
            logger.debug(f"Brave Search not available: {e}")

        try:
            from openpaw.builtins.tools.elevenlabs_tts import ElevenLabsTTSTool

            self.register_tool(ElevenLabsTTSTool)
        except ImportError as e:
            logger.debug(f"ElevenLabs TTS not available: {e}")

        try:
            from openpaw.builtins.tools.shell import ShellToolBuiltin

            self.register_tool(ShellToolBuiltin)
        except ImportError as e:
            logger.debug(f"Shell tool not available: {e}")

        try:
            from openpaw.builtins.tools.cron import CronToolBuiltin

            self.register_tool(CronToolBuiltin)
        except ImportError as e:
            logger.debug(f"Cron tool not available: {e}")

        try:
            from openpaw.builtins.tools.task import TaskToolBuiltin

            self.register_tool(TaskToolBuiltin)
        except ImportError as e:
            logger.debug(f"Task tool not available: {e}")

        try:
            from openpaw.builtins.tools.send_message import SendMessageTool

            self.register_tool(SendMessageTool)
        except ImportError as e:
            logger.debug(f"Send message tool not available: {e}")

        try:
            from openpaw.builtins.tools.followup import FollowupTool

            self.register_tool(FollowupTool)
        except ImportError as e:
            logger.debug(f"Followup tool not available: {e}")

        try:
            from openpaw.builtins.tools.send_file import SendFileTool

            self.register_tool(SendFileTool)
        except ImportError as e:
            logger.debug(f"Send file tool not available: {e}")

        try:
            from openpaw.builtins.tools.spawn import SpawnToolBuiltin

            self.register_tool(SpawnToolBuiltin)
        except ImportError as e:
            logger.debug(f"Spawn tool not available: {e}")

        try:
            from openpaw.builtins.tools.plan import PlanToolBuiltin

            self.register_tool(PlanToolBuiltin)
        except ImportError as e:
            logger.debug(f"Plan tool not available: {e}")

        try:
            from openpaw.builtins.tools.browser import BrowserToolBuiltin

            self.register_tool(BrowserToolBuiltin)
        except ImportError as e:
            logger.debug(f"Browser tool not available: {e}")

        try:
            from openpaw.builtins.tools.memory_search import MemorySearchToolBuiltin

            self.register_tool(MemorySearchToolBuiltin)
        except ImportError as e:
            logger.debug(f"Memory search tool not available: {e}")

        # Processors (sorted by metadata.priority in BuiltinLoader.load_processors)
        try:
            from openpaw.builtins.processors.file_persistence import FilePersistenceProcessor

            self.register_processor(FilePersistenceProcessor)
        except ImportError as e:
            logger.debug(f"File persistence processor not available: {e}")

        try:
            from openpaw.builtins.processors.whisper import WhisperProcessor

            self.register_processor(WhisperProcessor)
        except ImportError as e:
            logger.debug(f"Whisper processor not available: {e}")

        try:
            from openpaw.builtins.processors.timestamp import TimestampProcessor

            self.register_processor(TimestampProcessor)
        except ImportError as e:
            logger.debug(f"Timestamp processor not available: {e}")

        try:
            from openpaw.builtins.processors.docling import DoclingProcessor

            self.register_processor(DoclingProcessor)
        except ImportError as e:
            logger.debug(f"Docling processor not available: {e}")

    def register_tool(self, tool_class: type["BaseBuiltinTool"]) -> None:
        """Register a tool builtin.

        Args:
            tool_class: The tool class to register.
        """
        meta = tool_class.metadata
        self._tools[meta.name] = tool_class
        if meta.group:
            self._groups.setdefault(meta.group, []).append(meta.name)
        logger.debug(f"Registered tool builtin: {meta.name}")

    def register_processor(self, processor_class: type["BaseBuiltinProcessor"]) -> None:
        """Register a processor builtin.

        Args:
            processor_class: The processor class to register.
        """
        meta = processor_class.metadata
        self._processors[meta.name] = processor_class
        if meta.group:
            self._groups.setdefault(meta.group, []).append(meta.name)
        logger.debug(f"Registered processor builtin: {meta.name}")

    def get_available_tools(self) -> dict[str, BuiltinMetadata]:
        """Get all tools with satisfied prerequisites.

        Returns:
            Dict mapping tool name to metadata for available tools.
        """
        return {
            name: cls.metadata
            for name, cls in self._tools.items()
            if cls.metadata.prerequisites.is_satisfied()
        }

    def get_available_processors(self) -> dict[str, BuiltinMetadata]:
        """Get all processors with satisfied prerequisites.

        Returns:
            Dict mapping processor name to metadata for available processors.
        """
        return {
            name: cls.metadata
            for name, cls in self._processors.items()
            if cls.metadata.prerequisites.is_satisfied()
        }

    def get_tool_class(self, name: str) -> type["BaseBuiltinTool"] | None:
        """Get a tool class by name.

        Args:
            name: The builtin name.

        Returns:
            The tool class or None if not found.
        """
        return self._tools.get(name)

    def get_processor_class(self, name: str) -> type["BaseBuiltinProcessor"] | None:
        """Get a processor class by name.

        Args:
            name: The builtin name.

        Returns:
            The processor class or None if not found.
        """
        return self._processors.get(name)

    def get_group_members(self, group: str) -> list[str]:
        """Get all builtin names in a group.

        Args:
            group: The group name (e.g., "web", "voice").

        Returns:
            List of builtin names in the group.
        """
        return self._groups.get(group, [])

    def list_all(self) -> dict[str, list[BuiltinMetadata]]:
        """List all registered builtins by type.

        Returns:
            Dict with "tools" and "processors" keys containing metadata lists.
        """
        return {
            "tools": [cls.metadata for cls in self._tools.values()],
            "processors": [cls.metadata for cls in self._processors.values()],
        }
