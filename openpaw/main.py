"""Workspace runner for OpenPaw."""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiosqlite
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from openpaw.approval.config import ApprovalGatesConfig
from openpaw.approval.manager import ApprovalGateManager
from openpaw.approval.middleware import ApprovalRequiredError, ApprovalToolMiddleware
from openpaw.builtins.base import BaseBuiltinProcessor
from openpaw.builtins.loader import BuiltinLoader
from openpaw.channels.base import ChannelAdapter, Message
from openpaw.channels.factory import create_channel
from openpaw.commands.base import CommandContext
from openpaw.commands.handlers import get_framework_commands
from openpaw.commands.router import CommandRouter
from openpaw.core.agent import AgentRunner
from openpaw.core.config import Config, merge_configs
from openpaw.core.logging import setup_workspace_logger
from openpaw.core.metrics import TokenUsageLogger
from openpaw.core.tool_middleware import InterruptSignalError, QueueAwareToolMiddleware
from openpaw.heartbeat.scheduler import HeartbeatScheduler
from openpaw.memory.archiver import ConversationArchiver
from openpaw.queue.lane import LaneQueue, QueueItem, QueueMode
from openpaw.queue.manager import QueueManager
from openpaw.session.manager import SessionManager
from openpaw.subagent.runner import SubAgentRunner
from openpaw.subagent.store import SubAgentStore
from openpaw.task.store import TaskStore
from openpaw.workspace.loader import WorkspaceLoader
from openpaw.workspace.tool_loader import load_workspace_tools

# Module-level logger (for general WorkspaceRunner class messages)
module_logger = logging.getLogger(__name__)


