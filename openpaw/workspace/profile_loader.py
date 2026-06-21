"""Spawn profile loader for workspace and system-level team profiles."""

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from openpaw.model.spawn_profile import SpawnProfile

logger = logging.getLogger(__name__)

_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Known YAML keys — used to emit forward-compat warnings on unrecognised fields.
_KNOWN_KEYS = {
    "name",
    "description",
    "system_prompt",
    "model",
    "temperature",
    "allowed_tools",
    "denied_tools",
    "allowed_skills",
    "denied_skills",
    "timeout_minutes",
    "max_turns",
    "inherit_tools",
}


def load_spawn_profiles(
    profiles_path: Path,
    source: str = "workspace",
) -> list[SpawnProfile]:
    """Load all spawn profiles from a directory.

    Supports two formats:
    1. Flat YAML files: agent/team/name.yaml or name.yml
    2. Profile directories: agent/team/name/profile.yaml (with optional tools/)

    When both a flat file and directory share the same stem, the directory
    takes precedence and a warning is logged.

    Scans ``profiles_path`` for ``*.yaml`` / ``*.yml`` files and subdirectories
    that contain a ``profile.yaml``. Files and directories whose names start
    with ``_`` are skipped (private/disabled convention).

    Each candidate is parsed independently — a malformed profile is logged and
    skipped so that one bad profile cannot prevent the rest from loading.

    Profile names are validated against the pattern ``^[a-z0-9][a-z0-9-]*$``.
    Invalid names are logged and skipped.

    Args:
        profiles_path: Absolute path to the directory containing profile files
            or profile subdirectories.
        source: Origin label attached to every loaded profile. Defaults to
            ``"workspace"``; pass ``"system"`` for built-in framework profiles.

    Returns:
        List of :class:`SpawnProfile` instances sorted by name. Returns an
        empty list if the directory does not exist or contains no valid profiles.
    """
    if not profiles_path.exists():
        logger.debug("Spawn profiles directory does not exist: %s", profiles_path)
        return []

    if not profiles_path.is_dir():
        logger.warning("Spawn profiles path is not a directory: %s", profiles_path)
        return []

    # Phase 1: Collect file candidates (.yaml/.yml, .yaml wins for same stem)
    file_candidates: dict[str, Path] = {}
    # Phase 2: Collect directory candidates (must contain profile.yaml)
    dir_candidates: dict[str, Path] = {}

    for entry in sorted(profiles_path.iterdir()):
        if entry.name.startswith("_"):
            continue

        if entry.is_file() and entry.suffix in {".yaml", ".yml"}:
            stem = entry.stem
            existing = file_candidates.get(stem)
            if existing is None or (entry.suffix == ".yaml" and existing.suffix == ".yml"):
                file_candidates[stem] = entry

        elif entry.is_dir():
            if (entry / "profile.yaml").exists():
                dir_candidates[entry.name] = entry
            else:
                logger.debug(
                    "Skipping directory '%s' in profiles path — no profile.yaml found",
                    entry.name,
                )

    # Phase 3: Merge — directories win over files on stem collision
    candidates: dict[str, tuple[str, Path]] = {}  # stem -> ("file"|"dir", path)

    for stem, path in file_candidates.items():
        if stem in dir_candidates:
            logger.warning(
                "Spawn profile '%s' exists as both file and directory — using directory",
                stem,
            )
        else:
            candidates[stem] = ("file", path)

    for stem, path in dir_candidates.items():
        candidates[stem] = ("dir", path)

    # Phase 4: Load each candidate
    profiles: list[SpawnProfile] = []

    for stem, (kind, path) in sorted(candidates.items()):
        try:
            if kind == "dir":
                profile = _load_directory_profile(path, source)
            else:
                profile = _load_profile(path, source)
        except Exception as exc:
            logger.error(
                "Failed to load spawn profile from %s: %s",
                path.name,
                exc,
            )
            continue

        if not _NAME_PATTERN.match(profile.name):
            logger.warning(
                "Spawn profile '%s' has an invalid name (must match %s) — skipping: %s",
                profile.name,
                _NAME_PATTERN.pattern,
                path.name,
            )
            continue

        profiles.append(profile)

    profiles.sort(key=lambda p: p.name)

    if profiles:
        logger.info(
            "Loaded %d spawn profile(s): %s",
            len(profiles),
            [p.name for p in profiles],
        )

    return profiles


def _load_directory_profile(profile_dir: Path, source: str) -> SpawnProfile:
    """Load a profile from a directory containing profile.yaml and optional tools/.

    Args:
        profile_dir: Path to the profile directory.
        source: Origin label.

    Returns:
        SpawnProfile with tools loaded from the tools/ subdirectory.

    Raises:
        FileNotFoundError: If profile.yaml is missing.
    """
    profile_yaml = profile_dir / "profile.yaml"
    if not profile_yaml.exists():
        raise FileNotFoundError(f"Missing profile.yaml in {profile_dir.name}/")

    profile = _load_profile(profile_yaml, source)

    # Load tools from the optional tools/ subdirectory
    tools_dir = profile_dir / "tools"
    if tools_dir.exists() and tools_dir.is_dir():
        from openpaw.workspace.tool_loader import load_workspace_tools

        workspace_root = _find_workspace_root(profile_dir)
        profile.tools = load_workspace_tools(
            tools_dir,
            workspace_root=workspace_root,
            auto_install=True,
        )
        if profile.tools:
            logger.info(
                "Loaded %d profile tool(s) for '%s': %s",
                len(profile.tools),
                profile.name,
                [t.name for t in profile.tools],
            )

    return profile


