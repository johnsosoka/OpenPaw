"""Workspace runner for OpenPaw."""

import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from openpaw.agent.metrics import TokenUsageLogger
from openpaw.agent.middleware import (
    ApprovalToolMiddleware,
    QueueAwareToolMiddleware,
    ToolTimeoutMiddleware,
)
from openpaw.agent.session_logger import SessionLogger
from openpaw.builtins.base import BaseBuiltinProcessor
from openpaw.builtins.loader import BuiltinLoader
from openpaw.channels.base import ChannelAdapter
from openpaw.channels.commands.base import CommandContext
from openpaw.channels.commands.handlers import get_framework_commands
from openpaw.channels.commands.router import CommandRouter
from openpaw.core.config import Config, merge_configs
from openpaw.core.config.models import ApprovalGatesConfig, ToolTimeoutsConfig
from openpaw.core.logging import setup_workspace_logger
from openpaw.model.message import Message, MessageDirection
from openpaw.runtime.queue.lane import LaneQueue, QueueItem, QueueMode
from openpaw.runtime.queue.manager import QueueManager
from openpaw.runtime.session.archiver import ConversationArchiver
from openpaw.runtime.session.manager import SessionManager
from openpaw.runtime.subagent import SubAgentRunner
from openpaw.stores.approval import ApprovalGateManager
from openpaw.stores.subagent import SubAgentStore
from openpaw.stores.task import TaskStore
from openpaw.workspace.agent_factory import AgentFactory, filter_workspace_tools
from openpaw.workspace.lifecycle import LifecycleManager
from openpaw.workspace.loader import WorkspaceLoader
from openpaw.workspace.message_processor import MessageProcessor
from openpaw.workspace.tool_loader import load_workspace_tools


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

        # Merge workspace config with global config
        self._merged_config = self._merge_workspace_config(config, self._workspace)

        # Extract workspace timezone
        self._workspace_timezone: str = (
            self._workspace.config.timezone
            if self._workspace.config
            else "UTC"
        )

        # Initialize stores
        self._task_store = TaskStore(self._workspace.path)
        self._cleanup_old_tasks()
        self._subagent_store = SubAgentStore(self._workspace.path)
        self._token_logger = TokenUsageLogger(self._workspace.path)

        # Initialize queue system
        self._lane_queue = LaneQueue(
            main_concurrency=config.lanes.main_concurrency,
            subagent_concurrency=config.lanes.subagent_concurrency,
            cron_concurrency=config.lanes.cron_concurrency,
        )

        queue_config = self._merged_config.get("queue", {})
        self._queue_manager = QueueManager(
            lane_queue=self._lane_queue,
            default_mode=QueueMode(queue_config.get("mode", config.queue.mode)),
            default_debounce_ms=queue_config.get("debounce_ms", config.queue.debounce_ms),
            default_cap=queue_config.get("cap", config.queue.cap),
            default_drop_policy=queue_config.get("drop_policy", config.queue.drop_policy),
        )

        # Checkpointer (initialized in start())
        self._db_path = self._workspace.path / ".openpaw" / "conversations.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_conn: aiosqlite.Connection | None = None
        self._checkpointer: Any | None = None

        # Session and archiving
        self._session_manager = SessionManager(self._workspace.path)

        # Memory search infrastructure (vector store + indexer)
        self._vector_store: Any | None = None
        self._embedding_provider: Any | None = None
        self._indexer: Any | None = None

        memory_config = self._workspace.config.memory if self._workspace.config else None
        if memory_config and memory_config.enabled:
            try:
                from openpaw.stores.vector.factory import (
                    create_embedding_provider,
                    create_vector_store,
                )
                from openpaw.stores.vector.indexer import ConversationIndexer

                # Create vector store
                self._vector_store = create_vector_store(
                    provider=memory_config.vector_store.provider,
                    config=memory_config.vector_store.model_dump(),
                    workspace_path=self._workspace.path,
                )

                # Create embedding provider
                embedding_config = memory_config.embedding.model_dump()
                self._embedding_provider = create_embedding_provider(
                    provider=memory_config.embedding.provider,
                    config=embedding_config,
                )

                # Create indexer
                self._indexer = ConversationIndexer(
                    vector_store=self._vector_store,
                    embedding_provider=self._embedding_provider,
                )

                self.logger.info("Memory search infrastructure initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize memory search: {e}")
                self._vector_store = None
                self._embedding_provider = None
                self._indexer = None

        # Initialize conversation archiver with optional indexer
        self._conversation_archiver = ConversationArchiver(
            workspace_path=self._workspace.path,
            workspace_name=self.workspace_name,
            timezone=self._workspace_timezone,
            indexer=self._indexer,
        )

        # Command routing
        self._command_router = CommandRouter()
        self._register_framework_commands()

        # Load builtins
        workspace_builtins_config = None
        if self._workspace.config and self._workspace.config.builtins:
            workspace_builtins_config = self._workspace.config.builtins

        workspace_channel_config = self._merged_config.get("channel", {})
        self._user_aliases: dict[int, str] = workspace_channel_config.get("user_aliases", {})

        self._builtin_loader = BuiltinLoader(
            global_config=config.builtins,
            workspace_config=workspace_builtins_config,
            workspace_path=self._workspace.path,
            channel_config=workspace_channel_config,
            workspace_timezone=self._workspace_timezone,
            task_store=self._task_store,
        )

        self._builtin_tools = self._builtin_loader.load_tools()
        self._processors: list[BaseBuiltinProcessor] = self._builtin_loader.load_processors()
        self._enabled_builtin_names = self._builtin_loader.get_loaded_tool_names()

        if self._builtin_tools:
            self.logger.info(f"Loaded {len(self._builtin_tools)} builtin tools for workspace: {workspace_name}")
        if self._processors:
            self.logger.info(f"Loaded {len(self._processors)} builtin processors for workspace: {workspace_name}")

        # Load workspace tools
        self._workspace_tools = load_workspace_tools(self._workspace.tools_path)
        if self._workspace_tools:
            tool_names = [t.name for t in self._workspace_tools]
            self.logger.info(f"Loaded {len(self._workspace_tools)} workspace tools: {tool_names}")

        # Apply workspace tool filtering
        if self._workspace_tools and self._workspace.config:
            self._workspace_tools = filter_workspace_tools(
                self._workspace_tools,
                self._workspace.config.workspace_tools,
                self.logger,
            )

        # Create middleware
        self._queue_middleware = QueueAwareToolMiddleware()
        self._approval_middleware = ApprovalToolMiddleware()
        self._approval_manager: ApprovalGateManager | None = None

        approval_config = self._get_approval_config()
        if approval_config and approval_config.enabled:
            self._approval_manager = ApprovalGateManager(approval_config)
            self.logger.info("Approval gates enabled")

        # Build agent configuration
        agent_config = self._merged_config.get("model", {})
        model_str = agent_config.get("model", config.agent.model)
        if agent_config.get("provider"):
            model_str = f"{agent_config['provider']}:{agent_config['model']}"

        self.logger.info(f"Initializing agent with model: {model_str}")

        # Extract extra model kwargs
        known_model_keys = {"provider", "model", "api_key", "temperature", "max_turns", "region", "timeout_seconds"}
        extra_model_kwargs = {k: v for k, v in agent_config.items() if k not in known_model_keys and v is not None}

        if extra_model_kwargs:
            self.logger.info(f"Passing extra model kwargs: {list(extra_model_kwargs.keys())}")

        # Create tool timeout middleware
        tool_timeouts_config = self._get_tool_timeouts_config()
        self._tool_timeout_middleware = ToolTimeoutMiddleware(tool_timeouts_config)

        # Build middleware list (order matters: timeout → queue → approval)
        middlewares = [
            self._tool_timeout_middleware.get_middleware(),
            self._queue_middleware.get_middleware(),
        ]
        if self._approval_manager:
            middlewares.append(self._approval_middleware.get_middleware())

        # Create agent factory
        self._agent_factory = AgentFactory(
            workspace=self._workspace,
            model=model_str,
            api_key=agent_config.get("api_key", config.agent.api_key),
            max_turns=agent_config.get("max_turns", config.agent.max_turns),
            temperature=agent_config.get("temperature", config.agent.temperature),
            region=agent_config.get("region"),
            timeout_seconds=agent_config.get("timeout_seconds", 300.0),
            builtin_tools=self._builtin_tools,
            workspace_tools=self._workspace_tools,
            enabled_builtin_names=self._enabled_builtin_names,
            extra_model_kwargs=extra_model_kwargs,
            middleware=middlewares,
            logger=self.logger,
        )

        # Create initial agent (will be updated with checkpointer in start())
        self._agent_runner = self._agent_factory.create_agent(checkpointer=None)

        # Create message processor
        self._message_processor = MessageProcessor(
            agent_runner=self._agent_runner,
            session_manager=self._session_manager,
            queue_manager=self._queue_manager,
            builtin_loader=self._builtin_loader,
            queue_middleware=self._queue_middleware,
            approval_middleware=self._approval_middleware,
            approval_manager=self._approval_manager,
            workspace_name=self.workspace_name,
            token_logger=self._token_logger,
            logger=self.logger,
            conversation_archiver=self._conversation_archiver,
            auto_compact_config=self._workspace.config.auto_compact if self._workspace.config else None,
            user_aliases=workspace_channel_config.get("user_aliases", {}),
        )

        # Create lifecycle manager
        self._lifecycle_manager = LifecycleManager(
            workspace_name=self.workspace_name,
            workspace_path=self._workspace.path,
            workspace_config=self._workspace.config,
            merged_config=self._merged_config,
            config=config,
            queue_manager=self._queue_manager,
            message_handler=self._handle_inbound_message,
            queue_handler=self._process_messages,
            builtin_loader=self._builtin_loader,
            workspace_timezone=self._workspace_timezone,
            session_manager=self._session_manager,
            approval_handler=self._handle_approval_resolution,
            logger=self.logger,
            result_callback=self._inject_system_event,
        )

        self._channels: dict[str, ChannelAdapter] = {}
        self._subagent_runner: SubAgentRunner | None = None
        self._queue_processor_task: asyncio.Task[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def token_logger(self) -> TokenUsageLogger:
        """Get the token usage logger for this workspace."""
        return self._token_logger

    def _merge_workspace_config(self, global_config: Config, workspace: Any) -> dict[str, Any]:
        """Merge workspace config over global config."""
        if not workspace.config:
            return {}

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

        return merge_configs(global_dict, workspace_dict)

    def _register_framework_commands(self) -> None:
        """Register all framework command handlers."""
        for handler in get_framework_commands():
            self._command_router.register(handler)
        self.logger.info(
            f"Registered {len(self._command_router.list_commands(include_hidden=True))} framework commands"
        )

    def _get_approval_config(self) -> ApprovalGatesConfig | None:
        """Get approval gates config from workspace or global."""
        if self._workspace.config and self._workspace.config.approval_gates:
            if self._workspace.config.approval_gates.enabled:
                return self._workspace.config.approval_gates
        if hasattr(self.config, "approval_gates") and self.config.approval_gates:
            if self.config.approval_gates.enabled:
                return self.config.approval_gates
        return None

    def _get_tool_timeouts_config(self) -> ToolTimeoutsConfig:
        """Get tool timeouts config from workspace or global.

        Returns:
            ToolTimeoutsConfig (always returns a valid config, uses defaults if not configured).
        """
        if self._workspace.config:
            return self._workspace.config.tool_timeouts
        return self.config.tool_timeouts

    async def _handle_approval_resolution(
        self, approval_id: str, approved: bool
    ) -> None:
        """Handle approval resolution from channel callback."""
        if self._approval_manager:
            success = self._approval_manager.resolve(approval_id, approved)
            if success:
                self.logger.info(
                    f"Approval {approval_id}: {'approved' if approved else 'denied'}"
                )
            else:
                self.logger.warning(f"Failed to resolve approval {approval_id}")

    def _cleanup_old_tasks(self) -> None:
        """Clean up old completed tasks from TaskStore on startup."""
        try:
            removed = self._task_store.cleanup_old_tasks(max_age_days=3, stale_threshold_hours=48)
            if removed > 0:
                self.logger.info(f"Cleaned up {removed} old task(s) from TaskStore")

            from openpaw.model.task import TaskStatus

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
            self.logger.debug("TaskStore file not found (new workspace)")
        except Exception as e:
            self.logger.warning(f"Failed to cleanup TaskStore: {e}")

    def _build_command_context(self, message: Message) -> CommandContext:
        """Build command execution context for the current message."""
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
            browser_builtin=self._get_browser_builtin(),
            task_store=self._task_store,
            subagent_store=self._subagent_store,
            agent_factory=self._agent_factory,
        )

    async def _handle_inbound_message(self, message: Message) -> None:
        """Handle an inbound message from any channel."""
        # Check for framework commands first
        if message.is_command:
            context = self._build_command_context(message)
            command_result = await self._command_router.route(message, context)
            if command_result and command_result.handled:
                if command_result.response:
                    channel = self._channels.get(message.channel)
                    if channel:
                        await channel.send_message(message.session_key, command_result.response)

                # Rebuild agent on conversation rotation (/new, /compact)
                # so the agent picks up any workspace file changes (AGENT.md, etc.)
                if command_result.new_thread_id:
                    self._agent_runner.rebuild_agent()
                    # Prime the new session with orientation message
                    user_name = self._resolve_user_name(message)
                    await self._inject_new_session_prompt(
                        message.session_key, user_name=user_name
                    )

                return

        # Notify user if slow processing is expected (Docling OCR, Whisper transcription)
        if self._processors and message.attachments:
            await self._notify_processing_start(message)

        # Process through inbound processors
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
        """Process collected messages for a session."""
        channel_name = session_key.split(":")[0]
        channel = self._channels.get(channel_name)
        await self._message_processor.process_messages(session_key, messages, channel)

    async def _queue_processor(self) -> None:
        """Background task processing the lane queue."""
        async def handler(item: QueueItem) -> None:
            channel_name, messages = item.payload
            handler_func = self._queue_manager._handlers.get(channel_name)
            if handler_func:
                await handler_func(item.session_key, messages)

        await self._lane_queue.process("main", handler)

    async def _periodic_task_cleanup(self) -> None:
        """Run task cleanup every 6 hours."""
        while self._running:
            await asyncio.sleep(6 * 3600)  # 6 hours
            if not self._running:
                break
            try:
                removed = self._task_store.cleanup_old_tasks(max_age_days=3, stale_threshold_hours=48)
                if removed > 0:
                    self.logger.info(f"Periodic cleanup: removed {removed} old/stale tasks")
            except Exception as e:
                self.logger.warning(f"Periodic task cleanup failed: {e}")

    async def start(self) -> None:
        """Start workspace runner."""
        self.logger.info(f"Starting workspace runner: {self.workspace_name}")

        # Initialize SQLite checkpointer
        self._db_conn = await aiosqlite.connect(str(self._db_path))
        self._checkpointer = AsyncSqliteSaver(self._db_conn)
        await self._checkpointer.setup()
        self._agent_runner.update_checkpointer(self._checkpointer)
        self.logger.info(f"Initialized SQLite checkpointer: {self._db_path}")

        # Initialize vector store if memory search is enabled
        if self._vector_store:
            await self._vector_store.initialize()
            self.logger.info("Vector store initialized")

        # Wire memory search tool
        self._connect_memory_search_tool()

        # Setup channels
        self._channels = await self._lifecycle_manager.setup_channels()
        await self._lifecycle_manager.start_channels()

        # Start schedulers if needed
        cron_tool_loaded = self._builtin_loader.get_tool_instance("cron") is not None
        if self._workspace.crons or cron_tool_loaded:
            agent_factory = self._agent_factory.get_agent_factory_closure()
            await self._lifecycle_manager.setup_cron_scheduler(
                self._workspace.crons,
                agent_factory,
                self._token_logger,
            )

        await self._lifecycle_manager.setup_heartbeat_scheduler(
            self._agent_factory.get_agent_factory_closure(),
            self._token_logger,
        )

        # Start sub-agent runner
        subagent_session_logger = SessionLogger(self._workspace.path, session_type="subagent")
        self._subagent_runner = SubAgentRunner(
            agent_factory=self._agent_factory.get_agent_factory_closure(),
            store=self._subagent_store,
            channels=self._channels,
            token_logger=self._token_logger,
            workspace_name=self.workspace_name,
            max_concurrent=8,
            result_callback=self._inject_system_event,
            session_logger=subagent_session_logger,
        )
        self._connect_spawn_tool_to_runner()

        self._running = True
        self._queue_processor_task = asyncio.create_task(self._queue_processor())
        self._cleanup_task = asyncio.create_task(self._periodic_task_cleanup())

        self.logger.info(f"Workspace runner '{self.workspace_name}' is running")

        # Lifecycle notification: startup
        lifecycle = self._workspace.config.lifecycle if self._workspace.config else None
        if lifecycle and lifecycle.notify_startup:
            await self._notify_lifecycle("Started")

    def _connect_spawn_tool_to_runner(self) -> None:
        """Connect SpawnTool builtin to the live SubAgentRunner."""
        try:
            spawn_tool = self._builtin_loader.get_tool_instance("spawn")
            if spawn_tool:
                spawn_tool.set_runner(self._subagent_runner)
                self.logger.info("Connected SpawnTool to SubAgentRunner")
            else:
                self.logger.debug("SpawnTool not loaded for this workspace")
        except Exception as e:
            self.logger.warning(f"Failed to connect SpawnTool to runner: {e}")

    def _connect_memory_search_tool(self) -> None:
        """Connect MemorySearchTool builtin to vector store and embedding provider."""
        try:
            memory_tool = self._builtin_loader.get_tool_instance("memory_search")
            if memory_tool and self._vector_store and self._embedding_provider:
                memory_tool.set_context(self._vector_store, self._embedding_provider)
                self.logger.info("Connected MemorySearchTool to vector store")
            elif memory_tool:
                self.logger.debug("MemorySearchTool loaded but vector store not initialized")
            else:
                self.logger.debug("MemorySearchTool not loaded for this workspace")
        except Exception as e:
            self.logger.warning(f"Failed to connect MemorySearchTool: {e}")

    def _resolve_user_name(self, message: Message) -> str:
        """Resolve display name for a message's user from aliases or metadata."""
        if self._user_aliases:
            try:
                name = self._user_aliases.get(int(message.user_id))
                if name:
                    return name
            except (ValueError, TypeError):
                pass

        first_name = message.metadata.get("first_name")
        if first_name:
            return str(first_name)

        return "Unknown"

    async def _inject_new_session_prompt(
        self, session_key: str, user_name: str = "Unknown"
    ) -> None:
        """Inject a new-session orientation message with USER.md re-injection.

        Re-surfaces user context as a user-turn message, giving the model
        a second attention pass over the user identity (double prompting).

        Args:
            session_key: The session to inject into.
            user_name: Display name of the user who started the session.
        """
        from openpaw.core.prompts.system_events import NEW_SESSION_TEMPLATE

        user_context = self._workspace.user_md or "No user context available."
        content = NEW_SESSION_TEMPLATE.format(
            user_context=user_context, user_name=user_name
        )
        await self._inject_system_event(session_key, content)

    async def _inject_system_event(self, session_key: str, content: str) -> None:
        """Inject a system event into the queue for agent processing."""
        parts = session_key.split(":", 1)
        if len(parts) != 2 or not parts[0]:
            self.logger.error(f"Invalid session_key format for system event: {session_key}")
            return

        channel_name = parts[0]

        try:
            msg = Message(
                id=f"system-{uuid4().hex[:8]}",
                channel=channel_name,
                session_key=session_key,
                user_id="system",
                content=content,
                direction=MessageDirection.INBOUND,
            )

            await self._queue_manager.submit(
                session_key=session_key,
                channel_name=channel_name,
                message=msg,
                mode=QueueMode.COLLECT,
                steer_eligible=False,
            )

            self.logger.info(f"Injected system event into queue for session: {session_key}")

        except Exception as e:
            self.logger.error(
                f"Failed to inject system event for {session_key}: {e}",
                exc_info=True,
            )

    async def _notify_processing_start(self, message: Message) -> None:
        """Notify user that file processing is starting (Docling, Whisper, etc.).

        Only sends if attachments match processor-supported types. Best-effort.
        """
        from pathlib import Path

        doc_extensions = {".pdf", ".docx", ".pptx", ".xlsx"}
        audio_types = {"audio", "voice"}

        has_documents = False
        has_audio = False
        for att in message.attachments:
            if att.type in audio_types:
                has_audio = True
            elif att.filename:
                ext = Path(att.filename).suffix.lower()
                if ext in doc_extensions:
                    has_documents = True

        if not has_documents and not has_audio:
            return

        parts = []
        if has_documents:
            parts.append("Converting document")
        if has_audio:
            parts.append("Transcribing audio")
        notice = f"{' and '.join(parts)}... this may take a moment."

        channel = self._channels.get(message.channel)
        if channel:
            try:
                await channel.send_message(message.session_key, notice)
            except Exception as e:
                self.logger.debug(f"Failed to send processing notification: {e}")

    def _get_browser_builtin(self) -> Any | None:
        """Get the browser builtin instance if loaded."""
        return self._builtin_loader.get_tool_instance("browser")

    async def _notify_lifecycle(self, event: str, detail: str | None = None) -> None:
        """Send a lifecycle notification to all channels.

        Args:
            event: Event name (startup, shutdown, auto_compact).
            detail: Optional detail message.
        """
        message = f"[{self.workspace_name}] {event}"
        if detail:
            message += f": {detail}"

        for channel in self._channels.values():
            try:
                # Send to first allowed user in each channel
                allowed_users = getattr(channel, '_allowed_users', [])
                if allowed_users:
                    session_key = f"{channel.name}:{allowed_users[0]}"
                    await channel.send_message(session_key, message)
            except Exception as e:
                self.logger.debug(f"Failed to send lifecycle notification via {channel}: {e}")

    async def _archive_active_conversations(self) -> None:
        """Archive all active conversations on shutdown."""
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

        # Lifecycle notification: shutdown
        lifecycle = self._workspace.config.lifecycle if self._workspace.config else None
        if lifecycle and lifecycle.notify_shutdown:
            await self._notify_lifecycle("Shutting down")

        # Cancel queue processor
        if self._queue_processor_task:
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                pass
            self._queue_processor_task = None

        # Stop periodic cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        # Stop schedulers
        await self._lifecycle_manager.stop_cron_scheduler()
        await self._lifecycle_manager.stop_heartbeat_scheduler()

        # Shutdown sub-agent runner
        if self._subagent_runner:
            await self._subagent_runner.shutdown()
            self.logger.info("Stopped sub-agent runner")

        # Close browser session
        browser_builtin = self._get_browser_builtin()
        if browser_builtin:
            await browser_builtin.cleanup()
            self.logger.info("Closed browser session")

        # Stop channels
        await self._lifecycle_manager.stop_channels()

        # Cleanup approval manager
        if self._approval_manager:
            await self._approval_manager.cleanup()
            self.logger.info("Cleaned up approval manager")

        # Archive conversations
        await self._archive_active_conversations()

        # Close vector store
        if self._vector_store:
            await self._vector_store.close()
            self.logger.info("Closed vector store connection")

        # Close database
        if self._db_conn:
            await self._db_conn.close()
            self._db_conn = None
            self.logger.info("Closed checkpointer database connection")

        self.logger.info(f"Workspace runner '{self.workspace_name}' stopped")
