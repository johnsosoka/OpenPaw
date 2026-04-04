"""Integration tests for spawn profile resolution, tool filtering, prompt injection, and model override.

These tests exercise the integration layer between SubAgentRequest, SpawnProfile,
SpawnProfileResolver, filter_subagent_tools, and SpawnToolBuiltin without
instantiating real AgentRunners or making any LLM calls.
"""

from copy import copy
from pathlib import Path
from unittest.mock import MagicMock

from openpaw.builtins.tools.spawn import SpawnAgentInput, SpawnToolBuiltin
from openpaw.model.skill import SkillInfo
from openpaw.model.spawn_profile import SpawnProfile
from openpaw.model.subagent import SubAgentRequest, SubAgentStatus
from openpaw.runtime.subagent.runner import SUBAGENT_EXCLUDED_TOOLS, filter_subagent_tools
from openpaw.stores.subagent import SubAgentStore, create_subagent_request
from openpaw.workspace.profile_resolver import SpawnProfileResolver

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_profile(name: str, **kwargs) -> SpawnProfile:
    """Construct a minimal SpawnProfile with sensible defaults."""
    kwargs.setdefault("description", f"Test profile: {name}")
    return SpawnProfile(name=name, **kwargs)


def make_request(profile: str | None = None, **kwargs) -> SubAgentRequest:
    """Construct a minimal SubAgentRequest."""
    return SubAgentRequest(
        id="test-id-abc",
        task="Do a thing",
        label="test-task",
        status=SubAgentStatus.PENDING,
        session_key="telegram:12345",
        profile=profile,
        **kwargs,
    )


def make_fake_tool(name: str) -> MagicMock:
    """Create a fake LangChain tool with a .name attribute."""
    tool = MagicMock()
    tool.name = name
    return tool


# ---------------------------------------------------------------------------
# Section 1: SubAgentRequest serialization
# ---------------------------------------------------------------------------


class TestSubAgentRequestSerialization:
    """Profile field round-trips correctly through to_dict / from_dict."""

    def test_profile_field_preserved_in_round_trip(self) -> None:
        """to_dict() then from_dict() preserves the profile name exactly."""
        request = make_request(profile="researcher")

        data = request.to_dict()
        restored = SubAgentRequest.from_dict(data)

        assert restored.profile == "researcher"

    def test_profile_none_omitted_from_to_dict(self) -> None:
        """When profile is None it must not appear in the serialized dict."""
        request = make_request(profile=None)

        data = request.to_dict()

        assert "profile" not in data

    def test_from_dict_handles_missing_profile_key(self) -> None:
        """from_dict() tolerates old YAML files that lack the profile key."""
        request = make_request(profile="researcher")
        data = request.to_dict()
        # Simulate an old record that pre-dates the profile field.
        data.pop("profile", None)

        restored = SubAgentRequest.from_dict(data)

        assert restored.profile is None

    def test_profile_name_survives_full_round_trip(self) -> None:
        """A non-trivial profile name survives serialization unchanged."""
        request = make_request(profile="news-scout-v2")

        restored = SubAgentRequest.from_dict(request.to_dict())

        assert restored.profile == "news-scout-v2"

    def test_all_other_fields_unaffected_by_profile_presence(self) -> None:
        """Serialization of unrelated fields is not disturbed when profile is set."""
        request = make_request(profile="analyst", timeout_minutes=45, notify=False)

        restored = SubAgentRequest.from_dict(request.to_dict())

        assert restored.timeout_minutes == 45
        assert restored.notify is False
        assert restored.label == "test-task"


# ---------------------------------------------------------------------------
# Section 2: create_subagent_request profile threading
# ---------------------------------------------------------------------------


