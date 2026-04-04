"""Spawn profile loader for workspace and system-level team profiles."""

import logging
import re
from pathlib import Path

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
}


def load_spawn_profiles(
    profiles_path: Path,
    source: str = "workspace",
) -> list[SpawnProfile]:
    """Load all spawn profiles from a directory of YAML files.

    Scans ``profiles_path`` for ``*.yaml`` and ``*.yml`` files. When both
    extensions exist for the same stem, ``*.yaml`` takes precedence. Files
    whose names start with ``_`` are skipped (private/disabled convention).

    Each file is parsed independently — a malformed file is logged and skipped
    so that one bad profile cannot prevent the rest from loading.

    Profile names are validated against the pattern ``^[a-z0-9][a-z0-9-]*$``.
    Files with invalid names are logged and skipped.

    Args:
        profiles_path: Absolute path to the directory containing profile files.
        source: Origin label attached to every loaded profile.  Defaults to
            ``"workspace"``; pass ``"system"`` for built-in framework profiles.

    Returns:
        List of :class:`SpawnProfile` instances sorted by name.  Returns an
        empty list if the directory does not exist or contains no valid files.
    """
    if not profiles_path.exists():
        logger.debug("Spawn profiles directory does not exist: %s", profiles_path)
        return []

    if not profiles_path.is_dir():
        logger.warning("Spawn profiles path is not a directory: %s", profiles_path)
        return []

    # Collect candidate files, letting .yaml win over .yml for the same stem.
    candidates: dict[str, Path] = {}
    for path in sorted(profiles_path.iterdir()):
        if path.suffix not in {".yaml", ".yml"}:
            continue
        stem = path.stem
        existing = candidates.get(stem)
        if existing is None or (path.suffix == ".yaml" and existing.suffix == ".yml"):
            candidates[stem] = path

    profiles: list[SpawnProfile] = []

    for stem, profile_path in sorted(candidates.items()):
        # Skip private/disabled profiles
        if stem.startswith("_"):
            continue

        try:
            profile = _load_profile(profile_path, source)
        except Exception as exc:
            logger.error(
                "Failed to load spawn profile from %s: %s",
                profile_path.name,
                exc,
            )
            continue

        if not _NAME_PATTERN.match(profile.name):
            logger.warning(
                "Spawn profile '%s' has an invalid name (must match %s) — skipping: %s",
                profile.name,
                _NAME_PATTERN.pattern,
                profile_path.name,
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
    data: dict = yaml.safe_load(raw) or {}

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
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning(
            "Spawn profile %s: integer field received non-integer value %r — ignoring",
            source.name,
            value,
        )
        return None


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
