"""Tests for the AgentHarness seam (ADR-101 §2).

The seam is a structural Protocol; AgentRunner satisfies it as the react
harness. These tests pin the conformance so a drift in either surface fails
loudly here (and in mypy) rather than at runtime in a caller.
"""

from pathlib import Path

import pytest

from openpaw.agent.harness import AgentHarness, HarnessKind, ReactHarness
from openpaw.agent.runner import AgentRunner
from openpaw.core.workspace import AgentWorkspace


@pytest.fixture
def workspace(tmp_path: Path) -> AgentWorkspace:
    """Minimal on-disk workspace for constructing a runner."""
    (tmp_path / "AGENT.md").write_text("# Agent")
    (tmp_path / "USER.md").write_text("# User")
    (tmp_path / "SOUL.md").write_text("# Soul")
    (tmp_path / "HEARTBEAT.md").write_text("# Heartbeat")
    return AgentWorkspace(
        name="seam-test",
        path=tmp_path,
        agent_md="# Agent",
        user_md="# User",
        soul_md="# Soul",
        heartbeat_md="# Heartbeat",
        skills_path=tmp_path / "agent" / "skills",
        tools_path=tmp_path / "tools",
    )


def test_react_harness_is_agent_runner() -> None:
    """The react harness IS AgentRunner — no delegation wrapper."""
    assert ReactHarness is AgentRunner


def test_agent_runner_satisfies_protocol(workspace: AgentWorkspace) -> None:
    """Runtime protocol conformance for the react harness."""
    runner = AgentRunner(workspace=workspace, model="openai:gpt-4o-mini", api_key="test")
    assert isinstance(runner, AgentHarness)
    assert runner.kind == HarnessKind.REACT


def test_harness_kind_values() -> None:
    """Config value spelling is pinned (harness.type: react | balanced | ultra)."""
    assert HarnessKind.REACT.value == "react"
    assert HarnessKind.BALANCED.value == "balanced"
    assert HarnessKind.ULTRA.value == "ultra"
