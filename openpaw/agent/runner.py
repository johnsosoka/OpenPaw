"""Agent runner integrating LangGraph ReAct agent with OpenPaw workspace system."""

import asyncio
import logging
import re
import time
from typing import Any

from langchain.agents import create_agent
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models import BaseChatModel

from openpaw.agent.metrics import InvocationMetrics, extract_metrics_from_callback
from openpaw.agent.middleware.llm_hooks import THINKING_TAG_PATTERN, ThinkingTokenMiddleware
from openpaw.agent.middleware.queue_aware import InterruptSignalError
from openpaw.agent.tools.filesystem import FilesystemTools
from openpaw.core.prompts.system_events import (
    TIMEOUT_NOTIFICATION_GENERIC,
    TIMEOUT_NOTIFICATION_TEMPLATE,
)
from openpaw.core.timezone import workspace_now
from openpaw.workspace.loader import AgentWorkspace

logger = logging.getLogger(__name__)

# Models known to produce thinking tokens
THINKING_MODELS = [
    "moonshot.kimi-k2-thinking",
    "moonshotai.kimi-k2.5",
    "kimi-k2-thinking",
    "kimi-thinking",
    "kimi-k2.5",
]

# Bedrock tool name validation pattern (AWS requirement)
BEDROCK_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
MAX_TOOL_NAME_LENGTH = 64


