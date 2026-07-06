"""Tests for the /reload command handler."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.commands.base import CommandContext
from openpaw.channels.commands.handlers import ReloadCommand, get_framework_commands
from openpaw.model.message import Message


@pytest.fixture
def mock_message():
    """Create a mock message."""
    msg = MagicMock(spec=Message)
    msg.session_key = "telegram:123456"
    msg.content = "/reload"
    msg.channel = "telegram"
    msg.is_command = True
    return msg


@pytest.fixture
def mock_context(tmp_path):
    """Create a mock command context."""
    context = MagicMock(spec=CommandContext)
    context.workspace_name = "test-workspace"
    context.workspace_path = tmp_path
    context.channel = AsyncMock()
    context.skill_reloader = MagicMock(return_value=(3, 2, []))
    return context


class TestReloadCommand:
    """Tests for ReloadCommand."""

    @pytest.mark.asyncio
    async def test_reload_no_args_reloads_skills(self, mock_message, mock_context):
        handler = ReloadCommand()
        result = await handler.handle(mock_message, "", mock_context)

        mock_context.skill_reloader.assert_called_once()
        assert result.handled is True
        assert result.new_thread_id is None
        assert result.response == (
            "Skills reloaded: 5 skills loaded (3 workspace, 2 framework)."
        )

    @pytest.mark.asyncio
    async def test_reload_skills_arg_reloads_skills(self, mock_message, mock_context):
        handler = ReloadCommand()
        result = await handler.handle(mock_message, "skills", mock_context)

        mock_context.skill_reloader.assert_called_once()
        assert "5 skills loaded" in result.response

    @pytest.mark.asyncio
    async def test_reload_unknown_target(self, mock_message, mock_context):
        handler = ReloadCommand()
        result = await handler.handle(mock_message, "tools", mock_context)

        mock_context.skill_reloader.assert_not_called()
        assert "Unknown reload target: 'tools'" in result.response

    @pytest.mark.asyncio
    async def test_reload_unavailable_without_reloader(self, mock_message, mock_context):
        mock_context.skill_reloader = None
        handler = ReloadCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.response == "Skill reload is not available."

    @pytest.mark.asyncio
    async def test_reload_surfaces_skill_errors_as_warnings(
        self, mock_message, mock_context
    ):
        mock_context.skill_reloader = MagicMock(
            return_value=(2, 2, ["Failed to load skill 'broken-skill': invalid YAML"])
        )
        handler = ReloadCommand()
        result = await handler.handle(mock_message, "", mock_context)

        lines = result.response.split("\n")
        assert lines[0] == "Skills reloaded: 4 skills loaded (2 workspace, 2 framework)."
        assert lines[1] == "Warning: Failed to load skill 'broken-skill': invalid YAML"

    @pytest.mark.asyncio
    async def test_reload_singular_skill_count(self, mock_message, mock_context):
        mock_context.skill_reloader = MagicMock(return_value=(1, 0, []))
        handler = ReloadCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert "1 skill loaded" in result.response

    def test_reload_definition(self):
        handler = ReloadCommand()
        definition = handler.definition

        assert definition.name == "reload"
        assert definition.bypass_queue is False
        assert definition.hidden is False

    def test_reload_registered_in_framework_commands(self):
        commands = get_framework_commands()
        assert any(isinstance(cmd, ReloadCommand) for cmd in commands)
