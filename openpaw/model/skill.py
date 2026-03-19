"""Domain models for agent skills."""

from dataclasses import dataclass
from pathlib import Path


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
    """

    name: str
    description: str
    content: str
    path: Path
