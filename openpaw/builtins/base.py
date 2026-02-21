"""Base abstractions for OpenPaw builtins."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from openpaw.model.message import Message


class BuiltinType(Enum):
    """Classification of builtin capabilities."""

    TOOL = "tool"
    PROCESSOR = "processor"


@dataclass
class BuiltinPrerequisite:
    """Defines what a builtin needs to be available.

    Attributes:
        env_vars: Environment variables that must be set.
        packages: Python packages that must be installed (future use).
    """

    env_vars: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)

    def is_satisfied(self) -> bool:
        """Check if all prerequisites are met."""
        import os

        return all(os.environ.get(var) for var in self.env_vars)

    def missing(self) -> list[str]:
        """Return list of missing prerequisites."""
        import os

        missing = []
        for var in self.env_vars:
            if not os.environ.get(var):
                missing.append(f"env:{var}")
        return missing


@dataclass
class BuiltinMetadata:
    """Metadata describing a builtin capability.

    Attributes:
        name: Internal identifier (e.g., "brave_search").
        display_name: Human-readable name (e.g., "Brave Web Search").
        description: What the builtin does.
        builtin_type: Whether this is a tool or processor.
        group: Optional group for allow/deny (e.g., "web", "voice").
        prerequisites: What's needed to use this builtin.
    """

    name: str
    display_name: str
    description: str
    builtin_type: BuiltinType
    group: str | None = None
    prerequisites: BuiltinPrerequisite = field(default_factory=BuiltinPrerequisite)


class BaseBuiltinTool(ABC):
    """Abstract base class for tool builtins.

    Tools are LangChain-compatible callables that agents can invoke.
    Examples: web search, text-to-speech, image generation.
    """

    metadata: BuiltinMetadata

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize with optional configuration.

        Args:
            config: Builtin-specific configuration from workspace/global config.
        """
        self.config = config or {}

    @abstractmethod
    def get_langchain_tool(self) -> Any:
        """Return a LangChain-compatible tool instance.

        The returned object should be usable with LangChain agents,
        typically a BaseTool subclass or StructuredTool.
        """
        ...


@dataclass
class ProcessorResult:
    """Result from a processor transformation.

    Attributes:
        message: The (possibly modified) message.
        attachments: Any attachments to include in the response.
        skip_agent: If True, don't send to agent (processor handled it).
    """

    message: Message
    attachments: list[Any] = field(default_factory=list)
    skip_agent: bool = False


class BaseBuiltinProcessor(ABC):
    """Abstract base class for processor builtins.

    Processors transform messages at the channel layer, either before
    the agent sees them (inbound) or after the agent responds (outbound).
    Examples: audio transcription, language translation, content filtering.
    """

    metadata: BuiltinMetadata

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize with optional configuration.

        Args:
            config: Builtin-specific configuration from workspace/global config.
        """
        self.config = config or {}

    async def process_inbound(self, message: Message) -> ProcessorResult:
        """Transform an inbound message before it reaches the agent.

        Override this method to preprocess incoming messages.
        Default implementation passes through unchanged.

        Args:
            message: The incoming message from a channel.

        Returns:
            ProcessorResult with transformed message and optional attachments.
        """
        return ProcessorResult(message=message)

    async def process_outbound(
        self,
        message: Message,
        response: str,
    ) -> tuple[str, list[Any]]:
        """Transform an outbound response before sending to channel.

        Override this method to postprocess agent responses.
        Default implementation passes through unchanged.

        Args:
            message: The original inbound message (for context).
            response: The agent's text response.

        Returns:
            Tuple of (modified_response, attachments_to_send).
        """
        return response, []
