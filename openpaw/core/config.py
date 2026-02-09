"""Configuration management for OpenPaw.

DEPRECATED: This module has been reorganized into openpaw.core.config/.
Imports from this module still work but will emit deprecation warnings.

New location:
- Models: openpaw.core.config.models
- Loaders: openpaw.core.config.loader
- Approval: openpaw.core.config.approval

All items are re-exported from openpaw.core.config for convenience.
"""

import warnings

# Re-export everything from the new location
from openpaw.core.config import *  # noqa: F401, F403
from openpaw.core.config import __all__  # noqa: F401

# Emit deprecation warning on module import
warnings.warn(
    "Importing from openpaw.core.config is deprecated. "
    "Use openpaw.core.config.models, openpaw.core.config.loader, "
    "or openpaw.core.config.approval for specific imports, "
    "or import from openpaw.core.config directly.",
    DeprecationWarning,
    stacklevel=2,
)