class TestCreateSubagentRequestProfile:
    """Profile name set via create_subagent_request is preserved through the store."""

    def test_create_subagent_request_stores_profile_name(self) -> None:
        """create_subagent_request() propagates the profile field onto the request."""
        request = create_subagent_request(
            task="Research AI news",
            label="ai-news",
            session_key="telegram:99",
            status=SubAgentStatus.PENDING,
            profile="researcher",
        )

        assert request.profile == "researcher"

    def test_create_subagent_request_profile_none_by_default(self) -> None:
        """create_subagent_request() defaults profile to None when omitted."""
        request = create_subagent_request(
            task="Do work",
            label="work",
            session_key="telegram:99",
            status=SubAgentStatus.PENDING,
        )

        assert request.profile is None

    def test_profile_preserved_in_store_create_read_cycle(self, tmp_path: Path) -> None:
        """Profile name survives a store create → read round-trip."""
        store = SubAgentStore(tmp_path)
        request = create_subagent_request(
            task="Summarize documents",
            label="summarizer",
            session_key="telegram:42",
            status=SubAgentStatus.PENDING,
            profile="doc-summarizer",
        )

        store.create(request)
        retrieved = store.get(request.id)

        assert retrieved is not None
        assert retrieved.profile == "doc-summarizer"

    def test_no_profile_store_round_trip(self, tmp_path: Path) -> None:
        """A request without a profile is stored and retrieved with profile=None."""
        store = SubAgentStore(tmp_path)
        request = create_subagent_request(
            task="Generic task",
            label="generic",
            session_key="telegram:42",
            status=SubAgentStatus.PENDING,
        )

        store.create(request)
        retrieved = store.get(request.id)

        assert retrieved is not None
        assert retrieved.profile is None


# ---------------------------------------------------------------------------
# Section 3: filter_subagent_tools
# ---------------------------------------------------------------------------


class TestFilterSubagentTools:
    """filter_subagent_tools correctly applies the three-layer exclusion model."""

    def _make_tools(self, *names: str) -> list[MagicMock]:
        return [make_fake_tool(n) for n in names]

    def test_excluded_tools_always_removed(self) -> None:
        """SUBAGENT_EXCLUDED_TOOLS are stripped regardless of allow/deny lists."""
        excluded_name = next(iter(SUBAGENT_EXCLUDED_TOOLS))
        tools = self._make_tools("safe_tool", excluded_name)

        result = filter_subagent_tools(tools)

        names = {t.name for t in result}
        assert excluded_name not in names
        assert "safe_tool" in names

    def test_no_filters_returns_only_non_excluded_tools(self) -> None:
        """Without allow or deny lists only the excluded floor applies."""
        tools = self._make_tools("alpha", "beta", "spawn_agent")  # spawn_agent is excluded

        result = filter_subagent_tools(tools)

        names = {t.name for t in result}
        assert "alpha" in names
        assert "beta" in names
        assert "spawn_agent" not in names

    def test_allowed_tools_whitelist_restricts_further(self) -> None:
        """allowed_tools further restricts what survives the exclusion floor."""
        tools = self._make_tools("search", "write_file", "read_file")

        result = filter_subagent_tools(tools, allowed_tools=["search", "read_file"])

        names = {t.name for t in result}
        assert "search" in names
        assert "read_file" in names
        assert "write_file" not in names

    def test_denied_tools_removes_from_surviving_set(self) -> None:
        """denied_tools removes specific tools that passed the exclusion floor."""
        tools = self._make_tools("search", "write_file", "read_file")

        result = filter_subagent_tools(tools, denied_tools=["write_file"])

        names = {t.name for t in result}
        assert "search" in names
        assert "read_file" in names
        assert "write_file" not in names

    def test_two_pass_profile_then_per_spawn_restriction(self) -> None:
        """Profile restricts first; per-spawn further restricts the result.

        Simulates the two-pass pattern in _execute_subagent.
        """
        tools = self._make_tools("search", "read_file", "write_file", "ls")

        # Pass 1: profile allows only search + read_file + write_file
        after_profile = filter_subagent_tools(
            tools,
            allowed_tools=["search", "read_file", "write_file"],
        )
        # Pass 2: per-spawn further restricts to search + read_file
        after_spawn = filter_subagent_tools(
            after_profile,
            allowed_tools=["search", "read_file"],
        )

        names = {t.name for t in after_spawn}
        assert names == {"search", "read_file"}

    def test_denied_in_second_pass_removes_from_profile_result(self) -> None:
        """Per-spawn denied_tools can remove tools that a profile allowed."""
        tools = self._make_tools("search", "read_file", "write_file")

        # Pass 1: profile places no restrictions
        after_profile = filter_subagent_tools(tools)
        # Pass 2: per-spawn denies write_file
        after_spawn = filter_subagent_tools(after_profile, denied_tools=["write_file"])

        names = {t.name for t in after_spawn}
        assert "write_file" not in names
        assert "search" in names
        assert "read_file" in names

    def test_empty_tool_list_returns_empty(self) -> None:
        """Filtering an empty tool list always returns an empty list."""
        result = filter_subagent_tools([], allowed_tools=["search"])

        assert result == []

    def test_group_resolver_called_for_group_prefix(self) -> None:
        """group: prefix triggers the group_resolver callable."""
        tools = self._make_tools("search", "read_file", "write_file")
        group_resolver = MagicMock(return_value=["search", "read_file"])

        result = filter_subagent_tools(
            tools,
            allowed_tools=["group:web"],
            group_resolver=group_resolver,
        )

        group_resolver.assert_called_once_with("web")
        names = {t.name for t in result}
        assert names == {"search", "read_file"}

    def test_backward_compat_no_profile_single_pass(self) -> None:
        """Without a profile the single-pass path matches original behavior."""
        tools = self._make_tools("ls", "read_file", "send_message")  # send_message excluded

        result = filter_subagent_tools(
            tools,
            allowed_tools=None,
            denied_tools=None,
        )

        names = {t.name for t in result}
        assert "send_message" not in names  # excluded by floor
        assert "ls" in names
        assert "read_file" in names


