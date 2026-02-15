"""Base abstractions for OpenPaw builtins."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from openpaw.domain.message import Message

if TYPE_CHECKING:
    from openpaw.builtins.base import BaseBuiltinProcessor, BaseBuiltinTool


class BuiltinType(Enum):
    """Classification of builtin capabilities (for backward compatibility)."""

    TOOL = "tool"
    PROCESSOR = "processor"


class _BuiltinMetadataCompat:
    """Backward compatibility shim for code accessing .metadata attributes."""

    def __init__(self, builtin_cls: type) -> None:
        self._cls = builtin_cls

    @property
    def name(self) -> str:
        return self._cls.name

    @property
    def group(self) -> str | None:
        return getattr(self._cls, "group", None)

    @property
    def display_name(self) -> str:
        return self._cls.name

    @property
    def prerequisites(self) -> "_BuiltinMetadataCompat":
        return self

    @property
    def env_vars(self) -> list[str]:
        return getattr(self._cls, "required_env_vars", [])

    @property
    def packages(self) -> list[str]:
        return getattr(self._cls, "required_packages", [])

    def is_satisfied(self) -> bool:
        return self._cls.is_available()

    @property
    def builtin_type(self) -> BuiltinType:
        # Import locally to avoid circular dependency
        if issubclass(self._cls, BaseBuiltinTool):
            return BuiltinType.TOOL
        return BuiltinType.PROCESSOR


class BaseBuiltinTool(ABC):
    """Abstract base class for tool builtins.

    Tools are LangChain-compatible callables that agents can invoke.
    Examples: web search, text-to-speech, image generation.

    Subclasses MUST set these class attributes:
        name: Internal identifier (e.g., "brave_search")
        group: Optional group for allow/deny (e.g., "web", "voice")
        required_env_vars: Environment variables that must be set
        required_packages: Python packages that must be installed
    """

    name: str
    group: str | None = None
    required_env_vars: list[str] = []
    required_packages: list[str] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Create backward-compatible metadata attribute on subclass."""
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "name") and isinstance(cls.name, str):
            cls.metadata = _BuiltinMetadataCompat(cls)

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize with optional configuration.

        Args:
            config: Builtin-specific configuration from workspace/global config.
        """
        self.config = config or {}

    @classmethod
    def is_available(cls) -> bool:
        """Check if prerequisites are met (env vars set).

        Returns:
            True if all required environment variables are set.
        """
        import os

        return all(os.environ.get(var) for var in cls.required_env_vars)

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

    Subclasses MUST set these class attributes:
        name: Internal identifier (e.g., "whisper")
        group: Optional group for allow/deny (e.g., "voice", "document")
        required_env_vars: Environment variables that must be set
        required_packages: Python packages that must be installed
        order: Pipeline position (lower = earlier, default 100)
    """

    name: str
    group: str | None = None
    required_env_vars: list[str] = []
    required_packages: list[str] = []
    order: int = 100

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Create backward-compatible metadata attribute on subclass."""
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "name") and isinstance(cls.name, str):
            cls.metadata = _BuiltinMetadataCompat(cls)

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize with optional configuration.

        Args:
            config: Builtin-specific configuration from workspace/global config.
        """
        self.config = config or {}

    @classmethod
    def is_available(cls) -> bool:
        """Check if prerequisites are met (env vars set).

        Returns:
            True if all required environment variables are set.
        """
        import os

        return all(os.environ.get(var) for var in cls.required_env_vars)

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
