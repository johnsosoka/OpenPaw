"""Deprecated: Queue-aware middleware moved to openpaw.agent.middleware.queue_aware.

This module provides backward compatibility. Import from openpaw.agent.middleware instead:
    from openpaw.agent.middleware import QueueAwareToolMiddleware, InterruptSignalError
"""

import warnings
from typing import Any


def __getattr__(name: str) -> Any:
    """Lazy import with deprecation warning."""
    if name == "QueueAwareToolMiddleware":
        warnings.warn(
            "Importing QueueAwareToolMiddleware from openpaw.core.tool_middleware is deprecated. "
            "Use 'from openpaw.agent.middleware import QueueAwareToolMiddleware' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from openpaw.agent.middleware.queue_aware import QueueAwareToolMiddleware as _QueueAwareToolMiddleware

        return _QueueAwareToolMiddleware

    if name == "InterruptSignalError":
        warnings.warn(
            "Importing InterruptSignalError from openpaw.core.tool_middleware is deprecated. "
            "Use 'from openpaw.agent.middleware import InterruptSignalError' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from openpaw.agent.middleware.queue_aware import InterruptSignalError as _InterruptSignalError

        return _InterruptSignalError

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = []  # All exports via __getattr__