def _find_workspace_root(profile_dir: Path) -> Path:
    """Derive workspace root from a workspace-resident profile directory.

    Profile directories live at ``{workspace}/agent/team/{name}/``,
    so workspace root is 3 levels up from the profile dir.

    Note:
        Only valid for workspace-level profiles. System-level profiles
        (from ``team_profiles_path``) are always flat YAML — directory
        format with tools is not supported for system profiles.
    """
    return profile_dir.parent.parent.parent


def _load_profile(profile_path: Path, source: str) -> SpawnProfile:
    """Parse a single YAML profile file and return a :class:`SpawnProfile`.

    Args:
        profile_path: Absolute path to the ``.yaml`` / ``.yml`` file.
        source: Origin label to attach to the returned profile.

    Returns:
        Populated :class:`SpawnProfile` instance.

    Raises:
        yaml.YAMLError: If the file cannot be parsed as valid YAML.
        ValueError: If required coercions fail (e.g. temperature not numeric).
    """
    raw = profile_path.read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(raw) or {}

    unknown_keys = set(data) - _KNOWN_KEYS
    if unknown_keys:
        logger.warning(
            "Spawn profile %s contains unrecognised keys (ignored): %s",
            profile_path.name,
            sorted(unknown_keys),
        )

    name: str = str(data.get("name") or profile_path.stem)
    description: str = str(data.get("description") or "")

    # Optional scalar fields — coerce to the expected type or leave as None.
    model: str | None = _optional_str(data.get("model"))
    system_prompt: str | None = _optional_str(data.get("system_prompt"))
    temperature: float | None = _optional_float(data.get("temperature"), profile_path)
    timeout_minutes: int | None = _optional_int(data.get("timeout_minutes"), profile_path)
    max_turns: int | None = _optional_int(data.get("max_turns"), profile_path)
    inherit_tools: bool = _optional_bool(data.get("inherit_tools"), profile_path, default=True)

    # Optional list fields — accept a YAML sequence or None.
    allowed_tools: list[str] | None = _optional_str_list(data.get("allowed_tools"), profile_path)
    denied_tools: list[str] | None = _optional_str_list(data.get("denied_tools"), profile_path)
    allowed_skills: list[str] | None = _optional_str_list(data.get("allowed_skills"), profile_path)
    denied_skills: list[str] | None = _optional_str_list(data.get("denied_skills"), profile_path)

    return SpawnProfile(
        name=name,
        description=description,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
        allowed_tools=allowed_tools,
        denied_tools=denied_tools,
        allowed_skills=allowed_skills,
        denied_skills=denied_skills,
        timeout_minutes=timeout_minutes,
        max_turns=max_turns,
        inherit_tools=inherit_tools,
        source=source,
        path=profile_path,
    )


# ---------------------------------------------------------------------------
# Internal coercion helpers
# ---------------------------------------------------------------------------


def _optional_str(value: object) -> str | None:
    """Return a non-empty string or None."""
    if value is None:
        return None
    coerced = str(value).strip()
    return coerced if coerced else None


def _optional_float(value: object, source: Path) -> float | None:
    """Coerce *value* to float, logging a warning and returning None on failure."""
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        logger.warning(
            "Spawn profile %s: 'temperature' must be numeric — ignoring value %r",
            source.name,
            value,
        )
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning(
            "Spawn profile %s: 'temperature' must be numeric — ignoring value %r",
            source.name,
            value,
        )
        return None


def _optional_int(value: object, source: Path) -> int | None:
    """Coerce *value* to int, logging a warning and returning None on failure."""
    if value is None:
        return None
    if not isinstance(value, (str, int, float)):
        logger.warning(
            "Spawn profile %s: integer field received non-integer value %r — ignoring",
            source.name,
            value,
        )
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning(
            "Spawn profile %s: integer field received non-integer value %r — ignoring",
            source.name,
            value,
        )
        return None


def _optional_bool(value: object, source: Path, *, default: bool) -> bool:
    """Coerce *value* to bool, returning *default* if absent or invalid."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    logger.warning(
        "Spawn profile %s: 'inherit_tools' must be a boolean — using default %s",
        source.name,
        default,
    )
    return default


def _optional_str_list(value: object, source: Path) -> list[str] | None:
    """Coerce *value* to a list of strings, or None if absent.

    Accepts a YAML sequence (list) where each item is converted to a string.
    Logs a warning and returns None for non-list values.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        logger.warning(
            "Spawn profile %s: tool list field must be a YAML sequence — ignoring value %r",
            source.name,
            value,
        )
        return None
    return [str(item) for item in value]
