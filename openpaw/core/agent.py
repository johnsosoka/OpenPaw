"""Deprecated: Agent runner moved to openpaw.agent.runner.

This module provides backward compatibility. Import from openpaw.agent instead:
    from openpaw.agent import AgentRunner
"""

import warnings
from typing import Any


def __getattr__(name: str) -> Any:
    """Lazy import with deprecation warning."""
    if name == "AgentRunner":
        warnings.warn(
            "Importing AgentRunner from openpaw.core.agent is deprecated. "
            "Use 'from openpaw.agent import AgentRunner' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from openpaw.agent.runner import AgentRunner as _AgentRunner

        return _AgentRunner

    if name == "THINKING_MODELS":
        warnings.warn(
            "Importing THINKING_MODELS from openpaw.core.agent is deprecated. "
            "Use 'from openpaw.agent.runner import THINKING_MODELS' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from openpaw.agent.runner import THINKING_MODELS as _THINKING_MODELS

        return _THINKING_MODELS

    if name == "BEDROCK_TOOL_NAME_PATTERN":
        warnings.warn(
            "Importing BEDROCK_TOOL_NAME_PATTERN from openpaw.core.agent is deprecated. "
            "Use 'from openpaw.agent.runner import BEDROCK_TOOL_NAME_PATTERN' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from openpaw.agent.runner import BEDROCK_TOOL_NAME_PATTERN as _BEDROCK_TOOL_NAME_PATTERN

        return _BEDROCK_TOOL_NAME_PATTERN

    if name == "MAX_TOOL_NAME_LENGTH":
        warnings.warn(
            "Importing MAX_TOOL_NAME_LENGTH from openpaw.core.agent is deprecated. "
            "Use 'from openpaw.agent.runner import MAX_TOOL_NAME_LENGTH' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from openpaw.agent.runner import MAX_TOOL_NAME_LENGTH as _MAX_TOOL_NAME_LENGTH

        return _MAX_TOOL_NAME_LENGTH

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = []  # All exports via __getattr__
