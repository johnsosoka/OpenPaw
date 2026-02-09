"""Core functionality for OpenPaw.

Note: AgentRunner has moved to openpaw.agent.
Import from there for new code: from openpaw.agent import AgentRunner
"""

import warnings
from typing import Any

from openpaw.core.config import Config, load_config
from openpaw.core.queue import (
    Lane,
    LaneQueue,
    QueueItem,
    QueueManager,
    QueueMode,
    SessionQueue,
)
from openpaw.core.timezone import format_for_display, workspace_now

__all__ = [
    "Config",
    "load_config",
    "AgentRunner",
    "workspace_now",
    "format_for_display",
    "Lane",
    "LaneQueue",
    "QueueItem",
    "QueueManager",
    "QueueMode",
    "SessionQueue",
]


def __getattr__(name: str) -> Any:
    """Lazy import AgentRunner to avoid circular imports."""
    if name == "AgentRunner":
        warnings.warn(
            "Importing AgentRunner from openpaw.core is deprecated. "
            "Use 'from openpaw.agent import AgentRunner' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from openpaw.agent import AgentRunner as _AgentRunner

        return _AgentRunner

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
