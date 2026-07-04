"""Tests for the /harness command and WorkspaceRunner._harness_info (C9)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openpaw.channels.commands.base import CommandContext
from openpaw.channels.commands.handlers import HarnessCommand, get_framework_commands
from openpaw.core.config.models import WorkspaceConfig
from openpaw.model.message import Message
from openpaw.workspace.model_resolver import ModelResolver
from openpaw.workspace.node_model_resolver import NodeModelResolver
from openpaw.workspace.runner import WorkspaceRunner

WORKSPACE_MODEL = "anthropic:claude-sonnet-4-20250514"


@pytest.fixture
def mock_message():
    msg = MagicMock(spec=Message)
    msg.session_key = "telegram:123456"
    msg.content = "/harness"
    msg.channel = "telegram"
    msg.is_command = True
    return msg


def _node_resolver() -> NodeModelResolver:
    resolver = ModelResolver(
        provider_catalog={},
        configured_model=WORKSPACE_MODEL,
        api_key="test-key",
        region=None,
        extra_model_kwargs={},
    )
    return NodeModelResolver(
        resolver=resolver,
        workspace_model=WORKSPACE_MODEL,
        workspace_api_key="test-key",
        workspace_temperature=0.7,
        workspace_region=None,
        workspace_extra_kwargs={},
    )


def _fake_runner(config: WorkspaceConfig | None, ultra: bool = False) -> SimpleNamespace:
    """Duck-typed WorkspaceRunner for calling _harness_info directly."""
    agent_runner = SimpleNamespace()
    if ultra:
        agent_runner = SimpleNamespace(node_resolver=_node_resolver())
    return SimpleNamespace(
        _agent_factory=SimpleNamespace(
            active_model=WORKSPACE_MODEL,
            configured_model=WORKSPACE_MODEL,
        ),
        _workspace=SimpleNamespace(config=config),
        _agent_runner=agent_runner,
    )


# ---------------------------------------------------------------------------
# WorkspaceRunner._harness_info
# ---------------------------------------------------------------------------


def test_harness_info_react_default():
    config = WorkspaceConfig()  # harness defaults to react
    fake = _fake_runner(config)

    info = WorkspaceRunner._harness_info(fake)

    assert info == f"Harness: react\nModel: {WORKSPACE_MODEL}"


def test_harness_info_react_when_no_config():
    fake = _fake_runner(config=None)

    info = WorkspaceRunner._harness_info(fake)

    assert info.startswith("Harness: react")


def test_harness_info_ultra_table():
    config = WorkspaceConfig(
        harness={
            "type": "ultra",
            "triage": {"model": "openai:gpt-4o-mini"},
            "planning": {"module": "auto"},
        }
    )
    fake = _fake_runner(config, ultra=True)

    info = WorkspaceRunner._harness_info(fake)
    lines = info.splitlines()

    assert lines[0] == "Harness: ultra"
    # Pinned node: no inherited marker
    assert "triage: openai:gpt-4o-mini" in info
    assert "triage: openai:gpt-4o-mini (inherited)" not in info
    # Inherited nodes carry the marker; module kinds show their module
    assert f"planning: {WORKSPACE_MODEL} (inherited) [module: auto]" in info
    assert f"creative: {WORKSPACE_MODEL} (inherited) [module: ideonomy]" in info
    assert f"reflection: {WORKSPACE_MODEL} (inherited) [module: light]" in info
    assert f"selector: {WORKSPACE_MODEL} (inherited)" in info
    assert f"synthesize: {WORKSPACE_MODEL} (inherited)" in info
    # Execution row shows the factory's active model (runtime override target)
    assert lines[-1] == f"execution: {WORKSPACE_MODEL}"


def test_harness_info_ultra_execution_shows_runtime_override():
    config = WorkspaceConfig(harness={"type": "ultra"})
    fake = _fake_runner(config, ultra=True)
    fake._agent_factory.active_model = "xai:grok-4"

    info = WorkspaceRunner._harness_info(fake)

    assert "execution: xai:grok-4" in info


# ---------------------------------------------------------------------------
# HarnessCommand handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_harness_command_returns_info(mock_message):
    context = MagicMock(spec=CommandContext)
    context.harness_info = lambda: "Harness: react\nModel: m"

    result = await HarnessCommand().handle(mock_message, "", context)

    assert result.handled is True
    assert result.response == "Harness: react\nModel: m"


@pytest.mark.asyncio
async def test_harness_command_without_closure(mock_message):
    context = MagicMock(spec=CommandContext)
    context.harness_info = None

    result = await HarnessCommand().handle(mock_message, "", context)

    assert result.response == "Harness info is not available."


def test_harness_command_is_registered():
    handlers = get_framework_commands()
    names = [h.definition.name for h in handlers]

    assert "harness" in names
    assert any(isinstance(h, HarnessCommand) for h in handlers)
