"""SKILL.md file parsing shared by the skill loader and the SkillStore.

Lives in core/ so both workspace/skill_loader.py (loading) and
stores/skill.py (writing, which must re-read existing frontmatter) can use
one parser without an upward import (stability contract: stores/ may not
import from workspace/).
"""

import logging
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

import yaml

from openpaw.model.skill import SkillCreatedBy, SkillInfo, SkillInjectMode, SkillStatus

logger = logging.getLogger(__name__)

FRONTMATTER_DELIMITER = "---"
MAX_DESCRIPTION_LENGTH = 1024
SKILL_FILENAME = "SKILL.md"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and body content from a markdown string.

    Frontmatter is an optional YAML block at the very start of the file,
    enclosed between two ``---`` delimiter lines::

        ---
        name: my-skill
        description: Does something useful
        ---

        # Skill Content

    Args:
        text: Full file content to parse.

    Returns:
        A two-tuple of (frontmatter_dict, body_content). If no valid
        frontmatter block is present, returns ({}, original_text).
    """
    lines = text.split("\n")

    # Frontmatter must start on the very first line
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return {}, text

    # Find the closing delimiter
    try:
        closing_index = next(
            i for i, line in enumerate(lines[1:], start=1)
            if line.strip() == FRONTMATTER_DELIMITER
        )
    except StopIteration:
        # Opening delimiter found but no closing delimiter — treat as plain content
        return {}, text

    frontmatter_block = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1:]).lstrip("\n")

    try:
        parsed = yaml.safe_load(frontmatter_block) or {}
    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse frontmatter YAML: {e}")
        parsed = {}

    return parsed, body


def load_skill_file(skill_dir: Path, skill_file: Path) -> SkillInfo:
    """Parse a SKILL.md file and return a SkillInfo instance.

    All ADR-105 lifecycle keys (version, created_by, source, updated_at,
    status) are optional and defaulted, so files written before 0.5.0 parse
    unchanged.

    Args:
        skill_dir: Path to the skill's directory (used for name fallback).
        skill_file: Path to the SKILL.md file.

    Returns:
        Populated SkillInfo instance.
    """
    raw = skill_file.read_text(encoding="utf-8")
    frontmatter, content = parse_frontmatter(raw)

    name = str(frontmatter.get("name") or skill_dir.name)
    raw_description = str(frontmatter.get("description") or "")
    description = raw_description[:MAX_DESCRIPTION_LENGTH]
    inject = _parse_enum_field(
        frontmatter, "inject", SkillInjectMode, SkillInjectMode.SUMMARY, skill_dir.name
    )
    created_by = _parse_enum_field(
        frontmatter, "created_by", SkillCreatedBy, SkillCreatedBy.HUMAN, skill_dir.name
    )
    status = _parse_enum_field(
        frontmatter, "status", SkillStatus, SkillStatus.ACTIVE, skill_dir.name
    )

    # Compute read_path: workspace-relative path for agent read_file() access
    read_path = f"agent/skills/{skill_dir.name}/SKILL.md"

    return SkillInfo(
        name=name,
        description=description,
        content=content,
        path=skill_dir,
        inject=inject,
        read_path=read_path,
        version=_parse_version(frontmatter, skill_dir.name),
        created_by=created_by,
        source_ref=str(frontmatter.get("source") or ""),
        updated_at=_parse_updated_at(frontmatter, skill_dir.name),
        status=status,
    )


E = TypeVar("E", bound=StrEnum)


def _parse_enum_field(
    frontmatter: dict[str, Any],
    key: str,
    enum_type: type[E],
    default: E,
    skill_name: str,
) -> E:
    """Parse a StrEnum frontmatter value, falling back to a default."""
    raw = frontmatter.get(key)
    if raw is None:
        return default
    try:
        return enum_type(str(raw).strip().lower())
    except ValueError:
        logger.warning(
            "Skill '%s' has invalid %s '%s' — defaulting to %s",
            skill_name,
            key,
            raw,
            default.value,
        )
        return default


def _parse_version(frontmatter: dict[str, Any], skill_name: str) -> int:
    """Parse the version frontmatter key, defaulting to 1."""
    raw = frontmatter.get("version")
    if raw is None:
        return 1
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("Skill '%s' has invalid version '%s' — defaulting to 1", skill_name, raw)
        return 1


def _parse_updated_at(frontmatter: dict[str, Any], skill_name: str) -> datetime | None:
    """Parse the updated_at frontmatter key, defaulting to None."""
    raw = frontmatter.get("updated_at")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw  # yaml.safe_load parses ISO timestamps natively
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        logger.warning(
            "Skill '%s' has invalid updated_at '%s' — ignoring", skill_name, raw
        )
        return None
