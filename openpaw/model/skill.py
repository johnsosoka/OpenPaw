"""Domain models for agent skills."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


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
    """

    name: str
    description: str
    content: str
    path: Path
    inject: SkillInjectMode = SkillInjectMode.SUMMARY
    read_path: str = ""
    source: str = "workspace"
