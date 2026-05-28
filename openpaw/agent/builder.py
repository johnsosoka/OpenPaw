"""Agent builder for constructing LangGraph agents with workspace configuration.

This module extracts the agent construction logic from AgentRunner into a
pure builder class that can be used independently.
"""

import logging
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel

from openpaw.agent.middleware.llm_hooks import ThinkingTokenMiddleware
from openpaw.agent.model_factory import create_chat_model, validate_tool_names
from openpaw.agent.tools.filesystem import FilesystemTools
from openpaw.core.timezone import workspace_now
from openpaw.core.workspace import AgentWorkspace

logger = logging.getLogger(__name__)


class AgentBuilder:
    """Pure builder for LangGraph agents with workspace configuration.

    Encapsulates all agent construction logic previously in
    AgentRunner._build_agent() and AgentRunner._create_model().

    Usage:
        builder = AgentBuilder(workspace=..., model_id=...)
        agent, model_instance = builder.build()
    """

    def __init__(
        self,
        workspace: AgentWorkspace,
        model_id: str = "anthropic:claude-sonnet-4-20250514",
        api_key: str | None = None,
        temperature: float = 0.7,
        max_turns: int = 50,
        checkpointer: Any | None = None,
        tools: list[Any] | None = None,
        region: str | None = None,
        strip_thinking: bool = False,
        enabled_builtins: list[str] | None = None,
        extra_model_kwargs: dict[str, Any] | None = None,
        middleware: list[Any] | None = None,
        channel_logging_enabled: bool = False,
        create_agent_func: Any | None = None,
        filesystem_tools_cls: Any | None = None,
    ):
        """Initialize the agent builder.

        Args:
            workspace: Loaded agent workspace.
            model_id: Model identifier (provider:model format).
            api_key: API key for the model provider.
            temperature: Model temperature setting.
            max_turns: Maximum agent turns per invocation.
            checkpointer: Optional LangGraph checkpointer for persistence.
            tools: Optional additional tools to provide to the agent.
            region: AWS region for Bedrock models (e.g., us-east-1).
            strip_thinking: Whether to strip thinking tokens from responses.
            enabled_builtins: List of enabled builtin tool names for conditional prompt sections.
            extra_model_kwargs: Additional kwargs to pass to init_chat_model.
            middleware: Optional list of middleware functions for tool execution.
            channel_logging_enabled: Whether channel logging is enabled for this workspace.
            create_agent_func: Optional create_agent function override (for test patching).
            filesystem_tools_cls: Optional FilesystemTools class override (for test patching).
        """
        self.workspace = workspace
        self.model_id = model_id
        self.api_key = api_key
        self.temperature = temperature
        self.max_turns = max_turns
        self.checkpointer = checkpointer
        self.additional_tools = tools or []
        self.region = region
        self.strip_thinking = strip_thinking
        self.enabled_builtins = enabled_builtins
        self.extra_model_kwargs = extra_model_kwargs or {}
        self.middleware = middleware or []
        self.channel_logging_enabled = channel_logging_enabled
        self._create_agent_func = create_agent_func or create_agent
        self._filesystem_tools_cls = filesystem_tools_cls or FilesystemTools

    def create_model(self) -> BaseChatModel:
        """Create the appropriate chat model based on provider.

        Delegates to create_chat_model() module-level function.

        Returns:
            Configured BaseChatModel instance.

        Raises:
            ValueError: If provider is not supported.
        """
        return create_chat_model(
            model_str=self.model_id,
            api_key=self.api_key,
            temperature=self.temperature,
            region=self.region,
            extra_kwargs=self.extra_model_kwargs,
        )

    def build(self, model: BaseChatModel | None = None) -> tuple[Any, BaseChatModel]:
        """Build the LangGraph agent with workspace configuration.

        Creates an agent with:
        - Direct provider-specific model instantiation (if model not provided)
        - Sandboxed filesystem tools for workspace access
        - Workspace-specific tools from tools/ directory
        - System prompt from workspace markdown files
        - Middleware list (thinking token stripping, queue-aware, approval gates)

        Args:
            model: Optional pre-built model instance. If None, create_model() is called.

        Returns:
            Tuple of (agent, model_instance).
        """
        # 1. Initialize model directly via provider class (if not provided)
        if model is None:
            model = self.create_model()

        # 2. Create FilesystemTools for workspace
        workspace_root = self.workspace.path.resolve()
        if not workspace_root.exists():
            raise ValueError(f"Workspace does not exist: {workspace_root}")
        if not workspace_root.is_dir():
            raise ValueError(f"Workspace is not a directory: {workspace_root}")

        logger.debug(f"Sandboxing agent to workspace: {workspace_root}")

        # Get timezone from workspace config, defaulting to UTC
        timezone = self.workspace.config.timezone if self.workspace.config else "UTC"

        fs_tools_manager = self._filesystem_tools_cls(
            workspace_root=workspace_root,
            timezone=timezone,
            workspace_name=self.workspace.name,
        )
        filesystem_tools = fs_tools_manager.get_tools()

        # 3. Combine all tools (filesystem + additional tools)
        all_tools = filesystem_tools + self.additional_tools

        # 4. Validate tool names (especially important for Bedrock)
        if "bedrock" in self.model_id.lower():
            logger.debug("Validating tool names for Bedrock compatibility")
            validate_tool_names(all_tools)

        # 5. Get system prompt from workspace (with dynamic current date)
        try:
            timezone = getattr(self.workspace.config, "timezone", "UTC") if self.workspace.config else "UTC"
            current_dt = workspace_now(timezone).strftime("%A, %Y-%m-%d %H:%M %Z")
        except (TypeError, AttributeError):
            current_dt = None
        system_prompt = self.workspace.build_system_prompt(
            enabled_builtins=self.enabled_builtins,
            current_datetime=current_dt,
            channel_logging_enabled=self.channel_logging_enabled,
        )

        # 6. Wire middleware in dependency order:
        #    - ThinkingTokenMiddleware (first): strips reasoning before other middleware sees it
        #    - Custom middleware (after): queue-aware, approval gates, etc.
        if self.strip_thinking:
            middleware = [ThinkingTokenMiddleware(), *self.middleware]
        else:
            middleware = list(self.middleware)

        # 7. Call create_agent (successor to create_react_agent)
        # Note: create_agent handles tool binding internally - do NOT pre-bind
        logger.info(
            f"Creating agent with {len(all_tools)} tools "
            f"({len(filesystem_tools)} filesystem, {len(self.additional_tools)} additional)"
        )

        # Log all tool names for debugging
        tool_names = [getattr(t, "name", str(t)) for t in all_tools]
        logger.info(f"Tool names: {tool_names}")

        agent = self._create_agent_func(
            model=model,
            tools=all_tools,
            system_prompt=system_prompt,
            checkpointer=self.checkpointer,
            middleware=middleware,  # Thinking tokens + steer/interrupt + approval gates
        )

        return agent, model
