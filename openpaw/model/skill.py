"""Domain models for agent skills."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class SkillStatus(StrEnum):
    """Skill lifecycle status (ADR-105).

    Attributes:
        ACTIVE: Loaded and injected into the system prompt.
        STAGED: Loaded into the skills list but NOT injected into the prompt;
            awaits ``/skills approve``.
        DEPRECATED: Skipped by the loader (like the ``_`` prefix) but kept
            on disk.
    """

    ACTIVE = "active"
    STAGED = "staged"
    DEPRECATED = "deprecated"


class SkillCreatedBy(StrEnum):
    """Provenance of a skill write (PRD-001 F4.2)."""

    HUMAN = "human"
    AGENT = "agent"
    MIDDLEWARE = "middleware"
    DREAM = "dream"


class SkillInjectMode(StrEnum):
    """Controls how a skill's content is injected into the system prompt.

    Attributes:
        FULL: Inject the complete skill content into every system prompt.
            Use for behavioral skills the agent must embody on every turn.
        SUMMARY: Inject only name, description, and a read_file() pointer.
            The agent loads the full content on demand. Default for new skills.
    """

    FULL = "full"
    SUMMARY = "summary"


@dataclass
class SkillInfo:
    """Represents a loaded skill from a workspace skills/ directory.

    Skills are markdown documents that inject reusable knowledge or behavioral
    patterns into the agent's system prompt. Each skill lives in its own
    subdirectory under agent/skills/ and is defined by a SKILL.md file with
    optional YAML frontmatter.

    Attributes:
        name: Skill name from frontmatter, or directory name as fallback.
        description: Short description from frontmatter (max 1024 chars).
            Empty string if no frontmatter is present.
        content: Full SKILL.md body content (after frontmatter is stripped).
        path: Absolute path to the skill's directory.
        inject: How this skill is rendered in the system prompt. FULL injects
            complete content on every invocation. SUMMARY injects only the
            name, description, and a read_file() pointer for on-demand access.
        read_path: Workspace-relative path for agent read_file() access
            (e.g., "agent/skills/my-skill/SKILL.md"). Computed by the loader.
        source: Origin of this skill — "workspace" for user-defined skills,
            "framework" for framework-bundled skills.
        version: Monotonic per-skill counter, bumped on every SkillStore
            update. Frontmatter key: ``version``.
        created_by: Provenance of the original write. Frontmatter key:
            ``created_by``.
        source_ref: Provenance reference (e.g. a session/conversation key).
            Frontmatter key: ``source`` — named ``source_ref`` here because
            ``source`` is already taken by the workspace/framework origin.
        updated_at: UTC timestamp of the last write, or None if the file has
            never been stamped. Frontmatter key: ``updated_at``.
        status: Lifecycle status (active | staged | deprecated). Frontmatter
            key: ``status``.
    """

    name: str
    description: str
    content: str
    path: Path
    inject: SkillInjectMode = SkillInjectMode.SUMMARY
    read_path: str = ""
    source: str = "workspace"
    version: int = 1
    created_by: SkillCreatedBy = SkillCreatedBy.HUMAN
    source_ref: str = ""
    updated_at: datetime | None = None
    status: SkillStatus = SkillStatus.ACTIVE
