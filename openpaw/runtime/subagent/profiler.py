"""Sub-agent profile resolution and runner configuration.

Encapsulates the logic for resolving spawn profiles, creating profiled agent
runners, injecting system prompts, filtering skills/tools, and configuring
timeout overrides.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from copy import copy
from typing import TYPE_CHECKING

from openpaw.agent import AgentRunner
from openpaw.model.spawn_profile import SpawnProfile
from openpaw.model.subagent import SubAgentRequest

from .filter import filter_subagent_tools

if TYPE_CHECKING:
    from openpaw.workspace.agent_factory import AgentFactory
    from openpaw.workspace.profile_resolver import SpawnProfileResolver

logger = logging.getLogger(__name__)


class ProfileNotFoundError(Exception):
    """Raised when a requested spawn profile cannot be found or resolved."""


class SubAgentProfiler:
    """Resolves spawn profiles and applies them to agent runners.

    Handles profile lookup, model override, workspace mutation, skill filtering,
    tool injection, tool filtering, and timeout configuration.
    """

    def __init__(
        self,
        profile_resolver: SpawnProfileResolver | None,
        agent_factory_instance: AgentFactory | None,
        workspace_name: str,
    ):
        """Initialize the profiler.

        Args:
            profile_resolver: Optional resolver for named spawn profiles.
            agent_factory_instance: Optional AgentFactory for creating profiled
                agents when model-level overrides are present.
            workspace_name: Workspace name for log labels.
        """
        self._profile_resolver = profile_resolver
        self._agent_factory_instance = agent_factory_instance
        self._workspace_name = workspace_name

    def resolve(self, profile_name: str) -> SpawnProfile:
        """Resolve a profile by name.

        Args:
            profile_name: The profile identifier to look up.

        Returns:
            The resolved SpawnProfile instance.

        Raises:
            ProfileNotFoundError: If no resolver is configured or the profile
                does not exist.
        """
        if self._profile_resolver is None:
            raise ProfileNotFoundError(
                f"Spawn profile '{profile_name}' requested but no profiles are configured"
            )
        profile = self._profile_resolver.resolve(profile_name)
        if profile is None:
            available = ", ".join(self._profile_resolver.list_profile_names()) or "none"
            raise ProfileNotFoundError(
                f"Spawn profile '{profile_name}' not found. "
                f"Available profiles: {available}"
            )
        return profile

    def setup(
        self,
        request: SubAgentRequest,
        agent_factory: Callable[[], AgentRunner],
    ) -> tuple[AgentRunner, float]:
        """Create and configure a runner for the given request.

        Args:
            request: The sub-agent request to configure for.
            agent_factory: Factory function that returns a fresh AgentRunner.

        Returns:
            A tuple of (configured_runner, effective_timeout_minutes).

        Raises:
            ProfileNotFoundError: If the request references a profile that
                cannot be resolved.
        """
        profile: SpawnProfile | None = None
        if request.profile:
            profile = self.resolve(request.profile)

        # Create agent — use profiled factory when profile has model-level overrides
        if profile and self._agent_factory_instance and (
            profile.model is not None
            or profile.temperature is not None
            or profile.max_turns is not None
        ):
            runner = self._agent_factory_instance.create_profiled_agent(profile)
        else:
            runner = agent_factory()

        # Inject sub-agent label so logs distinguish sub-agent from main agent.
        # Prefer profile name (e.g. "devin:homelab-specialist"), fall back to task label.
        sub_label = request.profile or request.label
        runner._log_label = f"{self._workspace_name}:{sub_label}"

        # --- Profile workspace overrides (prompt + skills) ---
        # Copy workspace before ANY mutation to avoid shared-state corruption.
        needs_copy = profile and (
            profile.system_prompt
            or profile.allowed_skills is not None
            or profile.denied_skills
        )
        if needs_copy:
            runner.workspace = copy(runner.workspace)

        if profile and profile.system_prompt:
            role_block = (
                f'<team_role profile="{profile.name}">\n'
                f"{profile.system_prompt.strip()}\n"
                f"</team_role>\n\n"
            )
            runner.workspace.agent_md = role_block + runner.workspace.agent_md

        # --- Profile skill filtering ---
        if profile and runner.workspace.skills:
            if profile.allowed_skills is not None:
                # Whitelist: only keep named skills (empty list = no skills)
                allowed = set(profile.allowed_skills)
                original_count = len(runner.workspace.skills)
                runner.workspace.skills = [
                    s for s in runner.workspace.skills if s.name in allowed
                ]
                filtered = original_count - len(runner.workspace.skills)
                if filtered > 0:
                    logger.debug(
                        f"Profile '{profile.name}' filtered {filtered} skill(s) "
                        f"via allowed_skills"
                    )
            if profile.denied_skills:
                # Blocklist: remove named skills
                denied = set(profile.denied_skills)
                runner.workspace.skills = [
                    s for s in runner.workspace.skills if s.name not in denied
                ]

        # --- Profile tool injection ---
        if profile:
            if not profile.inherit_tools:
                # Replace: sub-agent gets ONLY profile tools (no parent tools)
                parent_count = len(runner.additional_tools)
                runner.additional_tools = list(profile.tools)
                logger.debug(
                    "Profile '%s' inherit_tools=False: replaced %d parent tools "
                    "with %d profile tools",
                    profile.name,
                    parent_count,
                    len(profile.tools),
                )
                if not profile.tools:
                    logger.warning(
                        "Profile '%s' has inherit_tools=False but no profile tools "
                        "— sub-agent will have only filesystem tools",
                        profile.name,
                    )
            elif profile.tools:
                # Append: sub-agent gets parent tools + profile tools
                parent_names = {
                    getattr(t, "name", "") for t in runner.additional_tools
                }
                profile_names = {t.name for t in profile.tools}
                collisions = parent_names & profile_names
                if collisions:
                    logger.warning(
                        "Profile '%s' tools override parent tools with same name: %s",
                        profile.name,
                        sorted(collisions),
                    )
                    # Remove parent tools that are overridden by profile tools
                    runner.additional_tools = [
                        t for t in runner.additional_tools
                        if getattr(t, "name", "") not in collisions
                    ]
                runner.additional_tools = (
                    list(runner.additional_tools) + list(profile.tools)
                )
                logger.debug(
                    "Profile '%s': added %d profile tool(s) to %d parent tools",
                    profile.name,
                    len(profile.tools),
                    len(runner.additional_tools) - len(profile.tools),
                )

        # Filter tools — two-pass: profile restricts first, per-spawn second
        original_tool_count = len(runner.additional_tools)

        if profile and (profile.allowed_tools or profile.denied_tools):
            runner.additional_tools = filter_subagent_tools(
                runner.additional_tools,
                allowed_tools=profile.allowed_tools,
                denied_tools=profile.denied_tools,
            )

        runner.additional_tools = filter_subagent_tools(
            runner.additional_tools,
            allowed_tools=request.allowed_tools,
            denied_tools=request.denied_tools,
        )

        filtered_count = original_tool_count - len(runner.additional_tools)

        if filtered_count > 0:
            logger.debug(
                f"Filtered {filtered_count} tool(s) from sub-agent {request.id}"
            )

        # Rebuild agent with filtered tools
        runner._agent = runner._build_agent()

        # Apply timeout: prefer profile default when per-spawn is still the default (30)
        effective_timeout = request.timeout_minutes
        if profile and profile.timeout_minutes and request.timeout_minutes == 30:
            effective_timeout = profile.timeout_minutes

        # Override agent's internal timeout to defer to SubAgentRunner's
        # outer timeout. AgentRunner.run() catches TimeoutError internally
        # and returns a string, which would be misclassified as success.
        # By setting the inner timeout higher, only the outer fires.
        runner.timeout_seconds = (effective_timeout * 60) + 30

        return runner, effective_timeout
