"""Tests for the /skills command handler."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.commands.base import CommandContext
from openpaw.channels.commands.handlers import SkillsCommand, get_framework_commands
from openpaw.model.message import Message
from openpaw.model.skill import SkillCreatedBy, SkillInfo, SkillStatus
from openpaw.stores.skill import SkillRejectedError, SkillValidationError


def make_skill(
    name: str,
    status: SkillStatus = SkillStatus.ACTIVE,
    version: int = 1,
    created_by: SkillCreatedBy = SkillCreatedBy.AGENT,
) -> SkillInfo:
    return SkillInfo(
        name=name,
        description="desc",
        content="Some content here.",
        path=Path(f"/tmp/{name}"),
        version=version,
        created_by=created_by,
        status=status,
    )


@pytest.fixture
def mock_message():
    msg = MagicMock(spec=Message)
    msg.session_key = "telegram:123456"
    msg.channel = "telegram"
    msg.is_command = True
    return msg


@pytest.fixture
def mock_context(tmp_path):
    context = MagicMock(spec=CommandContext)
    context.workspace_name = "test-workspace"
    context.workspace_path = tmp_path
    context.skill_store = AsyncMock()
    return context


class TestSkillsCommandList:
    async def test_unavailable_without_store(self, mock_message, mock_context):
        mock_context.skill_store = None
        result = await SkillsCommand().handle(mock_message, "", mock_context)
        assert result.response == "Skill management is not available."

    async def test_empty_list(self, mock_message, mock_context):
        mock_context.skill_store.list_skills.return_value = []
        result = await SkillsCommand().handle(mock_message, "", mock_context)
        assert result.response == "No workspace skills found."

    async def test_list_splits_by_status(self, mock_message, mock_context):
        mock_context.skill_store.list_skills.return_value = [
            make_skill("alpha", SkillStatus.ACTIVE, version=3),
            make_skill("beta", SkillStatus.STAGED, created_by=SkillCreatedBy.DREAM),
            make_skill("gamma", SkillStatus.DEPRECATED),
        ]
        result = await SkillsCommand().handle(mock_message, "", mock_context)

        response = result.response
        assert response.index("Active:") < response.index("Staged")
        assert response.index("Staged") < response.index("Deprecated:")
        assert "- alpha (v3, agent, ~" in response
        assert "- beta (v1, dream, ~" in response
        assert "tokens)" in response

    async def test_list_omits_empty_sections(self, mock_message, mock_context):
        mock_context.skill_store.list_skills.return_value = [make_skill("alpha")]
        result = await SkillsCommand().handle(mock_message, "", mock_context)
        assert "Staged" not in result.response
        assert "Deprecated" not in result.response


class TestSkillsCommandActions:
    async def test_approve_calls_store(self, mock_message, mock_context):
        mock_context.skill_store.approve.return_value = make_skill(
            "alpha", SkillStatus.ACTIVE, version=2
        )
        result = await SkillsCommand().handle(mock_message, "approve alpha", mock_context)

        mock_context.skill_store.approve.assert_awaited_once_with("alpha")
        assert "approved" in result.response
        assert "alpha" in result.response

    async def test_reject_calls_store(self, mock_message, mock_context):
        mock_context.skill_store.reject.return_value = make_skill(
            "beta", SkillStatus.DEPRECATED
        )
        result = await SkillsCommand().handle(mock_message, "reject beta", mock_context)

        mock_context.skill_store.reject.assert_awaited_once_with("beta")
        assert "rejected" in result.response

    async def test_store_rejection_surfaced(self, mock_message, mock_context):
        mock_context.skill_store.approve.side_effect = SkillRejectedError(
            [SkillValidationError("policy", "skill 'alpha' is active, expected staged")]
        )
        result = await SkillsCommand().handle(mock_message, "approve alpha", mock_context)
        assert "Cannot approve 'alpha'" in result.response
        assert "expected staged" in result.response

    async def test_unknown_action(self, mock_message, mock_context):
        result = await SkillsCommand().handle(mock_message, "delete alpha", mock_context)
        assert "Unknown action: 'delete'" in result.response

    async def test_missing_name(self, mock_message, mock_context):
        result = await SkillsCommand().handle(mock_message, "approve", mock_context)
        assert "Missing skill name" in result.response


class TestSkillsCommandRegistration:
    def test_definition(self):
        definition = SkillsCommand().definition
        assert definition.name == "skills"
        assert definition.hidden is False

    def test_registered_in_framework_commands(self):
        commands = get_framework_commands()
        assert any(isinstance(cmd, SkillsCommand) for cmd in commands)
