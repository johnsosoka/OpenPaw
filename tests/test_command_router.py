"""Tests for command routing system."""

import pytest

from openpaw.channels.base import Message, MessageDirection
from openpaw.channels.commands.base import (
    CommandContext,
    CommandDefinition,
    CommandHandler,
    CommandResult,
    CommandScope,
)
from openpaw.channels.commands.router import CommandRouter


class MockCommandHandler(CommandHandler):
    """Mock command handler for testing."""

    def __init__(
        self,
        name: str,
        description: str = "Test command",
        hidden: bool = False,
        response: str = "Command executed",
    ) -> None:
        self._name = name
        self._description = description
        self._hidden = hidden
        self._response = response

    @property
    def definition(self) -> CommandDefinition:
        return CommandDefinition(
            name=self._name,
            description=self._description,
            scope=CommandScope.FRAMEWORK,
            hidden=self._hidden,
        )

    async def handle(
        self,
        message: Message,
        args: str,
        context: CommandContext,
    ) -> CommandResult:
        return CommandResult(response=self._response, handled=True)


@pytest.fixture
def router() -> CommandRouter:
    """Create a fresh command router."""
    return CommandRouter()


@pytest.fixture
def mock_context() -> CommandContext:
    """Create a mock command context."""
    # We only need the CommandContext dataclass instance for routing tests
    # The actual values don't matter since our mock handler doesn't use them
    return CommandContext(
        channel=None,  # type: ignore
        session_manager=None,  # type: ignore
        checkpointer=None,
        agent_runner=None,  # type: ignore
        workspace_name="test",
        workspace_path=None,  # type: ignore
        queue_manager=None,  # type: ignore
    )


def test_register_handler(router: CommandRouter) -> None:
    """Test registering a command handler."""
    handler = MockCommandHandler("test", "A test command")
    router.register(handler)

    retrieved = router.get_handler("test")
    assert retrieved is handler
    assert retrieved.definition.name == "test"
    assert retrieved.definition.description == "A test command"


def test_get_handler_not_found(router: CommandRouter) -> None:
    """Test getting a handler that doesn't exist."""
    handler = router.get_handler("nonexistent")
    assert handler is None


def test_list_commands(router: CommandRouter) -> None:
    """Test listing registered commands."""
    handler1 = MockCommandHandler("cmd1", "Command 1")
    handler2 = MockCommandHandler("cmd2", "Command 2", hidden=True)
    handler3 = MockCommandHandler("cmd3", "Command 3")

    router.register(handler1)
    router.register(handler2)
    router.register(handler3)

    # Default: exclude hidden
    commands = router.list_commands()
    assert len(commands) == 2
    assert {c.name for c in commands} == {"cmd1", "cmd3"}


def test_list_commands_include_hidden(router: CommandRouter) -> None:
    """Test listing commands with hidden included."""
    handler1 = MockCommandHandler("cmd1", "Command 1")
    handler2 = MockCommandHandler("cmd2", "Command 2", hidden=True)

    router.register(handler1)
    router.register(handler2)

    # Include hidden
    commands = router.list_commands(include_hidden=True)
    assert len(commands) == 2
    assert {c.name for c in commands} == {"cmd1", "cmd2"}


@pytest.mark.asyncio
async def test_route_known_command(
    router: CommandRouter, mock_context: CommandContext
) -> None:
    """Test routing a known command."""
    handler = MockCommandHandler("queue", response="Queue mode changed")
    router.register(handler)

    message = Message(
        id="1",
        channel="test",
        session_key="test:123",
        user_id="u1",
        content="/queue collect",
        direction=MessageDirection.INBOUND,
    )

    result = await router.route(message, mock_context)

    assert result is not None
    assert result.handled is True
    assert result.response == "Queue mode changed"


@pytest.mark.asyncio
async def test_route_unknown_command(
    router: CommandRouter, mock_context: CommandContext
) -> None:
    """Test routing an unknown command returns None."""
    message = Message(
        id="1",
        channel="test",
        session_key="test:123",
        user_id="u1",
        content="/unknown arg1 arg2",
        direction=MessageDirection.INBOUND,
    )

    result = await router.route(message, mock_context)
    assert result is None


@pytest.mark.asyncio
async def test_route_non_command_message(
    router: CommandRouter, mock_context: CommandContext
) -> None:
    """Test routing a non-command message returns None."""
    handler = MockCommandHandler("test")
    router.register(handler)

    message = Message(
        id="1",
        channel="test",
        session_key="test:123",
        user_id="u1",
        content="This is a regular message, not a command",
        direction=MessageDirection.INBOUND,
    )

    result = await router.route(message, mock_context)
    assert result is None


@pytest.mark.asyncio
async def test_route_bot_mention_stripping(
    router: CommandRouter, mock_context: CommandContext
) -> None:
    """Test that bot mentions are stripped from command names."""
    handler = MockCommandHandler("queue", response="Queue command")
    router.register(handler)

    # Telegram format: /queue@MyBotName
    message = Message(
        id="1",
        channel="test",
        session_key="test:123",
        user_id="u1",
        content="/queue@MyBotName collect",
        direction=MessageDirection.INBOUND,
    )

    result = await router.route(message, mock_context)

    assert result is not None
    assert result.handled is True
    assert result.response == "Queue command"


@pytest.mark.asyncio
async def test_route_command_with_args(
    router: CommandRouter, mock_context: CommandContext
) -> None:
    """Test routing a command with arguments."""

    class ArgsTestHandler(CommandHandler):
        @property
        def definition(self) -> CommandDefinition:
            return CommandDefinition(
                name="test",
                description="Test command",
                scope=CommandScope.FRAMEWORK,
            )

        async def handle(
            self,
            message: Message,
            args: str,
            context: CommandContext,
        ) -> CommandResult:
            return CommandResult(response=f"Args: {args}", handled=True)

    handler = ArgsTestHandler()
    router.register(handler)

    message = Message(
        id="1",
        channel="test",
        session_key="test:123",
        user_id="u1",
        content="/test arg1 arg2 arg3",
        direction=MessageDirection.INBOUND,
    )

    result = await router.route(message, mock_context)

    assert result is not None
    assert result.response == "Args: arg1 arg2 arg3"
