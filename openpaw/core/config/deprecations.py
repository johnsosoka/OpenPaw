"""Startup deprecation warnings for legacy config keys (PRD-003 S-A2).

Warnings fire once per key per process, at config load / workspace merge
time — never per message. Removal of the deprecated keys is targeted for 0.6.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openpaw.core.config.models.base import Config
    from openpaw.core.config.models.workspace import WorkspaceModelConfig

logger = logging.getLogger(__name__)

# Keys already warned about this process. Keyed by the full message so each
# distinct (key, workspace) pair warns exactly once.
_warned: set[str] = set()


def _warn_once(message: str) -> None:
    if message in _warned:
        return
    _warned.add(message)
    logger.warning(message)


def reset_warnings() -> None:
    """Clear the once-per-process guard. Intended for tests."""
    _warned.clear()


def warn_deprecated_global_keys(config: "Config") -> None:
    """Warn about deprecated keys in the global config.

    Currently: ``agent.api_key`` — credentials belong in the ``providers:``
    catalog instead.
    """
    if config.agent.api_key is not None:
        _warn_once(
            "Config key 'agent.api_key' is deprecated: move the credential to "
            "a 'providers:' catalog entry (providers.<name>.api_key) and "
            "reference the provider from workspace model config. "
            "Removal targeted for 0.6."
        )


# Workspace-only config groups that the global Config silently swallows
# (extra="allow") — placing them in config.yaml does nothing.
_WORKSPACE_ONLY_KEYS = ("harness", "learning")


def warn_misplaced_workspace_keys(raw_config: dict[str, object]) -> None:
    """Warn when workspace-only groups appear in the global config.

    ``harness:`` and ``learning:`` are workspace ``agent.yaml`` groups; the
    root Config model would swallow them silently (extra="allow"), defeating
    the fail-fast intent of their extra="forbid" schemas.
    """
    for key in _WORKSPACE_ONLY_KEYS:
        if key in raw_config:
            _warn_once(
                f"Config key '{key}:' in the global config.yaml has no effect — "
                f"it is a workspace-level setting; move it to the workspace's "
                f"config/agent.yaml."
            )


def warn_deprecated_workspace_model_keys(
    config: "Config",
    model_config: "WorkspaceModelConfig | None",
    workspace_name: str,
) -> None:
    """Warn about inline workspace model credentials when a catalog exists.

    Only fires when the global config defines a ``providers:`` catalog —
    without one, inline credentials remain the only option.
    """
    if not config.providers or model_config is None:
        return
    for key in ("api_key", "base_url", "region"):
        if getattr(model_config, key, None) is not None:
            _warn_once(
                f"Workspace '{workspace_name}': inline 'model.{key}' is "
                f"deprecated when a 'providers:' catalog is configured. Move "
                f"it to the catalog entry (providers.<name>.{key}) and "
                f"reference the provider by name. Removal targeted for 0.6."
            )
