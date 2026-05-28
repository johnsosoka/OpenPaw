"""Team roster builder for injection into the agent system prompt."""

from __future__ import annotations

from openpaw.workspace.profile_resolver import SpawnProfileResolver


class TeamRosterBuilder:
    """Builds a team roster string for the ``<team>`` prompt section."""

    def __init__(self, resolver: SpawnProfileResolver) -> None:
        """Initialize with a profile resolver.

        Args:
            resolver: Profile resolver with loaded team profiles.
        """
        self._resolver = resolver

    def build(self) -> str:
        """Build a team roster string for injection into the system prompt.

        Provides the agent with awareness of its available sub-agent team members,
        their roles, and dispatch guidance.

        Returns:
            Formatted team roster string for the ``<team>`` prompt section.
        """
        profiles = self._resolver.list_profiles()
        if not profiles:
            return ""

        lines = [
            "## Your Sub-Agent Team",
            "",
            "You have specialized sub-agent profiles available for delegation. "
            "Use `spawn_agent(profile='name', task='...')` to dispatch work. "
            "Sub-agents run in the background and notify you when complete.",
            "",
            "| Profile | Role | Model |",
            "|---------|------|-------|",
        ]

        for p in profiles:
            model = p.model or "(workspace default)"
            desc = p.description or "(no description)"
            lines.append(f"| `{p.name}` | {desc} | {model} |")

        lines.append("")
        lines.append("### Dispatch Guidelines")
        lines.append("")
        lines.append(
            "- **Delegate proactively** — when you recognize a task that fits "
            "a profile, spawn it without waiting to be asked"
        )
        lines.append(
            "- **Prefer profiles over manual tool filtering** — profiles carry "
            "focused prompts and tool restrictions tuned for their role"
        )
        lines.append(
            "- **Sub-agents are fire-and-forget** — you cannot send follow-up "
            "messages; write a thorough task prompt upfront"
        )
        lines.append(
            "- **Chain results** — one sub-agent's output (saved to workspace) "
            "can be input for another sub-agent or your own synthesis"
        )
        lines.append(
            "- **Use `list_team_profiles` for details** — see tool restrictions, "
            "timeouts, and skill configurations per profile"
        )

        return "\n".join(lines)
