"""Skill loader for workspace-defined agent skills."""

import logging
from pathlib import Path

import yaml

from openpaw.model.skill import SkillInfo

logger = logging.getLogger(__name__)

_FRONTMATTER_DELIMITER = "---"
_MAX_DESCRIPTION_LENGTH = 1024
_SKILL_FILENAME = "SKILL.md"


def load_workspace_skills(skills_path: Path) -> list[SkillInfo]:
    """Load all skills from a workspace's agent/skills/ directory.

    Scans for SKILL.md files in immediate subdirectories of skills_path.
    Each subdirectory represents one skill. Directories prefixed with ``_``
    are skipped (private/disabled convention).

    SKILL.md files may contain an optional YAML frontmatter block delimited
    by ``---`` lines at the start of the file. Recognized frontmatter keys:

    - ``name``: Skill display name (falls back to directory name)
    - ``description``: Short description (truncated to 1024 chars)

    Any content after the frontmatter block (or the full file if no
    frontmatter is present) becomes the skill's ``content``.

    Args:
        skills_path: Absolute path to the workspace's agent/skills/ directory.

    Returns:
        List of SkillInfo instances, sorted by directory name.
        Returns an empty list if the directory doesn't exist or is empty.
    """
    if not skills_path.exists():
        logger.debug(f"Skills directory does not exist: {skills_path}")
        return []

    if not skills_path.is_dir():
        logger.warning(f"Skills path is not a directory: {skills_path}")
        return []

    skills: list[SkillInfo] = []

    for skill_dir in sorted(skills_path.iterdir()):
        if not skill_dir.is_dir():
            continue

        # Skip private/disabled skill directories
        if skill_dir.name.startswith("_"):
            continue

        skill_file = skill_dir / _SKILL_FILENAME
        if not skill_file.exists():
            logger.debug(f"No {_SKILL_FILENAME} in skill directory: {skill_dir.name}")
            continue

        try:
            skill = _load_skill(skill_dir, skill_file)
            skills.append(skill)
        except Exception as e:
            logger.error(f"Failed to load skill from {skill_dir.name}: {e}")
            continue

    if skills:
        skill_names = [s.name for s in skills]
        logger.info(f"Loaded {len(skills)} skills: {skill_names}")

    return skills


def _load_skill(skill_dir: Path, skill_file: Path) -> SkillInfo:
    """Parse a SKILL.md file and return a SkillInfo instance.

    Args:
        skill_dir: Path to the skill's directory (used for name fallback).
        skill_file: Path to the SKILL.md file.

    Returns:
        Populated SkillInfo instance.
    """
    raw = skill_file.read_text(encoding="utf-8")
    frontmatter, content = _parse_frontmatter(raw)

    name = str(frontmatter.get("name") or skill_dir.name)
    raw_description = str(frontmatter.get("description") or "")
    description = raw_description[:_MAX_DESCRIPTION_LENGTH]

    return SkillInfo(
        name=name,
        description=description,
        content=content,
        path=skill_dir,
    )


def _parse_frontmatter(text: str) -> tuple[dict, str]:
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
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        return {}, text

    # Find the closing delimiter
    try:
        closing_index = next(
            i for i, line in enumerate(lines[1:], start=1)
            if line.strip() == _FRONTMATTER_DELIMITER
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
