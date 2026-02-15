"""Builtin auto-discovery for OpenPaw."""

import importlib
import inspect
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openpaw.builtins.base import BaseBuiltinProcessor, BaseBuiltinTool

logger = logging.getLogger(__name__)


def discover_builtins() -> tuple[
    dict[str, type["BaseBuiltinTool"]],
    dict[str, type["BaseBuiltinProcessor"]],
]:
    """Scan builtins/tools/ and builtins/processors/ for builtin classes.

    Returns:
        Tuple of (tools_dict, processors_dict) keyed by builtin name.
    """
    from openpaw.builtins.base import BaseBuiltinProcessor, BaseBuiltinTool

    tools: dict[str, type[BaseBuiltinTool]] = {}
    processors: dict[str, type[BaseBuiltinProcessor]] = {}

    builtins_dir = Path(__file__).parent

    # Scan tools/
    tools_dir = builtins_dir / "tools"
    for module_path in sorted(tools_dir.glob("*.py")):
        if module_path.name.startswith("_"):
            continue
        _scan_module(
            f"openpaw.builtins.tools.{module_path.stem}",
            BaseBuiltinTool,
            tools,
        )

    # Scan browser/ subdirectory
    browser_init = tools_dir / "browser" / "__init__.py"
    if browser_init.exists():
        _scan_module(
            "openpaw.builtins.tools.browser",
            BaseBuiltinTool,
            tools,
        )

    # Scan processors/
    processors_dir = builtins_dir / "processors"
    for module_path in sorted(processors_dir.glob("*.py")):
        if module_path.name.startswith("_"):
            continue
        _scan_module(
            f"openpaw.builtins.processors.{module_path.stem}",
            BaseBuiltinProcessor,
            processors,
        )

    logger.debug(
        f"Discovered {len(tools)} tools and {len(processors)} processors"
    )
    return tools, processors


def _scan_module(
    module_name: str,
    base_class: type,
    registry: dict[str, type],
) -> None:
    """Import a module and register any concrete subclasses of base_class."""
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        logger.debug(f"Skipping {module_name}: {e}")
        return
    except Exception as e:
        logger.warning(f"Error loading {module_name}: {e}")
        return

    for _attr_name, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, base_class)
            and obj is not base_class
            and hasattr(obj, "name")
            and isinstance(obj.name, str)
            and obj.__module__ == module.__name__  # Only classes defined in this module
        ):
            registry[obj.name] = obj
            logger.debug(f"Registered {base_class.__name__}: {obj.name}")


# Backward-compatible singleton API (used by loader)
class BuiltinRegistry:
    """Registry of discovered builtins. Singleton for backward compat."""

    _instance: "BuiltinRegistry | None" = None
    _tools: dict[str, type["BaseBuiltinTool"]]
    _processors: dict[str, type["BaseBuiltinProcessor"]]
    _groups: dict[str, list[str]]

    def __init__(self) -> None:
        self._tools, self._processors = discover_builtins()
        self._groups = self._build_groups()

    def _build_groups(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for name, cls in {**self._tools, **self._processors}.items():
            if cls.group:
                groups.setdefault(cls.group, []).append(name)
        return groups

    @classmethod
    def get_instance(cls) -> "BuiltinRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def get_tool_class(self, name: str) -> type["BaseBuiltinTool"] | None:
        return self._tools.get(name)

    def get_processor_class(self, name: str) -> type["BaseBuiltinProcessor"] | None:
        return self._processors.get(name)

    def get_group_members(self, group: str) -> list[str]:
        return self._groups.get(group, [])

    def list_all(self) -> dict[str, list[type]]:
        """List all registered builtin classes by type.

        Returns:
            Dict with "tools" and "processors" keys containing class lists.
        """
        return {
            "tools": list(self._tools.values()),
            "processors": list(self._processors.values()),
        }
