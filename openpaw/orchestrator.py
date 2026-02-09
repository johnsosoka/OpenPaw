"""DEPRECATED: This module has moved to openpaw.runtime.orchestrator.

This shim provides backward compatibility. Update your imports to:
    from openpaw.runtime.orchestrator import OpenPawOrchestrator
"""

import warnings
from typing import Any

# Import from new location
from openpaw.runtime.orchestrator import OpenPawOrchestrator as _OpenPawOrchestrator

# Re-export for backward compatibility
OpenPawOrchestrator = _OpenPawOrchestrator

# Deprecation warning on module import
warnings.warn(
    "Importing from openpaw.orchestrator is deprecated. "
    "Use openpaw.runtime.orchestrator instead.",
    DeprecationWarning,
    stacklevel=2
)


def __getattr__(name: str) -> Any:
    """Provide deprecation warnings for attribute access."""
    if name == "OpenPawOrchestrator":
        warnings.warn(
            "Importing OpenPawOrchestrator from openpaw.orchestrator is deprecated. "
            "Use openpaw.runtime.orchestrator instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return _OpenPawOrchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["OpenPawOrchestrator"]
