"""Base abstractions for the command system."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openpaw.channels.base import ChannelAdapter, Message
    from openpaw.core.agent import AgentRunner
    from openpaw.queue.manager import QueueManager
    from openpaw.session.manager import SessionManager


class CommandScope(Enum):
    """Where a command can be used."""

    FRAMEWORK = "framework"
    WORKSPACE = "workspace"


@dataclass
class CommandDefinition:
    """Metadata for a registered command."""

    name: str  # e.g., "new", "compact", "queue"
    description: str  # Short description for /help
    scope: CommandScope = CommandScope.FRAMEWORK
    bypass_queue: bool = False  # If True, handle immediately
    hidden: bool = False  # If True, omit from /help
    args_description: str | None = None  # e.g., "<mode>" for /queue


@dataclass
class CommandContext:
    """Runtime context passed to command handlers."""

    channel: "ChannelAdapter"
    session_manager: "SessionManager"
    checkpointer: Any  # AsyncSqliteSaver
    agent_runner: "AgentRunner"
    workspace_name: str
    workspace_path: Path
    queue_manager: "QueueManager"
    command_router: Any = None  # CommandRouter, avoid circular import
    conversation_archiver: Any = None  # ConversationArchiver, avoid circular import
    workspace_timezone: str = "UTC"  # IANA timezone string for day boundaries


@dataclass
class CommandResult:
    """Result from a command handler."""

    response: str | None = None  # Text to send back to user
    handled: bool = True  # If False, pass message to agent
    new_thread_id: str | None = None  # If set, switch to this thread


class CommandHandler(ABC):
    """Base class for command implementations."""

    @property
    @abstractmethod
    def definition(self) -> CommandDefinition:
        """Command metadata."""
        ...

    @abstractmethod
    async def handle(
        self,
        message: "Message",
        args: str,
        context: CommandContext,
    ) -> CommandResult:
        """Execute the command."""
        ...
