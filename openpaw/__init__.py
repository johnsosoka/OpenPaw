"""OpenPaw - AI Agent Framework with DeepAgents and Multi-Channel Support."""

import warnings

# langgraph's checkpoint serializer emits a PendingDeprecationWarning about the
# default value of `allowed_objects` from its own internal module, on every CLI
# invocation (issue #181). It is an upstream default we cannot pass through, so
# we filter it. langchain_core registers its own "default" filters for the
# LangChain* warning categories at import time, which would shadow ours, so we
# import that module first and then prepend our ignore filter above it.
try:
    import langchain_core._api.deprecation as _lc_deprecation  # noqa: F401
except Exception:  # pragma: no cover - langchain_core is a core dependency
    pass
warnings.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects` will change",
)

__version__ = "0.4.3"
__all__ = ["__version__"]
