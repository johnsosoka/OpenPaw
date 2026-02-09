"""DEPRECATED: Sub-agent storage has moved to openpaw.stores.subagent.

This module provides backward compatibility shims. All new code should import from:
    from openpaw.stores.subagent import SubAgentStore, create_subagent_request
    from openpaw.domain.subagent import SubAgentRequest, SubAgentResult, SubAgentStatus
"""

import warnings
from typing import Any

# Re-export domain models (already deprecated from Phase 1)
# Re-export store classes from new location
from openpaw.stores.subagent import SubAgentStore as _SubAgentStore
from openpaw.stores.subagent import create_subagent_request as _create_subagent_request

# Re-export with deprecation
SubAgentStore = _SubAgentStore
create_subagent_request = _create_subagent_request


def __getattr__(name: str) -> Any:
    """Provide deprecation warnings for imports from this module."""
    if name == "SubAgentStore":
        warnings.warn(
            "Importing SubAgentStore from openpaw.subagent.store is deprecated. "
            "Use openpaw.stores.subagent instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return SubAgentStore
    elif name == "create_subagent_request":
        warnings.warn(
            "Importing create_subagent_request from openpaw.subagent.store is deprecated. "
            "Use openpaw.stores.subagent instead.",
            DeprecationWarning,
            stacklevel=2
        )
        return create_subagent_request
    elif name in ("SubAgentRequest", "SubAgentResult", "SubAgentStatus"):
        warnings.warn(
            f"Importing {name} from openpaw.subagent.store is deprecated. "
            "Use openpaw.domain.subagent instead.",
            DeprecationWarning,
            stacklevel=2
        )
        from openpaw.domain.subagent import SubAgentRequest, SubAgentResult, SubAgentStatus
        models = {
            "SubAgentRequest": SubAgentRequest,
            "SubAgentResult": SubAgentResult,
            "SubAgentStatus": SubAgentStatus,
        }
        return models[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
