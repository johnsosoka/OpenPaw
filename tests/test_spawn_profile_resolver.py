"""Tests for the SpawnProfileResolver."""

import pytest

from openpaw.model.spawn_profile import SpawnProfile
from openpaw.workspace.profile_resolver import SpawnProfileResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_profile(name: str, source: str = "workspace", **kwargs) -> SpawnProfile:
    """Construct a minimal SpawnProfile for resolver tests."""
    return SpawnProfile(name=name, description=f"Profile: {name}", source=source, **kwargs)


# ---------------------------------------------------------------------------
# Basic resolution
# ---------------------------------------------------------------------------


def test_resolve_workspace_profile_by_name() -> None:
    """A workspace profile is returned when resolved by its name."""
    profile = make_profile("news-scout")
    resolver = SpawnProfileResolver(workspace_profiles=[profile])

    result = resolver.resolve("news-scout")

    assert result is profile


def test_resolve_system_profile_by_name() -> None:
    """A system profile is returned when no workspace profile shadows it."""
    profile = make_profile("code-reviewer", source="system")
    resolver = SpawnProfileResolver(workspace_profiles=[], system_profiles=[profile])

    result = resolver.resolve("code-reviewer")

    assert result is profile


def test_resolve_returns_none_for_unknown_name() -> None:
    """Resolving an unregistered name returns None."""
    resolver = SpawnProfileResolver(workspace_profiles=[make_profile("alpha")])

    result = resolver.resolve("does-not-exist")

    assert result is None


def test_resolve_returns_none_from_empty_resolver() -> None:
    """An empty resolver always returns None."""
    resolver = SpawnProfileResolver(workspace_profiles=[])

    assert resolver.resolve("anything") is None


# ---------------------------------------------------------------------------
# Workspace shadows system
# ---------------------------------------------------------------------------


def test_workspace_profile_shadows_system_profile_with_same_name() -> None:
    """When workspace and system share a name, the workspace profile wins."""
    system_profile = make_profile("shared", source="system")
    workspace_profile = make_profile("shared", source="workspace")
    resolver = SpawnProfileResolver(
        workspace_profiles=[workspace_profile],
        system_profiles=[system_profile],
    )

    result = resolver.resolve("shared")

    assert result is workspace_profile
    assert result.source == "workspace"


def test_shadowing_logs_info(caplog: pytest.LogCaptureFixture) -> None:
    """Shadowing a system profile emits an INFO log."""
    import logging

    system_profile = make_profile("shadowed", source="system")
    workspace_profile = make_profile("shadowed", source="workspace")

    with caplog.at_level(logging.INFO, logger="openpaw.workspace.profile_resolver"):
        SpawnProfileResolver(
            workspace_profiles=[workspace_profile],
            system_profiles=[system_profile],
        )

    assert any("shadowed" in record.message for record in caplog.records)


def test_system_profiles_without_same_name_are_preserved() -> None:
    """System profiles without a workspace counterpart are still resolvable."""
    system_only = make_profile("system-only", source="system")
    workspace_only = make_profile("workspace-only", source="workspace")
    resolver = SpawnProfileResolver(
        workspace_profiles=[workspace_only],
        system_profiles=[system_only],
    )

    assert resolver.resolve("system-only") is system_only
    assert resolver.resolve("workspace-only") is workspace_only


# ---------------------------------------------------------------------------
# list_profiles()
# ---------------------------------------------------------------------------


def test_list_profiles_returns_all_profiles_sorted_by_name() -> None:
    """list_profiles() returns every registered profile in alphabetical order."""
    profiles = [
        make_profile("zebra"),
        make_profile("apple"),
        make_profile("mango"),
    ]
    resolver = SpawnProfileResolver(workspace_profiles=profiles)

    listed = resolver.list_profiles()

    assert [p.name for p in listed] == ["apple", "mango", "zebra"]


def test_list_profiles_mixed_workspace_and_system() -> None:
    """list_profiles() includes both workspace and system profiles, sorted."""
    workspace = [make_profile("bravo", source="workspace")]
    system = [make_profile("alpha", source="system"), make_profile("charlie", source="system")]
    resolver = SpawnProfileResolver(workspace_profiles=workspace, system_profiles=system)

    listed = resolver.list_profiles()

    assert [p.name for p in listed] == ["alpha", "bravo", "charlie"]


