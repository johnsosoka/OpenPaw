"""Skill loader for workspace-defined agent skills."""

import logging
from pathlib import Path
from typing import Any

import yaml

from openpaw.model.skill import SkillInfo, SkillInjectMode

logger = logging.getLogger(__name__)

_FRONTMATTER_DELIMITER = "---"
_MAX_DESCRIPTION_LENGTH = 1024
_SKILL_FILENAME = "SKILL.md"


def load_workspace_skills(
    skills_path: Path,
    errors: list[str] | None = None,
) -> list[SkillInfo]:
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
        errors: Optional list that per-skill load error messages are appended
            to, so callers can surface failures (broken skills are skipped
            regardless).

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
            if errors is not None:
                errors.append(f"Failed to load skill '{skill_dir.name}': {e}")
            continue

    if skills:
        skill_names = [s.name for s in skills]
        logger.info(f"Loaded {len(skills)} skills: {skill_names}")

    return skills


def load_framework_skills() -> list[SkillInfo]:
    """Load framework-bundled skills from the OpenPaw package.

    Framework skills provide reference documentation for framework capabilities
    (team management, web browsing, channel awareness). They are loaded from
    ``openpaw/builtins/skills/`` and merged with workspace skills at startup.

    Returns:
        List of SkillInfo instances with ``source="framework"``.
        Empty list if the directory doesn't exist.
    """
    framework_skills_dir = Path(__file__).resolve().parent.parent / "builtins" / "skills"

    if not framework_skills_dir.exists():
        logger.debug("Framework skills directory not found: %s", framework_skills_dir)
        return []

    skills: list[SkillInfo] = []

    for skill_dir in sorted(framework_skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        if skill_dir.name.startswith("_"):
            continue

        skill_file = skill_dir / _SKILL_FILENAME
        if not skill_file.exists():
            continue

        try:
            skill = _load_skill(skill_dir, skill_file)
            skill.source = "framework"
            # Framework skills are materialized into the workspace at startup,
            # so read_path points to the materialized location.
            skill.read_path = f"agent/skills/_framework/{skill_dir.name}/SKILL.md"
            skills.append(skill)
        except Exception as e:
            logger.error("Failed to load framework skill '%s': %s", skill_dir.name, e)
            continue

    if skills:
        logger.info(
            "Loaded %d framework skill(s): %s",
            len(skills),
            [s.name for s in skills],
        )

    return skills


def materialize_framework_skills(
    workspace_path: Path,
    skills: list[SkillInfo],
) -> None:
    """Write framework skill content into the workspace for agent read_file() access.

    Framework skills live in the Python package (outside the agent's sandbox).
    This function copies their SKILL.md content into the workspace at
    ``agent/skills/_framework/{name}/SKILL.md`` so agents can access them
    via ``read_file()``.

    The ``_framework`` prefix prevents the workspace skill loader from
    double-loading these files (underscore prefix convention).

    Args:
        workspace_path: Root path of the agent workspace.
        skills: Framework skills to materialize (only ``source="framework"`` are written).
    """
    for skill in skills:
        if skill.source != "framework":
            continue

        # Build full content with frontmatter
        target_dir = workspace_path / "agent" / "skills" / "_framework" / skill.name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / _SKILL_FILENAME

        # Write the original SKILL.md content (frontmatter + body)
        # Re-read from the source path to get the complete file
        source_file = skill.path / _SKILL_FILENAME
        if source_file.exists():
            content = source_file.read_text(encoding="utf-8")
        else:
            # Fallback: reconstruct from SkillInfo fields
            content = skill.content

        target_file.write_text(content, encoding="utf-8")

    framework_count = sum(1 for s in skills if s.source == "framework")
    if framework_count:
        logger.debug(
            "Materialized %d framework skill(s) into workspace", framework_count
        )


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

    # Parse inject mode from frontmatter
    raw_inject = frontmatter.get("inject")
    if raw_inject is None:
        inject = SkillInjectMode.SUMMARY
    else:
        raw_inject_str = str(raw_inject).strip().lower()
        try:
            inject = SkillInjectMode(raw_inject_str)
        except ValueError:
            logger.warning(
                "Skill '%s' has invalid inject mode '%s' — defaulting to summary",
                skill_dir.name,
                raw_inject,
            )
            inject = SkillInjectMode.SUMMARY

    # Compute read_path: workspace-relative path for agent read_file() access
    read_path = f"agent/skills/{skill_dir.name}/SKILL.md"

    return SkillInfo(
        name=name,
        description=description,
        content=content,
        path=skill_dir,
        inject=inject,
        read_path=read_path,
    )


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
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