class WorkspaceRunner:
    """Manages a single agent workspace with channels, queues, and agents."""

    def __init__(self, config: Config, workspace_name: str):
        """Initialize WorkspaceRunner.

        Args:
            config: Application configuration.
            workspace_name: Name of the agent workspace to load.
        """
        self.config = config
        self.workspace_name = workspace_name

        # Set up workspace-specific logger if per-workspace logging is enabled
        if config.logging.per_workspace:
            self.logger = setup_workspace_logger(
                workspace_name=workspace_name,
                directory=config.logging.directory,
                max_size_mb=config.logging.max_size_mb,
                backup_count=config.logging.backup_count,
            )
        else:
            self.logger = logging.getLogger(f"{__name__}.{workspace_name}")

        self._workspace_loader = WorkspaceLoader(config.workspaces_path)

        # Load workspace-specific .env BEFORE workspace load so ${VAR} expansion works
        workspace_env = Path(config.workspaces_path) / workspace_name / ".env"
        if workspace_env.exists():
            load_dotenv(workspace_env, override=True)
            self.logger.info(f"Loaded environment from: {workspace_env}")

        self._workspace = self._workspace_loader.load(workspace_name)

        # Merge workspace config with global config if workspace has agent.yaml
        self._merged_config = self._merge_workspace_config(config, self._workspace)

        # Extract workspace timezone for builtin injection
        self._workspace_timezone: str = (
            self._workspace.config.timezone
            if self._workspace.config
            else "UTC"
        )

        # Initialize TaskStore for long-running task tracking
        self._task_store = TaskStore(self._workspace.path)
        self._cleanup_old_tasks()

        # Initialize SubAgentStore for sub-agent tracking
        self._subagent_store = SubAgentStore(self._workspace.path)

        # Initialize TokenUsageLogger for tracking token usage
        self._token_logger = TokenUsageLogger(self._workspace.path)

        self._lane_queue = LaneQueue(
            main_concurrency=config.lanes.main_concurrency,
            subagent_concurrency=config.lanes.subagent_concurrency,
            cron_concurrency=config.lanes.cron_concurrency,
        )

        # Use workspace queue config if available, otherwise fall back to global
        queue_config = self._merged_config.get("queue", {})
        self._queue_manager = QueueManager(
            lane_queue=self._lane_queue,
            default_mode=QueueMode(queue_config.get("mode", config.queue.mode)),
            default_debounce_ms=queue_config.get("debounce_ms", config.queue.debounce_ms),
            default_cap=queue_config.get("cap", config.queue.cap),
            default_drop_policy=queue_config.get("drop_policy", config.queue.drop_policy),
        )

        # Checkpointer lifecycle managed in start()/stop()
        # SQLite-backed persistence for durable conversations across restarts
        self._db_path = self._workspace.path / ".openpaw" / "conversations.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_conn: aiosqlite.Connection | None = None
        self._checkpointer: Any | None = None  # Initialized in start()

        # Initialize SessionManager for conversation tracking
        self._session_manager = SessionManager(self._workspace.path)

        # Initialize conversation archiver for persisting conversations
        self._conversation_archiver = ConversationArchiver(
            workspace_path=self._workspace.path,
            workspace_name=self.workspace_name,
            timezone=self._workspace_timezone,
        )

        # Initialize command router and register framework commands
        self._command_router = CommandRouter()
        self._register_framework_commands()

        # Load builtins for this workspace
        workspace_builtins_config = None
        if self._workspace.config and self._workspace.config.builtins:
            workspace_builtins_config = self._workspace.config.builtins

        # Get channel config for routing (needed by cron tool)
        workspace_channel_config = self._merged_config.get("channel", {})

        self._builtin_loader = BuiltinLoader(
            global_config=config.builtins,
            workspace_config=workspace_builtins_config,
            workspace_path=self._workspace.path,
            channel_config=workspace_channel_config,
            workspace_timezone=self._workspace_timezone,
            task_store=self._task_store,
        )

        # Load tools (LangChain tools for agent) and processors (message transformers)
        self._builtin_tools = self._builtin_loader.load_tools()
        self._processors: list[BaseBuiltinProcessor] = self._builtin_loader.load_processors()

        # Extract enabled builtin names for conditional system prompt sections
        self._enabled_builtin_names = self._builtin_loader.get_loaded_tool_names()

        if self._builtin_tools:
            self.logger.info(f"Loaded {len(self._builtin_tools)} builtin tools for workspace: {workspace_name}")
        if self._processors:
            self.logger.info(f"Loaded {len(self._processors)} builtin processors for workspace: {workspace_name}")

        # Load workspace-defined tools from tools/ directory
        self._workspace_tools = load_workspace_tools(self._workspace.tools_path)
        if self._workspace_tools:
            tool_names = [t.name for t in self._workspace_tools]
            self.logger.info(f"Loaded {len(self._workspace_tools)} workspace tools: {tool_names}")

        # Apply workspace tool filtering based on allow/deny lists
        if self._workspace_tools and self._workspace.config:
            self._workspace_tools = self._filter_workspace_tools(
                self._workspace_tools,
                self._workspace.config.workspace_tools
            )

        # Merge all tools: builtins + workspace tools
        all_tools = list(self._builtin_tools) + list(self._workspace_tools)

        # Create queue-aware middleware for steer/interrupt modes
        self._queue_middleware = QueueAwareToolMiddleware()

        # Create approval middleware if enabled
        self._approval_middleware = ApprovalToolMiddleware()
        self._approval_manager: ApprovalGateManager | None = None

        # Get approval gates config
        approval_config = self._get_approval_config()
        if approval_config and approval_config.enabled:
            self._approval_manager = ApprovalGateManager(approval_config)
            self.logger.info("Approval gates enabled")

        # Use merged model config for agent
        agent_config = self._merged_config.get("model", {})
        model_str = agent_config.get("model", config.agent.model)
        if agent_config.get("provider"):
            model_str = f"{agent_config['provider']}:{agent_config['model']}"

        self.logger.info(f"Initializing agent with model: {model_str}")

        # Extract extra model kwargs (anything not in the known set)
        known_model_keys = {"provider", "model", "api_key", "temperature", "max_turns", "region", "timeout_seconds"}
        extra_model_kwargs = {k: v for k, v in agent_config.items() if k not in known_model_keys and v is not None}

        if extra_model_kwargs:
            self.logger.info(f"Passing extra model kwargs: {list(extra_model_kwargs.keys())}")

        # AgentRunner auto-detects thinking models - no need for WorkspaceRunner to check
        middlewares = [self._queue_middleware.get_middleware()]
        if self._approval_manager:
            middlewares.append(self._approval_middleware.get_middleware())

        self._agent_runner = AgentRunner(
            workspace=self._workspace,
            model=model_str,
            api_key=agent_config.get("api_key", config.agent.api_key),
            max_turns=agent_config.get("max_turns", config.agent.max_turns),
            temperature=agent_config.get("temperature", config.agent.temperature),
            checkpointer=self._checkpointer,
            tools=all_tools if all_tools else None,
            region=agent_config.get("region"),
            timeout_seconds=agent_config.get("timeout_seconds", 300.0),
            enabled_builtins=self._enabled_builtin_names,
            extra_model_kwargs=extra_model_kwargs,
            middleware=middlewares,
        )

        self._channels: dict[str, ChannelAdapter] = {}
        self._cron_scheduler: Any = None
        self._heartbeat_scheduler: HeartbeatScheduler | None = None
        self._subagent_runner: SubAgentRunner | None = None
        self._queue_processor_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def token_logger(self) -> TokenUsageLogger:
        """Get the token usage logger for this workspace.

        Returns:
            TokenUsageLogger instance for reading/logging token usage.
        """
        return self._token_logger

    def _merge_workspace_config(self, global_config: Config, workspace: Any) -> dict[str, Any]:
        """Merge workspace config over global config.

        Args:
            global_config: Global OpenPaw configuration.
            workspace: Loaded AgentWorkspace with optional config.

        Returns:
            Merged configuration dictionary with workspace values taking precedence.
        """
        if not workspace.config:
            return {}

        # Convert global config relevant sections to dict
        global_dict: dict[str, Any] = {
            "model": {
                "provider": None,
                "model": global_config.agent.model,
                "api_key": global_config.agent.api_key,
                "temperature": global_config.agent.temperature,
                "max_turns": global_config.agent.max_turns,
                "region": None,
            },
            "queue": {
                "mode": global_config.queue.mode,
                "debounce_ms": global_config.queue.debounce_ms,
            },
        }

        # Convert workspace config to dict
        workspace_dict: dict[str, Any] = {}
        if workspace.config.model:
            model_dict = workspace.config.model.model_dump(exclude_none=True)
            if model_dict:
                workspace_dict["model"] = model_dict

        if workspace.config.queue:
            queue_dict = workspace.config.queue.model_dump(exclude_none=True)
            if queue_dict:
                workspace_dict["queue"] = queue_dict

        if workspace.config.channel:
            channel_dict = workspace.config.channel.model_dump(exclude_none=True)
            if channel_dict:
                workspace_dict["channel"] = channel_dict

        # Merge and return
        return merge_configs(global_dict, workspace_dict)

    def _register_framework_commands(self) -> None:
        """Register all framework command handlers."""
        for handler in get_framework_commands():
            self._command_router.register(handler)
        self.logger.info(
            f"Registered {len(self._command_router.list_commands(include_hidden=True))} framework commands"
        )

    def _get_approval_config(self) -> ApprovalGatesConfig | None:
        """Get approval gates config from workspace or global.

        Returns:
            ApprovalGatesConfig if enabled, None otherwise.
        """
        # Check workspace config first
        if self._workspace.config and self._workspace.config.approval_gates:
            if self._workspace.config.approval_gates.enabled:
                return self._workspace.config.approval_gates
        # Check global config
        if hasattr(self.config, "approval_gates") and self.config.approval_gates:
            if self.config.approval_gates.enabled:
                return self.config.approval_gates
        return None

    async def _handle_approval_resolution(
        self, approval_id: str, approved: bool
    ) -> None:
        """Handle approval resolution from channel callback.

        Args:
            approval_id: ID of the approval request.
            approved: Whether the user approved or denied.
        """
        if self._approval_manager:
            success = self._approval_manager.resolve(approval_id, approved)
            if success:
                self.logger.info(
                    f"Approval {approval_id}: {'approved' if approved else 'denied'}"
                )
            else:
                self.logger.warning(f"Failed to resolve approval {approval_id}")

    def _filter_workspace_tools(
        self,
        tools: list[Any],
        config: Any,
    ) -> list[Any]:
        """Filter workspace tools based on allow/deny lists.

        Args:
            tools: List of workspace tools to filter.
            config: WorkspaceToolsConfig with allow/deny lists.

        Returns:
            Filtered list of tools.
        """
        from openpaw.core.config import WorkspaceToolsConfig

        # Handle case where config might not be WorkspaceToolsConfig
        if not isinstance(config, WorkspaceToolsConfig):
            return tools

        deny = config.deny
        allow = config.allow

        # No filtering if both lists are empty
        if not deny and not allow:
            return tools

        filtered = []
        filtered_out = []

        for tool in tools:
            tool_name = tool.name

            # Deny takes precedence
            if deny and tool_name in deny:
                filtered_out.append(tool_name)
                continue

            # Allow list filtering (if populated)
            if allow and tool_name not in allow:
                filtered_out.append(tool_name)
                continue

            filtered.append(tool)

        if filtered_out:
            self.logger.info(f"Filtered out workspace tools: {filtered_out}")

        if filtered:
            tool_names = [t.name for t in filtered]
            self.logger.info(f"Active workspace tools after filtering: {tool_names}")

        return filtered

    def _cleanup_old_tasks(self) -> None:
        """Clean up old completed tasks from TaskStore on startup.

        Removes tasks older than 7 days that are in completed/failed/cancelled state.
        Logs count of active tasks remaining.
        """
        try:
            removed = self._task_store.cleanup_old_tasks(max_age_days=7)
            if removed > 0:
                self.logger.info(f"Cleaned up {removed} old task(s) from TaskStore")

            # Log count of active tasks
            from openpaw.task.store import TaskStatus

            active_tasks = self._task_store.list(status=TaskStatus.IN_PROGRESS)
            pending_tasks = self._task_store.list(status=TaskStatus.PENDING)
            awaiting_tasks = self._task_store.list(status=TaskStatus.AWAITING_CHECK)

            total_active = len(active_tasks) + len(pending_tasks) + len(awaiting_tasks)
            if total_active > 0:
                self.logger.info(
                    f"TaskStore has {total_active} active task(s) "
                    f"(pending: {len(pending_tasks)}, in_progress: {len(active_tasks)}, "
                    f"awaiting_check: {len(awaiting_tasks)})"
                )
        except FileNotFoundError:
            # TASKS.yaml doesn't exist yet - this is fine for new workspaces
            self.logger.debug("TaskStore file not found (new workspace)")
        except Exception as e:
            # Log warning but don't fail startup
            self.logger.warning(f"Failed to cleanup TaskStore: {e}")

    async def _setup_channels(self) -> None:
        """Initialize configured channels via factory."""
        workspace_channel = self._merged_config.get("channel", {})
        if not workspace_channel:
            raise ValueError(
                f"Workspace '{self.workspace_name}' must define channel configuration in agent.yaml"
            )

        channel_type = workspace_channel.get("type", "telegram")
        token = workspace_channel.get("token")
        if not token:
            raise ValueError(
                f"Workspace '{self.workspace_name}' must define channel.token in agent.yaml"
            )

        channel = create_channel(channel_type, workspace_channel, self.workspace_name)
        channel.on_message(self._handle_inbound_message)
        self._channels[channel_type] = channel
        await self._queue_manager.register_handler(channel_type, self._process_messages)

        # Log security mode (channel-type agnostic logging)
        allow_all = workspace_channel.get("allow_all", False)
        allowed_users = workspace_channel.get("allowed_users", [])
        allowed_groups = workspace_channel.get("allowed_groups", [])
        if allow_all:
            self.logger.warning(f"Workspace '{self.workspace_name}': allow_all=true (insecure mode)")
        elif allowed_users or allowed_groups:
            self.logger.info(
                f"Workspace '{self.workspace_name}': Allowlist mode "
                f"({len(allowed_users)} users, {len(allowed_groups)} groups)"
            )
        else:
            self.logger.warning(
                f"Workspace '{self.workspace_name}': Empty allowlist - all requests will be denied"
            )

        self.logger.info(f"Initialized {channel_type} channel for workspace: {self.workspace_name}")

    def _build_command_context(self, message: Message) -> CommandContext:
        """Build command execution context for the current message.

        Args:
            message: The incoming message that triggered the command.

        Returns:
            CommandContext populated with current runtime state.
        """
        channel = self._channels.get(message.channel)
        if not channel:
            raise RuntimeError(f"No channel found for message.channel: {message.channel}")
        return CommandContext(
            channel=channel,
            session_manager=self._session_manager,
            checkpointer=self._checkpointer,
            agent_runner=self._agent_runner,
            workspace_name=self.workspace_name,
            workspace_path=self._workspace.path,
            queue_manager=self._queue_manager,
            command_router=self._command_router,
            workspace_timezone=self._workspace_timezone,
            conversation_archiver=self._conversation_archiver,
        )

    async def _handle_inbound_message(self, message: Message) -> None:
        """Handle an inbound message from any channel."""
        # Check for framework commands BEFORE processors modify content
        # (TimestampProcessor prepends [Current time: ...] which breaks is_command)
        if message.is_command:
            context = self._build_command_context(message)
            command_result = await self._command_router.route(message, context)
            if command_result and command_result.handled:
                if command_result.response:
                    channel = self._channels.get(message.channel)
                    if channel:
                        await channel.send_message(message.session_key, command_result.response)
                return
            # Unknown command — fall through to processors and queue

        # Process through inbound processors (e.g., Whisper transcription, timestamps)
        processed_message = message
        for processor in self._processors:
            try:
                result = await processor.process_inbound(processed_message)
                processed_message = result.message
                if result.skip_agent:
                    self.logger.debug(f"Processor {processor.metadata.name} handled message, skipping agent")
                    return
            except Exception as e:
                self.logger.error(f"Processor {processor.metadata.name} failed: {e}")

        content_preview = processed_message.content[:50] if processed_message.content else "(empty)"
        self.logger.info(f"Received message from {processed_message.channel}: {content_preview}...")

        await self._queue_manager.submit(
            session_key=processed_message.session_key,
            channel_name=processed_message.channel,
            message=processed_message,
        )

    async def _process_messages(self, session_key: str, messages: list[Message]) -> None:
        """Process collected messages for a session with followup, steer, and interrupt support."""
        combined_content = "\n".join(m.content for m in messages)
        thread_id = self._session_manager.get_thread_id(session_key)
        channel_name = session_key.split(":")[0]
        channel = self._channels.get(channel_name)
        followup_depth = 0
        max_followup_depth = 5

        while True:
            # Capture steer state before finally block resets it
            steered = False
            steer_messages = None

            try:
                # Set queue awareness on middleware before each run
                session_queue = await self._queue_manager._get_or_create_session(session_key)
                self._queue_middleware.set_queue_awareness(
                    queue_manager=self._queue_manager,
                    session_key=session_key,
                    queue_mode=session_queue.mode,
                )

                # Set approval context on middleware before each run
                if self._approval_manager:
                    self._approval_middleware.set_context(
                        manager=self._approval_manager,
                        session_key=session_key,
                        thread_id=thread_id,
                    )

                # Set session context for send_message tool
                if channel:
                    self._connect_send_message_tool(channel, session_key)

                # Set followup chain depth
                followup_tool = self._builtin_loader.get_tool_instance("followup")
                if followup_tool:
                    followup_tool.set_chain_depth(followup_depth)

                response = await self._agent_runner.run(
                    message=combined_content,
                    thread_id=thread_id,
                )

                # Capture steer state BEFORE reset
                steered = self._queue_middleware.was_steered
                steer_messages = self._queue_middleware.pending_steer_message

                # Log token usage for this invocation
                if self._agent_runner.last_metrics:
                    self._token_logger.log(
                        metrics=self._agent_runner.last_metrics,
                        workspace=self.workspace_name,
                        invocation_type="user",
                        session_key=session_key,
                    )

                if channel:
                    if response and response.strip():
                        await channel.send_message(session_key, response)
                        self._session_manager.increment_message_count(session_key)
                        await self._send_pending_audio(channel, session_key)
                    else:
                        self.logger.warning(f"Agent produced empty response for {session_key}, sending fallback")
                        fallback = "I processed your message but my response was empty. Please try again."
                        await channel.send_message(session_key, fallback)

            except ApprovalRequiredError as e:
                # APPROVAL MODE: Tool requires user approval
                # Log partial metrics if available
                if self._agent_runner.last_metrics:
                    self._token_logger.log(
                        metrics=self._agent_runner.last_metrics,
                        workspace=self.workspace_name,
                        invocation_type="user",
                        session_key=session_key,
                    )

                # Send approval request to user
                if channel and self._approval_manager:
                    tool_config = self._approval_manager.get_tool_config(e.tool_name)
                    show_args = tool_config.show_args if tool_config else True
                    await channel.send_approval_request(
                        session_key=session_key,
                        approval_id=e.approval_id,
                        tool_name=e.tool_name,
                        tool_args=e.tool_args,
                        show_args=show_args,
                    )

                    # Wait for user approval
                    approved = await self._approval_manager.wait_for_resolution(
                        e.approval_id
                    )

                    if approved:
                        # Re-run: the agent will re-invoke the tool
                        self.logger.info(f"Tool {e.tool_name} approved, resuming")
                        # The approval is already resolved, middleware will let it through
                        # We need to continue the loop to re-run with same message
                        continue  # Re-enter loop with same message
                    else:
                        # User denied - send denial to agent as system message
                        self.logger.info(f"Tool {e.tool_name} denied")
                        await channel.send_message(
                            session_key,
                            f"Tool '{e.tool_name}' was denied. "
                            f"The agent will be informed.",
                        )
                        # Send denial to agent as tool result
                        combined_content = (
                            f"[SYSTEM] The tool '{e.tool_name}' was denied by "
                            f"the user. Do not retry this action."
                        )
                        continue  # Re-enter with denial message

                # No channel available, deny by default
                break

            except InterruptSignalError as e:
                # INTERRUPT MODE: Run was aborted
                # Log partial metrics if available
                if self._agent_runner.last_metrics:
                    self._token_logger.log(
                        metrics=self._agent_runner.last_metrics,
                        workspace=self.workspace_name,
                        invocation_type="user",
                        session_key=session_key,
                    )

                # Notify user that run was interrupted
                if channel:
                    await channel.send_message(session_key, "[Run interrupted — processing new message]")

                # Use the pending messages as the new input
                pending_msgs = e.pending_messages
                if pending_msgs:
                    # Extract message content from the pending messages
                    # pending_msgs format: list of (channel_name, Message) tuples
                    new_contents = []
                    for _channel_name, msg in pending_msgs:
                        if hasattr(msg, 'content'):
                            new_contents.append(msg.content)
                        else:
                            new_contents.append(str(msg))
                    combined_content = "\n".join(new_contents)

                followup_depth = 0  # Reset followup depth on interrupt
                continue  # Re-enter loop with new message

            except Exception as e:
                self.logger.error(f"Error processing messages for {session_key}: {e}", exc_info=True)
                if channel:
                    await channel.send_message(session_key, f"Error: {e}")
                break  # Don't continue followup chain on error

            finally:
                self._disconnect_send_message_tool()
                # Note: Steer state (steered flag + steer_messages) is captured into local
                # variables BEFORE this finally block. Middleware reset MUST happen after
                # state capture because middleware state is per-invocation.
                self._queue_middleware.reset()  # Always reset middleware state
                if self._approval_manager:
                    self._approval_middleware.reset()

            # Check steer (captured before reset)
            if steered and steer_messages:
                new_contents = []
                for _channel_name, msg in steer_messages:
                    if hasattr(msg, 'content'):
                        new_contents.append(msg.content)
                    else:
                        new_contents.append(str(msg))
                combined_content = "\n".join(new_contents)
                followup_depth = 0  # Reset followup depth on steer
                self.logger.info(f"Steer redirect: processing {len(steer_messages)} new message(s)")
                continue

            # Check for followup request
            if followup_tool:
                followup = followup_tool.get_pending_followup()
                if followup and followup.delay_seconds == 0:
                    followup_depth += 1
                    if followup_depth > max_followup_depth:
                        self.logger.warning(
                            f"Followup chain depth exceeded ({max_followup_depth}) "
                            f"for session {session_key}"
                        )
                        break

                    self.logger.info(
                        f"Processing immediate followup (depth={followup_depth}): "
                        f"{followup.prompt[:100]}"
                    )
                    combined_content = f"[SYSTEM FOLLOWUP - depth {followup_depth}]\n{followup.prompt}"
                    continue
                elif followup and followup.delay_seconds > 0:
                    self.logger.info(
                        f"Scheduling delayed followup ({followup.delay_seconds}s): "
                        f"{followup.prompt[:100]}"
                    )
                    self._schedule_delayed_followup(followup, session_key)

            break  # No followup or delayed followup scheduled, exit loop

        # Reset followup state after loop exits (cleanup stale state from errors)
        followup_tool = self._builtin_loader.get_tool_instance("followup")
        if followup_tool:
            followup_tool.reset()

    async def _send_pending_audio(self, channel: ChannelAdapter, session_key: str) -> None:
        """Check for and send any pending TTS audio."""
        if not hasattr(channel, "send_audio"):
            return

        try:
            from openpaw.builtins.tools.elevenlabs_tts import ElevenLabsTTSTool

            audio_data = ElevenLabsTTSTool.get_any_pending_audio()
            if audio_data:
                await channel.send_audio(session_key, audio_data, filename="response.mp3")
                self.logger.info(f"Sent TTS audio to {session_key}")
        except ImportError:
            pass  # ElevenLabs not available
        except Exception as e:
            self.logger.error(f"Failed to send TTS audio: {e}")

    def _schedule_delayed_followup(self, followup: Any, session_key: str) -> None:
        """Schedule a delayed followup via the cron system."""
        from datetime import UTC, datetime, timedelta

        cron_tool = self._builtin_loader.get_tool_instance("cron")
        if not cron_tool or not cron_tool.scheduler:
            self.logger.warning("Cannot schedule delayed followup: no cron tool/scheduler available")
            return

        if not cron_tool.default_chat_id:
            self.logger.warning("Cannot schedule delayed followup: cron tool has no default_chat_id")
            return

        run_at = datetime.now(UTC) + timedelta(seconds=followup.delay_seconds)
        from openpaw.cron.dynamic import create_once_task

        task = create_once_task(
            prompt=followup.prompt,
            run_at=run_at,
            channel=cron_tool.default_channel,
            chat_id=cron_tool.default_chat_id,
        )
        cron_tool.store.add_task(task)
        cron_tool._add_to_live_scheduler(task)
        self.logger.info(f"Delayed followup scheduled as cron task {task.id}")

    async def _queue_processor(self) -> None:
        """Background task processing the lane queue."""
        async def handler(item: QueueItem) -> None:
            channel_name, messages = item.payload
            handler_func = self._queue_manager._handlers.get(channel_name)
            if handler_func:
                await handler_func(item.session_key, messages)

        await self._lane_queue.process("main", handler)

    async def start(self) -> None:
        """Start workspace runner."""
        self.logger.info(f"Starting workspace runner: {self.workspace_name}")

        # Initialize SQLite checkpointer for durable conversations
        self._db_conn = await aiosqlite.connect(str(self._db_path))
        self._checkpointer = AsyncSqliteSaver(self._db_conn)
        await self._checkpointer.setup()
        self._agent_runner.update_checkpointer(self._checkpointer)
        self.logger.info(f"Initialized SQLite checkpointer: {self._db_path}")

        await self._setup_channels()

        for name, channel in self._channels.items():
            await channel.start()
            self.logger.info(f"Started channel: {name}")

        # Connect approval callback to channels
        if self._approval_manager:
            for channel in self._channels.values():
                if hasattr(channel, "on_approval"):
                    channel.on_approval(self._handle_approval_resolution)

        # Start cron scheduler if workspace has cron definitions OR CronTool is loaded
        cron_tool_loaded = self._builtin_loader.get_tool_instance("cron") is not None
        if self._workspace.crons or cron_tool_loaded:
            await self._setup_cron_scheduler()

        # Start heartbeat scheduler if enabled
        await self._setup_heartbeat_scheduler()

        # Start sub-agent runner
        self._subagent_runner = SubAgentRunner(
            agent_factory=self._create_agent_factory(),
            store=self._subagent_store,
            channels=self._channels,
            token_logger=self._token_logger,
            workspace_name=self.workspace_name,
            max_concurrent=8,  # Could come from config later
        )
        # Connect SpawnTool to SubAgentRunner
        self._connect_spawn_tool_to_runner()

        self._running = True

        self._queue_processor_task = asyncio.create_task(self._queue_processor())

        self.logger.info(f"Workspace runner '{self.workspace_name}' is running")

    def _create_agent_factory(self) -> Callable[[], AgentRunner]:
        """Create an agent factory closure for stateless scheduler usage.

        Returns a factory function that creates fresh AgentRunner instances
        without checkpointers (stateless) but with the same configuration,
        tools, and system prompt as the main agent.

        Used by both cron and heartbeat schedulers to spawn isolated agent runs.

        Returns:
            Callable that returns a fresh AgentRunner instance.
        """
        def agent_factory() -> AgentRunner:
            """Factory to create fresh agent instances for scheduled tasks."""
            tools = list(self._builtin_tools) + list(self._workspace_tools)
            return AgentRunner(
                workspace=self._workspace,
                model=self._agent_runner.model_id,
                api_key=self._agent_runner.api_key,
                max_turns=self._agent_runner.max_turns,
                temperature=self._agent_runner.temperature,
                checkpointer=None,  # No checkpointer for scheduled tasks
                tools=tools if tools else None,
                region=self._agent_runner.region,
                strip_thinking=self._agent_runner.strip_thinking,
                timeout_seconds=self._agent_runner.timeout_seconds,
                enabled_builtins=self._enabled_builtin_names,
                extra_model_kwargs=self._agent_runner.extra_model_kwargs,
                middleware=[],  # No queue awareness for stateless scheduler agents
            )
        return agent_factory

    async def _setup_cron_scheduler(self) -> None:
        """Initialize and start cron scheduler if workspace has cron jobs."""
        try:
            from openpaw.cron.scheduler import CronScheduler

            self._cron_scheduler = CronScheduler(
                workspace_path=self._workspace.path,
                agent_factory=self._create_agent_factory(),
                channels=self._channels,
                token_logger=self._token_logger,
                workspace_name=self.workspace_name,
                timezone=self._workspace_timezone,
            )

            await self._cron_scheduler.start()
            self.logger.info(f"Started cron scheduler with {len(self._workspace.crons)} jobs")

            # Connect CronTool to live scheduler for dynamic task scheduling
            self._connect_cron_tool_to_scheduler()

        except ImportError as e:
            self.logger.warning(f"Cron scheduler not available: {e}")
        except Exception as e:
            self.logger.error(f"Failed to start cron scheduler: {e}", exc_info=True)

    def _connect_cron_tool_to_scheduler(self) -> None:
        """Connect CronTool builtin to the live CronScheduler.

        This enables dynamic task scheduling - when agents create tasks,
        they're immediately added to the running scheduler.
        """
        try:
            cron_tool = self._builtin_loader.get_tool_instance("cron")
            if cron_tool:
                cron_tool.set_scheduler(self._cron_scheduler)
                self.logger.info("Connected CronTool to live scheduler")
            else:
                self.logger.debug("CronTool not loaded for this workspace")
        except Exception as e:
            self.logger.warning(f"Failed to connect CronTool to scheduler: {e}")

    def _connect_spawn_tool_to_runner(self) -> None:
        """Connect SpawnTool builtin to the live SubAgentRunner.

        This enables sub-agent spawning - when agents spawn background tasks,
        they're immediately executed via the runner.
        """
        try:
            spawn_tool = self._builtin_loader.get_tool_instance("spawn")
            if spawn_tool:
                spawn_tool.set_runner(self._subagent_runner)
                self.logger.info("Connected SpawnTool to SubAgentRunner")
            else:
                self.logger.debug("SpawnTool not loaded for this workspace")
        except Exception as e:
            self.logger.warning(f"Failed to connect SpawnTool to runner: {e}")

    def _connect_send_message_tool(self, channel: Any, session_key: str) -> None:
        """Connect send_message tool to active session context.

        Called before each agent run to enable mid-execution messaging.

        Args:
            channel: The channel instance for sending messages.
            session_key: The session key for routing.
        """
        try:
            send_message_tool = self._builtin_loader.get_tool_instance("send_message")
            if send_message_tool:
                send_message_tool.set_session_context(channel, session_key)
                self.logger.debug(f"Connected send_message tool for session: {session_key}")
        except Exception as e:
            self.logger.debug(f"Failed to connect send_message tool: {e}")

    def _disconnect_send_message_tool(self) -> None:
        """Disconnect send_message tool from session context.

        Called after each agent run completes.
        """
        try:
            send_message_tool = self._builtin_loader.get_tool_instance("send_message")
            if send_message_tool:
                send_message_tool.clear_session_context()
                self.logger.debug("Disconnected send_message tool")
        except Exception as e:
            self.logger.debug(f"Failed to disconnect send_message tool: {e}")

    async def _setup_heartbeat_scheduler(self) -> None:
        """Initialize and start heartbeat scheduler if enabled in workspace config.

        Heartbeat is purely per-workspace. No global fallback.
        Only starts if workspace config defines heartbeat.enabled = True.
        """
        # Get heartbeat config from workspace only - no global fallback
        if not self._workspace.config or not self._workspace.config.heartbeat:
            return

        heartbeat_config = self._workspace.config.heartbeat
        if not heartbeat_config.enabled:
            return

        try:
            self._heartbeat_scheduler = HeartbeatScheduler(
                workspace_name=self.workspace_name,
                workspace_path=self._workspace.path,
                agent_factory=self._create_agent_factory(),
                channels=self._channels,
                config=heartbeat_config,
                timezone=self._workspace_timezone,
                token_logger=self._token_logger,
            )

            await self._heartbeat_scheduler.start()
            self.logger.info(
                f"Started heartbeat scheduler (interval: {heartbeat_config.interval_minutes}min)"
            )

        except Exception as e:
            self.logger.error(f"Failed to start heartbeat scheduler: {e}", exc_info=True)

    async def _archive_active_conversations(self) -> None:
        """Archive all active conversations on shutdown.

        Archives each active session's conversation to markdown + JSON files.
        Errors are logged but don't prevent clean shutdown.
        """
        if not self._checkpointer or not hasattr(self, '_conversation_archiver'):
            return

        sessions = self._session_manager.list_sessions()
        if not sessions:
            self.logger.debug("No active sessions to archive on shutdown")
            return

        archived_count = 0
        for session_key, state in sessions.items():
            try:
                thread_id = f"{session_key}:{state.conversation_id}"
                archive = await self._conversation_archiver.archive(
                    checkpointer=self._checkpointer,
                    thread_id=thread_id,
                    session_key=session_key,
                    conversation_id=state.conversation_id,
                    tags=["shutdown"],
                )
                if archive:
                    archived_count += 1
                    self.logger.debug(
                        f"Archived conversation {state.conversation_id} ({archive.message_count} messages)"
                    )
            except Exception as e:
                self.logger.warning(f"Failed to archive conversation {state.conversation_id}: {e}", exc_info=True)

        if archived_count > 0:
            self.logger.info(f"Archived {archived_count} conversation(s) on shutdown")

    async def stop(self) -> None:
        """Stop workspace runner gracefully."""
        self.logger.info(f"Stopping workspace runner: {self.workspace_name}")
        self._running = False

        # Cancel queue processor task
        if self._queue_processor_task:
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                pass
            self._queue_processor_task = None

        # Stop cron scheduler if running
        if self._cron_scheduler:
            await self._cron_scheduler.stop()
            self.logger.info("Stopped cron scheduler")

        # Stop heartbeat scheduler if running
        if self._heartbeat_scheduler:
            await self._heartbeat_scheduler.stop()
            self.logger.info("Stopped heartbeat scheduler")

        # Shutdown sub-agent runner (cancel active sub-agents)
        if self._subagent_runner:
            await self._subagent_runner.shutdown()
            self.logger.info("Stopped sub-agent runner")

        for name, channel in self._channels.items():
            await channel.stop()
            self.logger.info(f"Stopped channel: {name}")

        # Cleanup approval manager
        if self._approval_manager:
            await self._approval_manager.cleanup()
            self.logger.info("Cleaned up approval manager")

        # Archive all active conversations before closing DB
        await self._archive_active_conversations()

        # Close SQLite checkpointer connection
        if self._db_conn:
            await self._db_conn.close()
            self._db_conn = None
            self.logger.info("Closed checkpointer database connection")

        self.logger.info(f"Workspace runner '{self.workspace_name}' stopped")