class AgentRunner:
    """Runs LangGraph agent with OpenPaw workspace configuration.

    Integrates:
    - Workspace-based system prompts (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
    - Sandboxed filesystem access for workspace operations
    - LangGraph checkpointing for multi-turn conversations
    - Automatic stripping of model thinking tokens (<think>...</think>)
    - Tool name validation for Bedrock compatibility
    - Streaming execution via astream() for behavioral parity with ainvoke()
    - Middleware support (thinking token stripping, queue awareness, approval gates)
    """

    @staticmethod
    def _strip_thinking_tokens(text: str) -> str:
        """Strip thinking tokens from string content (fallback).

        Handles edge cases where ThinkingTokenMiddleware doesn't catch
        <think>...</think> tags in string content.
        """
        cleaned = THINKING_TAG_PATTERN.sub("", text)
        return cleaned.strip()

    @staticmethod
    def _extract_text_from_content(content: Any) -> str:
        """Extract text from message content, handling both string and structured formats.

        Bedrock models return content as a list of typed blocks:
        [{"type": "thinking", ...}, {"type": "text", "text": "answer"}]

        Blocks may be dicts or objects with type/text attributes.

        Returns:
            Extracted text content, or empty string if no text blocks found.
        """
        if not isinstance(content, list):
            return str(content)

        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    text_parts.append(block["text"])
            elif hasattr(block, "type") and hasattr(block, "text"):
                if getattr(block, "type") == "text" and getattr(block, "text"):
                    text_parts.append(block.text)
        return "\n".join(text_parts)

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
        extra_model_kwargs: dict[str, Any] | None = None,
        middleware: list[Any] | None = None,
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
            extra_model_kwargs: Additional kwargs to pass to init_chat_model
                (e.g., base_url for OpenAI-compatible APIs).
            middleware: Optional list of middleware functions for tool execution
                (e.g., queue-aware middleware for steer/interrupt modes).
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
        self.extra_model_kwargs = extra_model_kwargs or {}
        self._middleware = middleware or []

        # Per-invocation tracking (populated after each run)
        self._last_metrics: InvocationMetrics | None = None
        self._last_tools_used: list[str] = []
        self._current_tool_name: str | None = None

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

    @property
    def last_metrics(self) -> InvocationMetrics | None:
        """Get token usage metrics from the most recent invocation.

        Returns:
            InvocationMetrics from the last run() call, or None if no invocations yet.
        """
        return self._last_metrics

    @property
    def last_tools_used(self) -> list[str]:
        """Get list of tool names invoked during the most recent run.

        Returns:
            List of tool name strings (may contain duplicates if called multiple times).
        """
        return self._last_tools_used

    def update_checkpointer(self, checkpointer: Any) -> None:
        """Update the checkpointer and rebuild the agent graph.

        Used for deferred initialization when checkpointer requires async setup.

        Args:
            checkpointer: New checkpointer instance (e.g., AsyncSqliteSaver).
        """
        self.checkpointer = checkpointer
        self._agent = self._build_agent()
        logger.info(f"Updated checkpointer for workspace: {self.workspace.name}")

    def rebuild_agent(self) -> None:
        """Reload workspace files and rebuild the agent graph.

        Call this after conversation rotation (/new, /compact) so the agent
        picks up any changes the agent made to its own workspace files
        (AGENT.md, HEARTBEAT.md, etc.) during the previous conversation.
        """
        self.workspace.reload_files()
        self._agent = self._build_agent()
        logger.info(f"Rebuilt agent with fresh workspace files: {self.workspace.name}")

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

    def _create_model(self) -> BaseChatModel:
        """Create the appropriate chat model based on provider.

        Directly instantiates provider-specific classes instead of using
        init_chat_model, which silently drops kwargs like extra_body.

        Supported providers: openai, anthropic, bedrock_converse.

        Returns:
            Configured BaseChatModel instance.

        Raises:
            ValueError: If provider is not supported.
        """
        # Parse provider from model_id (format: "provider:model_name")
        if ":" in self.model_id:
            provider, model_name = self.model_id.split(":", 1)
        else:
            provider = "openai"
            model_name = self.model_id

        # Build kwargs common to all providers
        kwargs: dict[str, Any] = {
            "model": model_name,
            "temperature": self.temperature,
        }

        # Merge extra kwargs from config (base_url, model_kwargs, extra_body, etc.)
        kwargs.update(self.extra_model_kwargs)

        # Flatten model_kwargs into direct constructor args so that params like
        # extra_body reach the provider class directly instead of being silently dropped
        nested_model_kwargs = kwargs.pop("model_kwargs", None)
        if nested_model_kwargs and isinstance(nested_model_kwargs, dict):
            kwargs.update(nested_model_kwargs)

        if provider == "openai":
            from langchain_openai import ChatOpenAI

            if self.api_key:
                kwargs["api_key"] = self.api_key
            logger.info(f"Creating ChatOpenAI: model={model_name}, kwargs={list(kwargs.keys())}")
            return ChatOpenAI(**kwargs)

        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            if self.api_key:
                kwargs["api_key"] = self.api_key
            logger.info(f"Creating ChatAnthropic: model={model_name}")
            return ChatAnthropic(**kwargs)

        if provider in ("bedrock_converse", "bedrock"):
            from langchain_aws import ChatBedrockConverse

            if self.region:
                kwargs["region_name"] = self.region
            # Bedrock uses AWS credentials, not api_key
            kwargs.pop("api_key", None)
            logger.info(f"Creating ChatBedrockConverse: model={model_name}, kwargs_keys={list(kwargs.keys())}")
            return ChatBedrockConverse(**kwargs)

        raise ValueError(
            f"Unsupported model provider: '{provider}'. "
            f"Supported: openai, anthropic, bedrock_converse"
        )

    def _build_agent(self) -> Any:
        """Build the LangGraph agent with workspace configuration.

        Creates an agent with:
        - Direct provider-specific model instantiation
        - Sandboxed filesystem tools for workspace access
        - Workspace-specific tools from tools/ directory
        - System prompt from workspace markdown files
        - Empty middleware list (populated in future sprints for steer/interrupt)
        - Thinking token stripping handled via fallback logic in run()
        """
        # 1. Initialize model directly via provider class
        model = self._create_model()

        # 2. Create FilesystemTools for workspace
        workspace_root = self.workspace.path.resolve()
        if not workspace_root.exists():
            raise ValueError(f"Workspace does not exist: {workspace_root}")
        if not workspace_root.is_dir():
            raise ValueError(f"Workspace is not a directory: {workspace_root}")

        logger.debug(f"Sandboxing agent to workspace: {workspace_root}")

        # Get timezone from workspace config, defaulting to UTC
        timezone = self.workspace.config.timezone if self.workspace.config else "UTC"

        fs_tools_manager = FilesystemTools(workspace_root=workspace_root, timezone=timezone)
        filesystem_tools = fs_tools_manager.get_tools()

        # 3. Combine all tools (filesystem + additional tools)
        all_tools = filesystem_tools + self.additional_tools

        # 4. Validate tool names (especially important for Bedrock)
        if "bedrock" in self.model_id.lower():
            logger.debug("Validating tool names for Bedrock compatibility")
            self._validate_tool_names(all_tools)

        # 5. Get system prompt from workspace (with dynamic current date)
        try:
            timezone = getattr(self.workspace.config, "timezone", "UTC") if self.workspace.config else "UTC"
            current_dt = workspace_now(timezone).strftime("%A, %Y-%m-%d %H:%M %Z")
        except (TypeError, AttributeError):
            current_dt = None
        system_prompt = self.workspace.build_system_prompt(
            enabled_builtins=self.enabled_builtins,
            current_datetime=current_dt,
        )

        # 6. Wire middleware in dependency order:
        #    - ThinkingTokenMiddleware (first): strips reasoning before other middleware sees it
        #    - Custom middleware (after): queue-aware, approval gates, etc.
        if self.strip_thinking:
            middleware = [ThinkingTokenMiddleware(), *self._middleware]
        else:
            middleware = list(self._middleware)

        # 7. Call create_agent (successor to create_react_agent)
        # Note: create_agent handles tool binding internally - do NOT pre-bind
        logger.info(
            f"Creating agent with {len(all_tools)} tools "
            f"({len(filesystem_tools)} filesystem, {len(self.additional_tools)} additional)"
        )

        # Log all tool names for debugging
        tool_names = [getattr(t, 'name', str(t)) for t in all_tools]
        logger.info(f"Tool names: {tool_names}")

        agent = create_agent(
            model=model,
            tools=all_tools,
            system_prompt=system_prompt,
            checkpointer=self.checkpointer,
            middleware=middleware,  # Thinking tokens + steer/interrupt + approval gates
        )

        return agent

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
            Agent's response text. Thinking tokens are stripped by ThinkingTokenMiddleware
            in the agent graph. Fallback stripping handles edge cases.
        """
        # Reset per-invocation tracking
        self._last_metrics = None
        self._last_tools_used = []
        self._current_tool_name = None

        # Set recursion_limit for multi-turn execution (2 supersteps per turn)
        config: dict[str, Any] = {"recursion_limit": self.max_turns * 2}

        if session_id or thread_id:
            config["configurable"] = {}
            if thread_id:
                config["configurable"]["thread_id"] = thread_id
            if session_id:
                config["configurable"]["session_id"] = session_id

        # Create fresh callback handler for token tracking
        usage_callback = UsageMetadataCallbackHandler()
        config["callbacks"] = [usage_callback]

        # Track invocation duration
        start_time = time.monotonic()

        try:
            # Use astream with stream_mode="updates" for behavioral parity with ainvoke
            # Collect all messages from the stream
            final_messages = []
            async with asyncio.timeout(self.timeout_seconds):
                async for update in self._agent.astream(
                    {"messages": [{"role": "user", "content": message}]},
                    config=config,
                    stream_mode="updates",
                ):
                    # Updates come as: {"model": {"messages": [...]}} from create_agent v2
                    if "model" in update:
                        messages_in_update = update["model"].get("messages", [])
                        final_messages.extend(messages_in_update)
                        # Capture tool names from AI messages with tool_calls
                        for msg in messages_in_update:
                            tool_calls = getattr(msg, "tool_calls", [])
                            if tool_calls:
                                tool_names = [tc.get("name", "?") for tc in tool_calls]
                                logger.debug(f"Model called tools: {tool_names}")
                                # Track last tool called for timeout reporting
                                self._current_tool_name = tool_calls[-1].get("name")
                            for tc in tool_calls:
                                if name := tc.get("name"):
                                    self._last_tools_used.append(name)
                    # Clear current tool tracking when we see tool results
                    if "tools" in update:
                        self._current_tool_name = None
        except InterruptSignalError:
            # Re-raise for WorkspaceRunner to handle
            raise
        except TimeoutError:
            # Extract partial metrics even on timeout
            duration_ms = (time.monotonic() - start_time) * 1000
            self._last_metrics = extract_metrics_from_callback(
                usage_callback, duration_ms, self.model_id
            )
            self._last_metrics.is_partial = True

            logger.warning(
                f"Agent timed out after {self.timeout_seconds}s "
                f"(workspace: {self.workspace.name})"
            )

            # Use rich notification if we know what tool was executing
            if self._current_tool_name:
                return TIMEOUT_NOTIFICATION_TEMPLATE.format(
                    timeout=int(self.timeout_seconds),
                    tool_name=self._current_tool_name,
                )
            else:
                return TIMEOUT_NOTIFICATION_GENERIC.format(
                    timeout=int(self.timeout_seconds),
                )
        except Exception as e:
            # Re-raise ApprovalRequiredError for WorkspaceRunner to handle
            if type(e).__name__ == "ApprovalRequiredError":
                raise
            # Re-raise any other exception
            raise

        # Extract metrics after successful invocation
        duration_ms = (time.monotonic() - start_time) * 1000
        self._last_metrics = extract_metrics_from_callback(
            usage_callback, duration_ms, self.model_id
        )

        # Extract response from final messages
        if final_messages:
            last_message = final_messages[-1]
            if hasattr(last_message, "content"):
                raw_response = self._extract_text_from_content(last_message.content)
            else:
                raw_response = str(last_message)

            # Fallback: strip <think> tags from string content if middleware missed them
            if self.strip_thinking and "<think>" in raw_response.lower():
                logger.warning(
                    f"Fallback thinking stripping triggered "
                    f"(workspace: {self.workspace.name}, model: {self.model_id})"
                )
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
            Agent's response text. Thinking tokens are stripped by ThinkingTokenMiddleware
            in the agent graph. Fallback stripping handles edge cases.
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
            if hasattr(last_message, "content"):
                raw_response = self._extract_text_from_content(last_message.content)
            else:
                raw_response = str(last_message)

            if self.strip_thinking and "<think>" in raw_response.lower():
                logger.warning(
                    f"Fallback thinking stripping triggered "
                    f"(workspace: {self.workspace.name}, model: {self.model_id})"
                )
                return self._strip_thinking_tokens(raw_response)
            return raw_response

        return ""