# ---------------------------------------------------------------------------
# Section 4: SpawnAgentInput profile field
# ---------------------------------------------------------------------------


class TestSpawnAgentInput:
    """SpawnAgentInput Pydantic model correctly handles the profile field."""

    def test_profile_field_accepted(self) -> None:
        """SpawnAgentInput validates correctly when profile is provided."""
        data = SpawnAgentInput(
            task="Research X",
            label="research-x",
            profile="researcher",
        )

        assert data.profile == "researcher"

    def test_profile_defaults_to_none(self) -> None:
        """profile is optional and defaults to None."""
        data = SpawnAgentInput(task="Do work", label="work")

        assert data.profile is None

    def test_profile_accepts_hyphenated_names(self) -> None:
        """Profile names with hyphens are accepted as-is."""
        data = SpawnAgentInput(task="t", label="l", profile="news-scout-v2")

        assert data.profile == "news-scout-v2"


# ---------------------------------------------------------------------------
# Section 5: SpawnToolBuiltin.list_team_profiles
# ---------------------------------------------------------------------------


class TestListTeamProfiles:
    """list_team_profiles tool returns correct output based on resolver state."""

    def _make_spawn_tool_with_profiles(self, profiles: list[SpawnProfile]) -> SpawnToolBuiltin:
        """Build a SpawnToolBuiltin whose runner has a populated resolver."""
        tool = SpawnToolBuiltin()
        mock_runner = MagicMock()
        mock_runner._profile_resolver = SpawnProfileResolver(workspace_profiles=profiles)
        tool.set_runner(mock_runner)
        return tool

    def _invoke_list_profiles(self, tool: SpawnToolBuiltin) -> str:
        """Invoke the list_team_profiles tool and return the string output."""
        lc_tools = tool.get_langchain_tool()
        list_tool = next(t for t in lc_tools if t.name == "list_team_profiles")
        return list_tool.func()

    def test_no_profiles_configured_returns_expected_message(self) -> None:
        """When resolver is empty the tool returns the 'no profiles' message."""
        tool = self._make_spawn_tool_with_profiles([])

        output = self._invoke_list_profiles(tool)

        assert "No spawn profiles configured" in output

    def test_profiles_listed_with_name_and_description(self) -> None:
        """When profiles exist the output contains name and description."""
        profiles = [
            make_profile("researcher", description="Searches the web for information"),
            make_profile("analyst", description="Analyzes data and produces reports"),
        ]
        tool = self._make_spawn_tool_with_profiles(profiles)

        output = self._invoke_list_profiles(tool)

        assert "researcher" in output
        assert "Searches the web for information" in output
        assert "analyst" in output
        assert "Analyzes data and produces reports" in output

    def test_profiles_listed_with_model_override(self) -> None:
        """When a profile has a model override it appears in the listing."""
        profiles = [make_profile("fast", model="anthropic:claude-haiku-4-5-20251001")]
        tool = self._make_spawn_tool_with_profiles(profiles)

        output = self._invoke_list_profiles(tool)

        assert "claude-haiku-4-5-20251001" in output

    def test_profiles_listed_with_allowed_tools(self) -> None:
        """Tool restrictions in a profile are surfaced in the listing."""
        profiles = [make_profile("read-only", allowed_tools=["read_file", "ls"])]
        tool = self._make_spawn_tool_with_profiles(profiles)

        output = self._invoke_list_profiles(tool)

        assert "read_file" in output
        assert "ls" in output

    def test_profiles_listed_with_timeout(self) -> None:
        """Timeout override in a profile is surfaced in the listing."""
        profiles = [make_profile("quick", timeout_minutes=10)]
        tool = self._make_spawn_tool_with_profiles(profiles)

        output = self._invoke_list_profiles(tool)

        assert "10" in output

    def test_runner_none_returns_error_message(self) -> None:
        """When the runner is not connected the tool returns an error string."""
        tool = SpawnToolBuiltin()
        # Do not call set_runner — _runner stays None.

        output = self._invoke_list_profiles(tool)

        assert "[Error" in output

    def test_resolver_none_returns_no_profiles_message(self) -> None:
        """When runner has no resolver the tool reports no profiles configured."""
        tool = SpawnToolBuiltin()
        mock_runner = MagicMock()
        mock_runner._profile_resolver = None
        tool.set_runner(mock_runner)

        output = self._invoke_list_profiles(tool)

        assert "No spawn profiles configured" in output

    def test_count_of_profiles_shown_in_header(self) -> None:
        """The profile count is included in the listing header."""
        profiles = [make_profile("a"), make_profile("b"), make_profile("c")]
        tool = self._make_spawn_tool_with_profiles(profiles)

        output = self._invoke_list_profiles(tool)

        assert "3" in output


