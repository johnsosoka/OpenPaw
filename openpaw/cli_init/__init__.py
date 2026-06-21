"""CLI commands for workspace scaffolding: `openpaw init` and `openpaw list`.

Re-exports dispatch_command for backward compatibility.
"""

from .commands import dispatch_command

__all__ = ["dispatch_command"]
