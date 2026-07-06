"""Skill loader for workspace-defined agent skills."""

import logging
from pathlib import Path

from openpaw.core.skill_file import SKILL_FILENAME as _SKILL_FILENAME
from openpaw.core.skill_file import load_skill_file
from openpaw.model.skill import SkillInfo, SkillStatus

logger = logging.getLogger(__name__)


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
    - ``inject``, ``version``, ``created_by``, ``source``, ``updated_at``,
      ``status``: ADR-105 lifecycle keys, all optional and defaulted

    Any content after the frontmatter block (or the full file if no
    frontmatter is present) becomes the skill's ``content``.

    Skills with ``status: deprecated`` are skipped entirely (like the ``_``
    prefix). Skills with ``status: staged`` ARE returned — marked staged —
    so they appear in ``/skills``, but they are excluded from system-prompt
    injection by AgentWorkspace.

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
            skill = load_skill_file(skill_dir, skill_file)
            if skill.status is SkillStatus.DEPRECATED:
                logger.debug(f"Skipping deprecated skill: {skill_dir.name}")
                continue
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
            skill = load_skill_file(skill_dir, skill_file)
            if skill.status is SkillStatus.DEPRECATED:
                continue
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