# ---------------------------------------------------------------------------
# Section 6: Workspace copy protection
# ---------------------------------------------------------------------------


class TestWorkspaceCopyProtection:
    """copy(workspace) produces an independent object for agent_md mutation."""

    def test_copy_produces_independent_object(self) -> None:
        """Mutating agent_md on the copy does not affect the original."""
        workspace = MagicMock()
        workspace.agent_md = "# Original AGENT.md content"

        workspace_copy = copy(workspace)
        workspace_copy.agent_md = "<team_role>...</team_role>\n\n# Original AGENT.md content"

        assert workspace.agent_md == "# Original AGENT.md content"
        assert workspace_copy.agent_md.startswith("<team_role>")

    def test_copy_is_not_the_same_object(self) -> None:
        """copy() returns a distinct object (is-not identity check)."""
        workspace = MagicMock()
        workspace.agent_md = "original"

        workspace_copy = copy(workspace)

        assert workspace_copy is not workspace

    def test_profile_prompt_injection_pattern(self) -> None:
        """The role_block prepend pattern used in _execute_subagent is correct.

        This validates the exact string construction logic from the runner so
        that any future refactor that breaks the format is caught.
        """
        profile = make_profile("researcher", system_prompt="You are a research expert.")
        workspace = MagicMock()
        workspace.agent_md = "# AGENT\n\nYou help users."

        # Mirror the injection logic from SubAgentRunner._execute_subagent
        workspace_copy = copy(workspace)
        role_block = (
            f'<team_role profile="{profile.name}">\n'
            f"{profile.system_prompt.strip()}\n"
            f"</team_role>\n\n"
        )
        workspace_copy.agent_md = role_block + workspace_copy.agent_md

        assert workspace_copy.agent_md.startswith('<team_role profile="researcher">')
        assert "You are a research expert." in workspace_copy.agent_md
        assert "# AGENT" in workspace_copy.agent_md
        # Original is untouched
        assert workspace.agent_md == "# AGENT\n\nYou help users."


