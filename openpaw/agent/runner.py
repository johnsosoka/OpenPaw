"""Agent runner integrating LangGraph ReAct agent with OpenPaw workspace system."""

import asyncio
import logging
import time
from typing import Any

from langchain.agents import create_agent
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models import BaseChatModel

from openpaw.agent.builder import AgentBuilder
from openpaw.agent.middleware.approval import ApprovalRequiredError
from openpaw.agent.middleware.queue_aware import InterruptSignalError
from openpaw.agent.model_factory import THINKING_MODELS
from openpaw.agent.response_processor import ResponseProcessor
from openpaw.agent.tools.filesystem import FilesystemTools
from openpaw.core.prompts.system_events import (
    TIMEOUT_NOTIFICATION_GENERIC,
    TIMEOUT_NOTIFICATION_TEMPLATE,
)
from openpaw.core.workspace import AgentWorkspace

logger = logging.getLogger(__name__)


class AgentRunner:
    """Runs LangGraph agent with OpenPaw workspace configuration.

    Integrates:
    - Workspace-based system prompts (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
    - Sandboxed filesystem access for workspace operations
    - LangGraph checkpointing for multi-turn conversations
    - Automatic stripping of model thinking tokens (<thinking>...</thinking>)
    - Tool name validation for Bedrock compatibility
    - Streaming execution via astream() for behavioral parity with ainvoke()
    - Middleware support (thinking token stripping, queue awareness, approval gates)
    """

    @staticmethod
    def _strip_thinking_tokens(text: str) -> str:
        """Strip thinking tokens from string content (backward-compatible delegate).

        Handles edge cases where ThinkingTokenMiddleware doesn't catch
        <thinking> tags in string content.
        """
        return ResponseProcessor.strip_thinking_tokens(text)

    @staticmethod
    def _extract_text_from_content(content: Any) -> str:
        """Extract text from message content (backward-compatible delegate).

        Bedrock models return content as a list of typed blocks:
        [{"type": "thinking", ...}, {"type": "text", "text": "answer"}]
        """
        return ResponseProcessor.extract_text_from_content(content)

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
        channel_logging_enabled: bool = False,
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
            strip_thinking: Whether to strip <thinking> tokens from responses.
            timeout_seconds: Wall-clock timeout for agent invocations (default 5 minutes).
            enabled_builtins: List of enabled builtin tool names for conditional prompt sections.
            extra_model_kwargs: Additional kwargs to pass to init_chat_model
                (e.g., base_url for OpenAI-compatible APIs).
            middleware: Optional list of middleware functions for tool execution.
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
        self.channel_logging_enabled = channel_logging_enabled

        # Capture max_tokens for truncation detection after runs
        self._max_output_tokens: int | None = self.extra_model_kwargs.get("max_tokens")

        # Log label for distinguishing main agent from sub-agents.
        self._log_label: str = workspace.name

        # Per-invocation tracking (populated after each run)
        self._last_metrics: Any | None = None
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

        self._response_processor = ResponseProcessor(
            strip_thinking=self.strip_thinking,
            log_label=self._log_label,
            model_id=self.model_id,
        )

        self._builder = AgentBuilder(
            workspace=self.workspace,
            model_id=self.model_id,
            api_key=self.api_key,
            temperature=self.temperature,
            max_turns=self.max_turns,
            checkpointer=self.checkpointer,
            tools=self.additional_tools,
            region=self.region,
            strip_thinking=self.strip_thinking,
            enabled_builtins=self.enabled_builtins,
            extra_model_kwargs=self.extra_model_kwargs,
            middleware=self._middleware,
            channel_logging_enabled=self.channel_logging_enabled,
            create_agent_func=create_agent,
            filesystem_tools_cls=FilesystemTools,
        )
        self._agent = self._build_agent()

    @property
    def max_output_tokens(self) -> int | None:
        """Get the configured output token cap for this runner."""
        return self._max_output_tokens

    @property
    def last_metrics(self) -> Any | None:
        """Get token usage metrics from the most recent invocation."""
        return self._last_metrics

    @property
    def last_tools_used(self) -> list[str]:
        """Get list of tool names invoked during the most recent run."""
        return self._last_tools_used

    @property
    def model_instance(self) -> BaseChatModel | None:
        """Get the current model instance for profile access."""
        return getattr(self, '_model_instance', None)

    def update_checkpointer(self, checkpointer: Any) -> None:
        """Update the checkpointer and rebuild the agent graph."""
        self.checkpointer = checkpointer
        self._builder.checkpointer = checkpointer
        self._agent, self._model_instance = self._builder.build()
        logger.info(f"Updated checkpointer for workspace: {self.workspace.name}")

    def update_model(
        self,
        model: str,
        api_key: str | None = None,
        temperature: float | None = None,
    ) -> None:
        """Update model configuration and rebuild the agent graph.

        Conversation state is preserved (checkpointer is model-independent).
        """
        self.model_id = model
        if api_key is not None:
            self.api_key = api_key
        if temperature is not None:
            self.temperature = temperature

        # Re-check thinking model status
        self.strip_thinking = any(
            thinking_model in self.model_id.lower()
            for thinking_model in THINKING_MODELS
        )

        self._builder.model_id = self.model_id
        self._builder.api_key = self.api_key
        self._builder.temperature = self.temperature
        self._builder.strip_thinking = self.strip_thinking

        self._response_processor = ResponseProcessor(
            strip_thinking=self.strip_thinking,
            log_label=self._log_label,
            model_id=self.model_id,
        )

        self._agent, self._model_instance = self._builder.build()
        logger.info(f"Model updated to {model} for workspace: {self.workspace.name}")

    def rebuild_agent(self) -> None:
        """Reload workspace files and rebuild the agent graph."""
        self.workspace.reload_files()
        self._builder.workspace = self.workspace
        self._agent, self._model_instance = self._builder.build()
        logger.info(f"Rebuilt agent with fresh workspace files: {self.workspace.name}")

    async def get_context_info(self, thread_id: str) -> dict[str, Any]:
        """Get context window utilization for a conversation thread."""
        from langchain_core.messages.utils import count_tokens_approximately

        config = {"configurable": {"thread_id": thread_id}}
        state = await self._agent.aget_state(config)

        if not state or not state.values:
            return {
                "max_input_tokens": 0,
                "approximate_tokens": 0,
                "utilization": 0.0,
                "message_count": 0,
            }

        messages = state.values.get("messages", [])
        approx_tokens = count_tokens_approximately(
            messages, use_usage_metadata_scaling=True
        )

        max_input = 200000  # fallback
        if self._model_instance and hasattr(self._model_instance, 'profile') and self._model_instance.profile:
            max_input = self._model_instance.profile.get("max_input_tokens", 200000)

        return {
            "max_input_tokens": max_input,
            "approximate_tokens": approx_tokens,
            "utilization": approx_tokens / max_input if max_input > 0 else 0.0,
            "message_count": len(messages),
        }

    async def resolve_orphaned_tool_calls(
        self, thread_id: str, responses: dict[str, str] | None = None
    ) -> None:
        """Inject synthetic ToolMessages for orphaned tool_calls in checkpoint state.

        When approval middleware raises ApprovalRequiredError, LangGraph has already
        checkpointed an AIMessage with tool_calls but no corresponding ToolMessages.
        This creates an invalid state that OpenAI-compatible APIs reject.
        """
        if not self.checkpointer:
            return

        from langchain_core.messages import AIMessage, ToolMessage

        config = {"configurable": {"thread_id": thread_id}}
        state = await self._agent.aget_state(config)

        if not state or not state.values:
            return

        messages = state.values.get("messages", [])
        if not messages:
            return

        # Find the last AIMessage with tool_calls
        last_ai_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], AIMessage) and getattr(messages[i], "tool_calls", None):
                last_ai_idx = i
                break

        if last_ai_idx is None:
            return

        ai_msg = messages[last_ai_idx]
        tool_calls = ai_msg.tool_calls

        # Collect tool_call_ids that already have matching ToolMessages
        resolved_ids = set()
        for msg in messages[last_ai_idx + 1:]:
            if isinstance(msg, ToolMessage):
                resolved_ids.add(msg.tool_call_id)

        # Find orphaned tool_calls (no matching ToolMessage)
        orphaned = [tc for tc in tool_calls if tc.get("id") not in resolved_ids]

        if not orphaned:
            return

        responses = responses or {}
        synthetic_messages = []
        for tc in orphaned:
            tc_id = tc.get("id", "")
            content = responses.get(tc_id, "Tool execution was interrupted.")
            synthetic_messages.append(
                ToolMessage(content=content, tool_call_id=tc_id)
            )

        logger.info(
            f"Resolving {len(synthetic_messages)} orphaned tool call(s) "
            f"in thread {thread_id}"
        )

        # Inject synthetic ToolMessages as if they came from the "tools" node.
        await self._agent.aupdate_state(
            config, {"messages": synthetic_messages}, as_node="tools"
        )

    def _create_model(self) -> BaseChatModel:
        """Create the appropriate chat model based on provider.

        Thin wrapper around AgentBuilder.create_model() for backward compatibility.
        """
        return self._builder.create_model()

    def _build_agent(self) -> Any:
        """Build the LangGraph agent with workspace configuration.

        Backward-compatible wrapper that calls _create_model() first (to honor
        test patches), then delegates the rest of construction to AgentBuilder.
        """
        self._builder.additional_tools = self.additional_tools
        model = self._create_model()
        self._model_instance = model
        self._agent, _ = self._builder.build(model=model)
        return self._agent

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
            Agent's response text.
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
            final_messages = []
            async with asyncio.timeout(self.timeout_seconds):
                async for update in self._agent.astream(
                    {"messages": [{"role": "user", "content": message}]},
                    config=config,
                    stream_mode="updates",
                ):
                    if "model" in update:
                        messages_in_update = update["model"].get("messages", [])
                        final_messages.extend(messages_in_update)
                        for msg in messages_in_update:
                            tool_calls = getattr(msg, "tool_calls", [])
                            if tool_calls:
                                tool_names = [tc.get("name", "?") for tc in tool_calls]
                                logger.info(f"[{self._log_label}] Tool calls: {tool_names}")
                                self._current_tool_name = tool_calls[-1].get("name")
                            for tc in tool_calls:
                                if name := tc.get("name"):
                                    self._last_tools_used.append(name)
                    if "tools" in update:
                        self._current_tool_name = None
        except InterruptSignalError:
            raise
        except TimeoutError:
            duration_ms = (time.monotonic() - start_time) * 1000
            from openpaw.agent.metrics import extract_metrics_from_callback
            self._last_metrics = extract_metrics_from_callback(
                usage_callback, duration_ms, self.model_id
            )
            self._last_metrics.is_partial = True

            logger.warning(
                f"Agent timed out after {self.timeout_seconds}s "
                f"(workspace: {self._log_label})"
            )

            if self._current_tool_name:
                return TIMEOUT_NOTIFICATION_TEMPLATE.format(
                    timeout=int(self.timeout_seconds),
                    tool_name=self._current_tool_name,
                )
            return TIMEOUT_NOTIFICATION_GENERIC.format(
                timeout=int(self.timeout_seconds),
            )
        except ApprovalRequiredError:
            raise
        except Exception:
            raise

        # Extract metrics after successful invocation
        duration_ms = (time.monotonic() - start_time) * 1000
        from openpaw.agent.metrics import extract_metrics_from_callback
        self._last_metrics = extract_metrics_from_callback(
            usage_callback, duration_ms, self.model_id
        )

        # Warn when output token cap may have caused response truncation
        if self._max_output_tokens and self._last_metrics:
            if self._last_metrics.output_tokens >= self._max_output_tokens:
                logger.warning(
                    f"Output token cap reached: "
                    f"{self._last_metrics.output_tokens}/{self._max_output_tokens} tokens "
                    f"— response may be truncated (workspace: {self._log_label})"
                )

        # Extract response from final messages
        return self._response_processor.process(final_messages)

    def run_sync(
        self,
        message: str,
        session_id: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Synchronous version of run for non-async contexts.

        Returns:
            Agent's response text.
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
        return self._response_processor.process(messages)
