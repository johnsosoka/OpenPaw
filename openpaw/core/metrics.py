"""Deprecated: Token usage tracking moved to openpaw.agent.metrics.

This module provides backward compatibility. Import from openpaw.agent instead:
    from openpaw.agent.metrics import InvocationMetrics, TokenUsageLogger
"""

import warnings
from typing import Any


def __getattr__(name: str) -> Any:
    """Lazy import with deprecation warning."""
    if name == "InvocationMetrics":
        warnings.warn(
            "Importing InvocationMetrics from openpaw.core.metrics is deprecated. "
            "Use 'from openpaw.agent.metrics import InvocationMetrics' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from openpaw.agent.metrics import InvocationMetrics as _InvocationMetrics

        return _InvocationMetrics

    if name == "extract_metrics_from_callback":
        warnings.warn(
            "Importing extract_metrics_from_callback from openpaw.core.metrics is deprecated. "
            "Use 'from openpaw.agent.metrics import extract_metrics_from_callback' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from openpaw.agent.metrics import extract_metrics_from_callback as _extract_metrics_from_callback

        return _extract_metrics_from_callback

    if name == "TokenUsageLogger":
        warnings.warn(
            "Importing TokenUsageLogger from openpaw.core.metrics is deprecated. "
            "Use 'from openpaw.agent.metrics import TokenUsageLogger' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from openpaw.agent.metrics import TokenUsageLogger as _TokenUsageLogger

        return _TokenUsageLogger

    if name == "TokenUsageReader":
        warnings.warn(
            "Importing TokenUsageReader from openpaw.core.metrics is deprecated. "
            "Use 'from openpaw.agent.metrics import TokenUsageReader' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from openpaw.agent.metrics import TokenUsageReader as _TokenUsageReader

        return _TokenUsageReader

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = []  # All exports via __getattr__