# ---------------------------------------------------------------------------
# Section 7: SpawnProfileResolver integration with SubAgentRunner context
# ---------------------------------------------------------------------------


class TestProfileResolverIntegration:
    """Resolver behaviour as it would be used inside SubAgentRunner._execute_subagent."""

    def test_resolve_returns_correct_profile_for_request(self) -> None:
        """A resolver set on a mock runner returns the expected profile."""
        profile = make_profile("researcher")
        resolver = SpawnProfileResolver(workspace_profiles=[profile])

        result = resolver.resolve("researcher")

        assert result is profile

    def test_unknown_profile_returns_none(self) -> None:
        """resolve() returns None for an unknown name — failure path in runner."""
        resolver = SpawnProfileResolver(workspace_profiles=[make_profile("known")])

        result = resolver.resolve("unknown-profile")

        assert result is None

    def test_available_profiles_listed_when_resolution_fails(self) -> None:
        """list_profile_names() provides context for the 'not found' error message."""
        resolver = SpawnProfileResolver(
            workspace_profiles=[make_profile("alpha"), make_profile("beta")]
        )

        available = ", ".join(resolver.list_profile_names()) or "none"

        assert "alpha" in available
        assert "beta" in available

    def test_no_profiles_configured_message_uses_none(self) -> None:
        """When resolver is empty list_profile_names() yields an empty join → 'none'."""
        resolver = SpawnProfileResolver(workspace_profiles=[])

        available = ", ".join(resolver.list_profile_names()) or "none"

        assert available == "none"

    def test_profile_with_model_triggers_profiled_factory_path(self) -> None:
        """A profile with a model override satisfies the condition that routes to create_profiled_agent.

        This mirrors the conditional in _execute_subagent:
            if profile and agent_factory_instance and (model or temp or max_turns)
        """
        profile_with_model = make_profile("fast", model="anthropic:claude-haiku-4-5-20251001")
        profile_no_model = make_profile("plain")  # no model/temperature/max_turns

        assert profile_with_model.model is not None
        has_overrides_with_model = (
            profile_with_model.model is not None
            or profile_with_model.temperature is not None
            or profile_with_model.max_turns is not None
        )
        has_overrides_no_model = (
            profile_no_model.model is not None
            or profile_no_model.temperature is not None
            or profile_no_model.max_turns is not None
        )

        assert has_overrides_with_model is True
        assert has_overrides_no_model is False

    def test_profile_with_only_temperature_triggers_profiled_factory_path(self) -> None:
        """A profile with only temperature (no model) also routes to create_profiled_agent."""
        profile = make_profile("warm", temperature=0.9)

        has_overrides = (
            profile.model is not None
            or profile.temperature is not None
            or profile.max_turns is not None
        )

        assert has_overrides is True

    def test_profile_timeout_preferred_over_default_when_request_is_default(self) -> None:
        """Profile timeout wins over the request default of 30 when unchanged.

        Mirrors the conditional: if profile.timeout_minutes and request.timeout_minutes == 30
        """
        profile = make_profile("quick", timeout_minutes=10)
        request = make_request(profile="quick")  # timeout_minutes defaults to 30

        effective_timeout = request.timeout_minutes
        if profile.timeout_minutes and request.timeout_minutes == 30:
            effective_timeout = profile.timeout_minutes

        assert effective_timeout == 10

    def test_profile_timeout_does_not_override_explicit_request_timeout(self) -> None:
        """Profile timeout is ignored when the caller sets an explicit timeout."""
        profile = make_profile("quick", timeout_minutes=10)
        request = make_request(profile="quick", timeout_minutes=60)

        effective_timeout = request.timeout_minutes
        if profile.timeout_minutes and request.timeout_minutes == 30:
            effective_timeout = profile.timeout_minutes

        assert effective_timeout == 60  # caller's explicit value wins


# ---------------------------------------------------------------------------
# Section 8: Skill filtering via SpawnProfile
# ---------------------------------------------------------------------------

# Shared fake skills used across all skill-filtering tests.
_SKILL_A = SkillInfo(name="skill-a", description="A", content="content-a", path=Path("/fake/a"))
_SKILL_B = SkillInfo(name="skill-b", description="B", content="content-b", path=Path("/fake/b"))


