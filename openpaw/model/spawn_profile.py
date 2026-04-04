"""Domain models for spawn profiles."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SpawnProfile:
    """Represents a loaded spawn profile for configuring sub-agents.

    Spawn profiles are YAML documents that define reusable sub-agent
    configurations. They allow callers to spawn agents with a consistent
    set of overrides (model, tools, timeout, system prompt) without
    repeating those details on every spawn_agent call. Profiles are
    loaded from workspace profile directories and injected into the
    spawn builtin at startup.

    Attributes:
        name: Profile name used to reference the profile at spawn time
            (e.g., "news-scout", "code-reviewer").
        description: Short description of what this profile does and
            when it should be used.
        system_prompt: Optional text injected as a <team_role> block
            ahead of the workspace AGENT.md, scoping the sub-agent's
            identity without replacing the full system prompt.
        model: Optional model override for sub-agents using this profile
            (e.g., "anthropic:claude-haiku-4-5-20251001"). Falls back
            to the workspace configured model when None.
        temperature: Optional temperature override. Falls back to the
            workspace configured temperature when None.
        allowed_tools: Optional tool whitelist. Supports group: prefix
            (e.g., "group:search"). When set, only listed tools are
            available to the sub-agent.
        denied_tools: Optional tool blocklist. Supports group: prefix.
            Takes precedence over allowed_tools when both are set.
        allowed_skills: Optional skill whitelist by name. When set, only
            listed skills are injected into the sub-agent's system prompt.
            None means inherit all parent skills. Empty list means no skills.
        denied_skills: Optional skill blocklist by name. Removes matching
            skills from the sub-agent's system prompt.
        timeout_minutes: Default timeout in minutes for sub-agent runs
            using this profile. Falls back to the spawn builtin default
            when None.
        max_turns: Maximum number of LLM turns for sub-agents using
            this profile. Falls back to the workspace model config
            when None.
        source: Origin of this profile — "workspace" for profiles loaded
            from the workspace profiles directory, "system" for built-in
            framework profiles.
        path: Absolute path to the YAML file this profile was loaded
            from. Set by the loader; None for programmatically created
            profiles.
    """

    name: str
    description: str
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = None
    allowed_tools: list[str] | None = None
    denied_tools: list[str] | None = None
    allowed_skills: list[str] | None = None
    denied_skills: list[str] | None = None
    timeout_minutes: int | None = None
    max_turns: int | None = None
    source: str = "workspace"
    path: Path | None = None
