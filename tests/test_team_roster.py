"""Tests for TeamRosterBuilder."""

from openpaw.model.spawn_profile import SpawnProfile
from openpaw.workspace.profile_resolver import SpawnProfileResolver
from openpaw.workspace.roster import TeamRosterBuilder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_profile(name: str, description: str | None = None, model: str | None = None) -> SpawnProfile:
    """Construct a minimal SpawnProfile for roster tests."""
    return SpawnProfile(
        name=name,
        description=description or "",
        model=model,
    )


def make_resolver(profiles: list[SpawnProfile]) -> SpawnProfileResolver:
    """Create a resolver from a list of profiles."""
    return SpawnProfileResolver(workspace_profiles=profiles)


# ---------------------------------------------------------------------------
# Empty roster
# ---------------------------------------------------------------------------


def test_empty_profiles_returns_empty_string() -> None:
    """When no profiles are loaded, build() returns an empty string."""
    resolver = make_resolver([])
    builder = TeamRosterBuilder(resolver)

    result = builder.build()

    assert result == ""


# ---------------------------------------------------------------------------
# Single profile
# ---------------------------------------------------------------------------


def test_single_profile_returns_correct_markdown() -> None:
    """A single profile produces a complete roster with the profile row."""
    resolver = make_resolver([make_profile("news-scout", description="News research", model="anthropic:claude-haiku")])
    builder = TeamRosterBuilder(resolver)

    result = builder.build()

    assert "## Your Sub-Agent Team" in result
    assert "| Profile | Role | Model |" in result
    assert "| `news-scout` | News research | anthropic:claude-haiku |" in result


# ---------------------------------------------------------------------------
# Multiple profiles
# ---------------------------------------------------------------------------


def test_multiple_profiles_returns_correct_markdown() -> None:
    """Multiple profiles are listed in sorted order with correct markdown."""
    profiles = [
        make_profile("code-reviewer", description="Review code", model="openai:gpt-4o"),
        make_profile("news-scout", description="News research", model="anthropic:claude-haiku"),
    ]
    resolver = make_resolver(profiles)
    builder = TeamRosterBuilder(resolver)

    result = builder.build()

    lines = result.splitlines()
    # Profiles are sorted alphabetically by name
    code_reviewer_idx = next(i for i, line in enumerate(lines) if "code-reviewer" in line)
    news_scout_idx = next(i for i, line in enumerate(lines) if "news-scout" in line)
    assert code_reviewer_idx < news_scout_idx
    assert "| `code-reviewer` | Review code | openai:gpt-4o |" in result
    assert "| `news-scout` | News research | anthropic:claude-haiku |" in result


# ---------------------------------------------------------------------------
# Dispatch guidelines
# ---------------------------------------------------------------------------


def test_build_includes_all_dispatch_guidelines() -> None:
    """The roster includes all five dispatch guideline bullets."""
    resolver = make_resolver([make_profile("alpha", description="Alpha role", model="xai:grok-3")])
    builder = TeamRosterBuilder(resolver)

    result = builder.build()

    assert "### Dispatch Guidelines" in result
    assert "Delegate proactively" in result
    assert "Prefer profiles over manual tool filtering" in result
    assert "Sub-agents are fire-and-forget" in result
    assert "Chain results" in result
    assert "Use `list_team_profiles` for details" in result


# ---------------------------------------------------------------------------
# Default placeholders
# ---------------------------------------------------------------------------


def test_profile_without_model_uses_workspace_default() -> None:
    """A profile with no model shows the '(workspace default)' placeholder."""
    resolver = make_resolver([make_profile("no-model", description="Has no model")])
    builder = TeamRosterBuilder(resolver)

    result = builder.build()

    assert "| `no-model` | Has no model | (workspace default) |" in result


def test_profile_without_description_uses_no_description() -> None:
    """A profile with no description shows the '(no description)' placeholder."""
    resolver = make_resolver([make_profile("no-desc", description="", model="openai:gpt-4o")])
    builder = TeamRosterBuilder(resolver)

    result = builder.build()

    assert "| `no-desc` | (no description) | openai:gpt-4o |" in result
