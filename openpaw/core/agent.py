"""Agent runner integrating LangGraph ReAct agent with OpenPaw workspace system."""

import asyncio
import logging
import re
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent

from openpaw.tools.filesystem import FilesystemTools
from openpaw.workspace.loader import AgentWorkspace

logger = logging.getLogger(__name__)

# Pattern to match thinking tokens like <think>...</think>
# Non-greedy match, handles multiline content
THINKING_TAG_PATTERN = re.compile(r"<think>[\s\S]*?</think>\s*", re.IGNORECASE)

# Models known to produce thinking tokens
THINKING_MODELS = ["moonshot.kimi-k2-thinking", "kimi-k2-thinking", "kimi-thinking"]

# Bedrock tool name validation pattern (AWS requirement)
BEDROCK_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
MAX_TOOL_NAME_LENGTH = 64


class AgentRunner:
    """Runs LangGraph ReAct agent with OpenPaw workspace configuration.

    Integrates:
    - Workspace-based system prompts (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
    - Sandboxed filesystem access for workspace operations
    - LangGraph checkpointing for multi-turn conversations
    - Automatic stripping of model thinking tokens (<think>...</think>)
    - Tool name validation for Bedrock compatibility
    """

    @staticmethod
    def _strip_thinking_tokens(text: str) -> str:
        """Strip thinking tokens from model response.

        Some models (e.g., Bedrock moonshot.kimi-k2-thinking) output internal
        reasoning wrapped in <think>...</think> tags. These should be removed
        before showing the response to users.

        Args:
            text: Raw response text potentially containing thinking tokens.

        Returns:
            Response text with thinking tokens removed and trimmed.
        """
        cleaned = THINKING_TAG_PATTERN.sub("", text)
        return cleaned.strip()

    def __init__(
        self,
        workspace: AgentWorkspace,
        model: str = "anthropic:claude-sonnet-4-20250514",
        api_key: str | None = None,
        max_turns: int = 50,
        temperature: float = 0.7,
        checkpointer: Any | None = None,
        tools: list[Any] | None = None,
        region: str | None = None,
        strip_thinking: bool = False,
        timeout_seconds: float = 300.0,
        enabled_builtins: list[str] | None = None,
    ):
        """Initialize the agent runner.

        Args:
            workspace: Loaded agent workspace.
            model: Model identifier (provider:model format).
            api_key: API key for the model provider.
            max_turns: Maximum agent turns per invocation.
            temperature: Model temperature setting.
            checkpointer: Optional LangGraph checkpointer for persistence.
            tools: Optional additional tools to provide to the agent.
            region: AWS region for Bedrock models (e.g., us-east-1).
            strip_thinking: Whether to strip <think>...</think> tokens from responses.
            timeout_seconds: Wall-clock timeout for agent invocations (default 5 minutes).
            enabled_builtins: List of enabled builtin tool names for conditional prompt sections.
        """
        self.workspace = workspace
        self.model_id = model
        self.api_key = api_key
        self.max_turns = max_turns
        self.temperature = temperature
        self.checkpointer = checkpointer
        self.additional_tools = tools or []
        self.region = region
        self.strip_thinking = strip_thinking
        self.timeout_seconds = timeout_seconds
        self.enabled_builtins = enabled_builtins

        # Auto-enable thinking stripping for known thinking models
        if not self.strip_thinking and any(
            thinking_model in self.model_id.lower()
            for thinking_model in THINKING_MODELS
        ):
            logger.info(
                f"Auto-enabling thinking token stripping for model: {self.model_id}"
            )
            self.strip_thinking = True

        self._agent = self._build_agent()

    def update_checkpointer(self, checkpointer: Any) -> None:
        """Update the checkpointer and rebuild the agent graph.

        Used for deferred initialization when checkpointer requires async setup.

        Args:
            checkpointer: New checkpointer instance (e.g., AsyncSqliteSaver).
        """
        self.checkpointer = checkpointer
        self._agent = self._build_agent()
        logger.info(f"Updated checkpointer for workspace: {self.workspace.name}")

    def _validate_tool_names(self, tools: list[Any]) -> None:
        """Validate tool names comply with Bedrock requirements.

        AWS Bedrock requires tool names to:
        - Match pattern [a-zA-Z0-9_-]+
        - Be 64 characters or less

        Args:
            tools: List of tools to validate.

        Raises:
            ValueError: If any tool name is invalid.
        """
        for tool in tools:
            tool_name = getattr(tool, "name", None)
            if not tool_name:
                logger.warning(f"Tool {tool} has no name attribute, skipping validation")
                continue

            # Check length
            if len(tool_name) > MAX_TOOL_NAME_LENGTH:
                raise ValueError(
                    f"Tool name '{tool_name}' exceeds max length of {MAX_TOOL_NAME_LENGTH} characters"
                )

            # Check pattern
            if not BEDROCK_TOOL_NAME_PATTERN.match(tool_name):
                raise ValueError(
                    f"Tool name '{tool_name}' contains invalid characters. "
                    f"Must match pattern: [a-zA-Z0-9_-]+"
                )

    def _build_agent(self) -> Any:
        """Build the LangGraph ReAct agent with workspace configuration.

        Creates a ReAct agent with:
        - Multi-provider model support via init_chat_model
        - Sandboxed filesystem tools for workspace access
        - Workspace-specific tools from tools/ directory
        - System prompt from workspace markdown files
        - Optional thinking token stripping via post_model_hook
        """
        # 1. Initialize model with init_chat_model
        model_kwargs: dict[str, Any] = {"temperature": self.temperature}
        is_bedrock = self.model_id.startswith("bedrock")
        if self.api_key and not is_bedrock:
            model_kwargs["api_key"] = self.api_key
        if self.region:
            model_kwargs["region_name"] = self.region

        model = init_chat_model(self.model_id, **model_kwargs)

        # 2. Create FilesystemTools for workspace
        workspace_root = self.workspace.path.resolve()
        if not workspace_root.exists():
            raise ValueError(f"Workspace does not exist: {workspace_root}")
        if not workspace_root.is_dir():
            raise ValueError(f"Workspace is not a directory: {workspace_root}")

        logger.debug(f"Sandboxing agent to workspace: {workspace_root}")

        fs_tools_manager = FilesystemTools(workspace_root=workspace_root)
        filesystem_tools = fs_tools_manager.get_tools()

        # 3. Combine all tools (filesystem + additional tools)
        all_tools = filesystem_tools + self.additional_tools

        # 4. Validate tool names (especially important for Bedrock)
        if "bedrock" in self.model_id.lower():
            logger.debug("Validating tool names for Bedrock compatibility")
            self._validate_tool_names(all_tools)

        # 5. Get system prompt from workspace
        system_prompt = self.workspace.build_system_prompt(enabled_builtins=self.enabled_builtins)

        # 6. Create post_model_hook for thinking stripping (if needed)
        post_hook = self._strip_thinking_hook if self.strip_thinking else None

        # 7. Call create_react_agent
        # Note: create_react_agent handles tool binding internally - do NOT pre-bind
        logger.info(
            f"Creating ReAct agent with {len(all_tools)} tools "
            f"({len(filesystem_tools)} filesystem, {len(self.additional_tools)} additional)"
        )

        # Log all tool names for debugging
        tool_names = [getattr(t, 'name', str(t)) for t in all_tools]
        logger.info(f"Tool names: {tool_names}")

        agent = create_react_agent(
            model=model,
            tools=all_tools,
            prompt=system_prompt,
            checkpointer=self.checkpointer,
            post_model_hook=post_hook,
        )

        return agent

    def _strip_thinking_hook(self, state: dict[str, Any]) -> dict[str, Any]:
        """Post-model hook to strip thinking tokens from responses.

        This hook is called after each model invocation to remove thinking blocks
        from the response content. Works with both string content and structured
        content blocks (Claude format).

        Args:
            state: Agent state dict containing messages.

        Returns:
            Modified state with thinking tokens removed.
        """
        messages = state.get("messages", [])
        if not messages:
            return state

        last_message = messages[-1]

        # Handle AIMessage with content attribute
        if isinstance(last_message, AIMessage):
            # Handle structured content (list of blocks)
            if isinstance(last_message.content, list):
                # Filter out thinking blocks
                filtered_content = [
                    block
                    for block in last_message.content
                    if not (hasattr(block, "type") and block.type == "thinking")
                ]
                last_message.content = filtered_content

            # Handle string content
            elif isinstance(last_message.content, str):
                last_message.content = self._strip_thinking_tokens(last_message.content)

        return state

    async def run(
        self,
        message: str,
        session_id: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Run the agent with a user message.

        Args:
            message: User input message.
            session_id: Session identifier for checkpointing.
            thread_id: Thread identifier for multi-turn conversations.

        Returns:
            Agent's response text with thinking tokens stripped.
        """
        # Set recursion_limit for multi-turn execution (2 supersteps per turn)
        config: dict[str, Any] = {"recursion_limit": self.max_turns * 2}

        if session_id or thread_id:
            config["configurable"] = {}
            if thread_id:
                config["configurable"]["thread_id"] = thread_id
            if session_id:
                config["configurable"]["session_id"] = session_id

        try:
            async with asyncio.timeout(self.timeout_seconds):
                result = await self._agent.ainvoke(
                    {"messages": [{"role": "user", "content": message}]},
                    config=config,
                )
        except TimeoutError:
            logger.warning(
                f"Agent timed out after {self.timeout_seconds}s "
                f"(workspace: {self.workspace.name})"
            )
            return (
                f"I ran out of time processing your request "
                f"(timeout: {int(self.timeout_seconds)}s). "
                f"Please try again with a simpler request."
            )

        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            raw_response = ""
            if hasattr(last_message, "content"):
                raw_response = str(last_message.content)
            else:
                raw_response = str(last_message)

            # Thinking tokens should already be stripped by hook, but apply fallback
            if self.strip_thinking and "<think>" in raw_response.lower():
                return self._strip_thinking_tokens(raw_response)
            return raw_response

        return ""

    def run_sync(
        self,
        message: str,
        session_id: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Synchronous version of run for non-async contexts.

        Returns:
            Agent's response text with thinking tokens stripped.
        """
        # Set recursion_limit for multi-turn execution (2 supersteps per turn)
        config: dict[str, Any] = {"recursion_limit": self.max_turns * 2}

        if session_id or thread_id:
            config["configurable"] = {}
            if thread_id:
                config["configurable"]["thread_id"] = thread_id
            if session_id:
                config["configurable"]["session_id"] = session_id

        result = self._agent.invoke(
            {"messages": [{"role": "user", "content": message}]},
            config=config,
        )

        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            raw_response = ""
            if hasattr(last_message, "content"):
                raw_response = str(last_message.content)
            else:
                raw_response = str(last_message)

            # Thinking tokens should already be stripped by hook, but apply fallback
            if self.strip_thinking and "<think>" in raw_response.lower():
                return self._strip_thinking_tokens(raw_response)
            return raw_response

        return ""