def test_list_profiles_shadowed_name_appears_once() -> None:
    """A shadowed name appears exactly once in list_profiles() output."""
    system_profile = make_profile("shared", source="system")
    workspace_profile = make_profile("shared", source="workspace")
    resolver = SpawnProfileResolver(
        workspace_profiles=[workspace_profile],
        system_profiles=[system_profile],
    )

    listed = resolver.list_profiles()

    assert len([p for p in listed if p.name == "shared"]) == 1
    assert listed[0].source == "workspace"


def test_list_profiles_returns_empty_list_when_no_profiles() -> None:
    """list_profiles() on an empty resolver returns an empty list."""
    resolver = SpawnProfileResolver(workspace_profiles=[])

    assert resolver.list_profiles() == []


# ---------------------------------------------------------------------------
# list_profile_names()
# ---------------------------------------------------------------------------


def test_list_profile_names_returns_sorted_names() -> None:
    """list_profile_names() returns names sorted alphabetically."""
    profiles = [make_profile("gamma"), make_profile("alpha"), make_profile("beta")]
    resolver = SpawnProfileResolver(workspace_profiles=profiles)

    names = resolver.list_profile_names()

    assert names == ["alpha", "beta", "gamma"]


def test_list_profile_names_returns_empty_list_when_no_profiles() -> None:
    """list_profile_names() on an empty resolver returns an empty list."""
    resolver = SpawnProfileResolver(workspace_profiles=[])

    assert resolver.list_profile_names() == []


def test_list_profile_names_excludes_shadowed_duplicate() -> None:
    """A shadowed name appears only once in list_profile_names() output."""
    resolver = SpawnProfileResolver(
        workspace_profiles=[make_profile("dup", source="workspace")],
        system_profiles=[make_profile("dup", source="system")],
    )

    names = resolver.list_profile_names()

    assert names.count("dup") == 1


# ---------------------------------------------------------------------------
# __len__()
# ---------------------------------------------------------------------------


def test_len_returns_zero_for_empty_resolver() -> None:
    """len() on an empty resolver is 0."""
    resolver = SpawnProfileResolver(workspace_profiles=[])

    assert len(resolver) == 0


def test_len_returns_count_of_unique_profiles() -> None:
    """len() counts unique profile names (shadowed profiles count once)."""
    resolver = SpawnProfileResolver(
        workspace_profiles=[make_profile("alpha"), make_profile("beta")],
    )

    assert len(resolver) == 2


def test_len_counts_shadowed_name_once() -> None:
    """A shadowed name contributes 1 to the count, not 2."""
    resolver = SpawnProfileResolver(
        workspace_profiles=[make_profile("shared")],
        system_profiles=[make_profile("shared", source="system")],
    )

    assert len(resolver) == 1


def test_len_with_mixed_profiles() -> None:
    """len() reflects the total number of unique profiles across both sources."""
    resolver = SpawnProfileResolver(
        workspace_profiles=[make_profile("wp1"), make_profile("wp2")],
        system_profiles=[make_profile("sp1", source="system"), make_profile("sp2", source="system")],
    )

    assert len(resolver) == 4


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_system_profiles_none_treated_same_as_empty_list() -> None:
    """Passing system_profiles=None is equivalent to passing an empty list."""
    profile = make_profile("solo")
    resolver_none = SpawnProfileResolver(workspace_profiles=[profile], system_profiles=None)
    resolver_empty = SpawnProfileResolver(workspace_profiles=[profile], system_profiles=[])

    assert len(resolver_none) == len(resolver_empty) == 1
    assert resolver_none.resolve("solo") is not None


def test_resolver_is_independent_of_input_list_order() -> None:
    """Resolution correctness does not depend on the insertion order of profiles."""
    profiles = [make_profile("gamma"), make_profile("alpha"), make_profile("beta")]
    resolver = SpawnProfileResolver(workspace_profiles=profiles)

    assert resolver.resolve("alpha") is not None
    assert resolver.resolve("beta") is not None
    assert resolver.resolve("gamma") is not None


def test_multiple_workspace_profiles_last_write_wins() -> None:
    """When two workspace profiles share a name the last one registered wins."""
    first = SpawnProfile(name="dup", description="first")
    second = SpawnProfile(name="dup", description="second")
    resolver = SpawnProfileResolver(workspace_profiles=[first, second])

    result = resolver.resolve("dup")

    # The last workspace profile in the list should win.
    assert result is second


def test_profile_objects_returned_are_the_exact_instances_provided() -> None:
    """resolve() and list_profiles() return the original objects, not copies."""
    profile = make_profile("exact")
    resolver = SpawnProfileResolver(workspace_profiles=[profile])

    assert resolver.resolve("exact") is profile
    assert resolver.list_profiles()[0] is profile
