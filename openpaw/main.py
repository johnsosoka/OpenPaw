"""Deprecated: WorkspaceRunner has moved to openpaw.workspace.runner.

This module is maintained for backward compatibility only.
Please update imports to use openpaw.workspace.runner.WorkspaceRunner instead.
"""

import warnings

# Re-export WorkspaceRunner from new location
from openpaw.workspace.runner import WorkspaceRunner

warnings.warn(
    "Importing WorkspaceRunner from openpaw.main is deprecated. "
    "Use 'from openpaw.workspace.runner import WorkspaceRunner' instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["WorkspaceRunner"]