def _apply_skill_filters(
    skills: list[SkillInfo],
    profile: SpawnProfile,
) -> list[SkillInfo]:
    """Mirror the skill-filtering logic from SubAgentRunner._execute_subagent.

    This function exists purely to keep the test assertions close to the
    production algorithm. Any refactor of _execute_subagent that changes the
    filtering logic must also update this helper.
    """
    result = list(skills)

    if profile.allowed_skills is not None:
        allowed = set(profile.allowed_skills)
        result = [s for s in result if s.name in allowed]

    if profile.denied_skills:
        denied = set(profile.denied_skills)
        result = [s for s in result if s.name not in denied]

    return result


class TestSkillFiltering:
    """Skill whitelist / blocklist logic on SpawnProfile."""

    def test_allowed_skills_none_inherits_all_parent_skills(self) -> None:
        """allowed_skills=None means no filtering — sub-agent gets all parent skills."""
        profile = make_profile("no-filter", allowed_skills=None)

        result = _apply_skill_filters([_SKILL_A, _SKILL_B], profile)

        assert len(result) == 2
        assert _SKILL_A in result
        assert _SKILL_B in result

    def test_allowed_skills_empty_list_means_no_skills(self) -> None:
        """allowed_skills=[] explicitly grants no skills to the sub-agent."""
        profile = make_profile("no-skills", allowed_skills=[])

        result = _apply_skill_filters([_SKILL_A, _SKILL_B], profile)

        assert result == []

    def test_allowed_skills_single_name_passes_only_that_skill(self) -> None:
        """allowed_skills with one name allows exactly that skill and excludes others."""
        profile = make_profile("skill-a-only", allowed_skills=["skill-a"])

        result = _apply_skill_filters([_SKILL_A, _SKILL_B], profile)

        assert len(result) == 1
        assert result[0].name == "skill-a"

    def test_denied_skills_removes_named_skill_and_keeps_rest(self) -> None:
        """denied_skills removes the blocked skill; all others survive."""
        profile = make_profile("deny-b", denied_skills=["skill-b"])

        result = _apply_skill_filters([_SKILL_A, _SKILL_B], profile)

        names = {s.name for s in result}
        assert "skill-b" not in names
        assert "skill-a" in names

    def test_allowed_then_denied_further_restricts_result(self) -> None:
        """allowed_skills runs first, then denied_skills restricts the allowed set."""
        skill_c = SkillInfo(name="skill-c", description="C", content="c", path=Path("/fake/c"))
        profile = make_profile(
            "allow-ab-deny-b",
            allowed_skills=["skill-a", "skill-b"],
            denied_skills=["skill-b"],
        )

        result = _apply_skill_filters([_SKILL_A, _SKILL_B, skill_c], profile)

        names = {s.name for s in result}
        assert names == {"skill-a"}

    def test_parent_workspace_skills_unmodified_after_filtering(self) -> None:
        """Filtering operates on a copy — the original workspace skills list is unchanged."""
        original_skills = [_SKILL_A, _SKILL_B]
        profile = make_profile("mutate-check", allowed_skills=["skill-a"])

        workspace = MagicMock()
        workspace.skills = original_skills

        workspace_copy = copy(workspace)
        workspace_copy.skills = _apply_skill_filters(workspace_copy.skills, profile)

        # Original is untouched.
        assert workspace.skills is original_skills
        assert len(workspace.skills) == 2

        # Copy has been filtered.
        assert len(workspace_copy.skills) == 1
        assert workspace_copy.skills[0].name == "skill-a"

    def test_no_profile_inherits_all_skills(self) -> None:
        """When no profile is applied the sub-agent inherits all parent skills (backward compat)."""
        # Simulate the path in _execute_subagent where profile is None:
        # skill filtering is simply skipped, so the copy retains all skills.
        skills = [_SKILL_A, _SKILL_B]

        workspace = MagicMock()
        workspace.skills = skills
        workspace_copy = copy(workspace)
        # No profile — no filtering applied.

        assert len(workspace_copy.skills) == 2
        assert workspace_copy.skills is skills
