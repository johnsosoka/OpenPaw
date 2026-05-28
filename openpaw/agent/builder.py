"""Agent builder for constructing LangGraph agents from workspace config."""
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
    """Builds LangGraph agents from workspace configuration."""

    def __init__(
        self,
        workspace: AgentWorkspace,
        model: str,
        api_key: str | None,
        temperature: float,
        max_turns: int,
        checkpointer: Any | None,
        tools: list[Any] | None,
        region: str | None,
        strip_thinking: bool,
        enabled_builtins: list[str] | None,
        extra_model_kwargs: dict[str, Any] | None,
        middleware: list[Any] | None,
        channel_logging_enabled: bool,
        create_model_func: Any | None = None,
        create_agent_func: Any | None = None,
    ):
        self.workspace = workspace
        self.model_id = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_turns = max_turns
        self.checkpointer = checkpointer
        self.additional_tools = tools or []
        self.region = region
        self.strip_thinking = strip_thinking
        self.enabled_builtins = enabled_builtins
        self.extra_model_kwargs = extra_model_kwargs or {}
        self._middleware = middleware or []
        self.channel_logging_enabled = channel_logging_enabled
        self._create_model_func = create_model_func
        self._create_agent_func = create_agent_func or create_agent

    def build(self) -> tuple[Any, BaseChatModel]:
        """Build and return a new agent instance plus the model instance."""
        model = self._create_model_func() if self._create_model_func else self._create_model()

        # 2. Create FilesystemTools for workspace
        workspace_root = self.workspace.path.resolve()
        if not workspace_root.exists():
            raise ValueError(f"Workspace does not exist: {workspace_root}")
        if not workspace_root.is_dir():
            raise ValueError(f"Workspace is not a directory: {workspace_root}")

        logger.debug(f"Sandboxing agent to workspace: {workspace_root}")

        # Get timezone from workspace config, defaulting to UTC
        timezone = self.workspace.config.timezone if self.workspace.config else "UTC"

        fs_tools_manager = FilesystemTools(
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
            middleware = [ThinkingTokenMiddleware(), *self._middleware]
        else:
            middleware = list(self._middleware)

        # 7. Call create_agent (successor to create_react_agent)
        logger.info(
            f"Creating agent with {len(all_tools)} tools "
            f"({len(filesystem_tools)} filesystem, {len(self.additional_tools)} additional)"
        )

        tool_names = [getattr(t, 'name', str(t)) for t in all_tools]
        logger.info(f"Tool names: {tool_names}")

        agent = self._create_agent_func(
            model=model,
            tools=all_tools,
            system_prompt=system_prompt,
            checkpointer=self.checkpointer,
            middleware=middleware,
        )

        return agent, model

    def _create_model(self) -> BaseChatModel:
        """Create the chat model instance."""
        return create_chat_model(
            model_str=self.model_id,
            api_key=self.api_key,
            temperature=self.temperature,
            region=self.region,
            extra_kwargs=self.extra_model_kwargs,
        )
