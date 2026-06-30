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
from openpaw.agent.session_logger import SessionLogger
from openpaw.builtins.loader import BuiltinLoader
from openpaw.channels.base import ChannelAdapter
from openpaw.channels.commands.base import CommandContext
from openpaw.channels.commands.handlers import get_framework_commands
from openpaw.channels.commands.router import CommandRouter
from openpaw.core.channel_context import format_channel_context
from openpaw.core.config import Config
from openpaw.core.logging import setup_workspace_logger
from openpaw.core.paths import CONVERSATIONS_DB, DOT_ENV, TEAM_DIR
from openpaw.core.utils import resolve_user_name
from openpaw.model.message import Message, MessageDirection
from openpaw.model.spawn_profile import SpawnProfile
from openpaw.runtime.mcp.manager import MCPManager
from openpaw.runtime.queue.lane import LaneQueue, QueueItem, QueueMode
from openpaw.runtime.queue.manager import QueueManager
from openpaw.runtime.session.manager import SessionManager
from openpaw.runtime.subagent import SubAgentRunner
from openpaw.workspace.connector import BuiltinToolConnector
from openpaw.workspace.initializer import WorkspaceInitializer
from openpaw.workspace.lifecycle import LifecycleManager
from openpaw.workspace.lifecycle_notifier import _notify_lifecycle_impl
from openpaw.workspace.loader import WorkspaceLoader
from openpaw.workspace.profile_loader import load_spawn_profiles
from openpaw.workspace.profile_resolver import SpawnProfileResolver
from openpaw.workspace.roster import TeamRosterBuilder
from openpaw.workspace.task_service import TaskMaintenanceService
from openpaw.workspace.tool_loader import load_workspace_tools  # noqa: F401


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

        # Load workspace and merge configuration
        workspace_root = Path(config.workspaces_path) / workspace_name
        self._workspace_loader = WorkspaceLoader(config.workspaces_path)
        workspace_env = workspace_root / str(DOT_ENV)
        if workspace_env.exists():
            load_dotenv(workspace_env, override=False)
            self.logger.info(f"Loaded environment from: {workspace_env}")
        self._workspace = self._workspace_loader.load(workspace_name)
        self._merged_config = WorkspaceInitializer.merge_workspace_config(
            config, self._workspace
        )
        self._workspace_timezone: str = (
            self._workspace.config.timezone if self._workspace.config else "UTC"
        )

        # Initialize persistence stores and token logger
        self._initializer = WorkspaceInitializer(
            config=config,
            workspace=self._workspace,
            merged_config=self._merged_config,
            logger=self.logger,
        )
        self._task_store, self._subagent_store, self._token_logger = (
            self._initializer.init_stores()
        )

        # Initialize task maintenance service
        self._task_service = TaskMaintenanceService(self._task_store, self.logger)
        self._task_service.cleanup_old_tasks()

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
            default_debounce_ms=queue_config.get(
                "debounce_ms", config.queue.debounce_ms
            ),
            default_cap=queue_config.get("cap", config.queue.cap),
            default_drop_policy=queue_config.get(
                "drop_policy", config.queue.drop_policy
            ),
        )

        # Checkpointer placeholder (initialized in start())
        self._db_path = self._workspace.path / str(CONVERSATIONS_DB)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_conn: aiosqlite.Connection | None = None
        self._checkpointer: Any | None = None

        # MCP manager (config-only at this point; I/O happens in start())
        self._mcp_manager: MCPManager | None = None
        if self._workspace.config and self._workspace.config.mcp.enabled:
            self._mcp_manager = MCPManager(self._workspace.config.mcp, workspace_name)

        # Session manager
        self._session_manager = SessionManager(self._workspace.path)

        # Memory search infrastructure and conversation archiver
        (
            self._vector_store,
            self._embedding_provider,
            self._indexer,
            self._conversation_archiver,
        ) = self._initializer.init_memory()

        # Command routing
        self._command_router = CommandRouter()
        self._register_framework_commands()

        # Builtin tools, processors, and workspace tools
        workspace_builtins_config = None
        if self._workspace.config and self._workspace.config.builtins:
            workspace_builtins_config = self._workspace.config.builtins

        workspace_channel_config = (
            self._merged_config.get("channels") or [{}]
        )[0]

        builtin_loader = BuiltinLoader(
            global_config=self.config.builtins,
            workspace_config=workspace_builtins_config,
            workspace_path=self._workspace.path,
            channel_config=workspace_channel_config,
            workspace_timezone=self._workspace_timezone,
            task_store=self._task_store,
        )
        (
            self._builtin_loader,
            self._builtin_tools,
            self._processors,
            self._workspace_tools,
            self._enabled_builtin_names,
            self._user_aliases,
            self._channel_logging_enabled,
        ) = self._initializer.init_builtins(
            self._task_store,
            builtin_loader=builtin_loader,
        )

        # Middleware, agent factory, agent runner, and message processor
        (
            self._queue_middleware,
            self._approval_middleware,
            self._approval_manager,
            self._agent_factory,
            self._agent_runner,
            self._message_processor,
            self._tool_timeout_middleware,
            self._status_reminder_middleware,
            self._status_update_middleware,
        ) = self._initializer.init_agent(
            builtin_loader=self._builtin_loader,
            builtin_tools=self._builtin_tools,
            workspace_tools=self._workspace_tools,
            enabled_builtin_names=self._enabled_builtin_names,
            user_aliases=self._user_aliases,
            token_logger=self._token_logger,
            conversation_archiver=self._conversation_archiver,
            session_manager=self._session_manager,
            queue_manager=self._queue_manager,
            channel_logging_enabled=self._channel_logging_enabled,
        )

        # Tool connector (channels updated in start())
        self._tool_connector = BuiltinToolConnector(
            builtin_loader=self._builtin_loader,
            agent_factory=self._agent_factory,
            agent_runner=self._agent_runner,
            message_processor=self._message_processor,
            channels={},
            logger=self.logger,
        )

        # Lifecycle manager
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

        # Session TTL config (used by _inject_channel_context to skip context
        # for sessions that are about to be rotated)
        self._session_ttl_minutes: int = self._merged_config.get(
            "session_ttl_minutes", 180
        )

        # Build a channel-name → context_messages limit mapping so
        # _inject_channel_context() can look up the limit without re-parsing
        # the full merged config on every inbound message.
        self._channel_context_limits: dict[str, int] = {
            (ch_cfg.get("name") or ch_cfg.get("type", "telegram")): ch_cfg.get(
                "context_messages", 25
            )
            for ch_cfg in self._merged_config.get("channels", [])
        }

        # Runtime state
        self._channels: dict[str, ChannelAdapter] = {}
        self._subagent_runner: SubAgentRunner | None = None
        self._queue_processor_task: asyncio.Task[None] | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._supervisor_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def token_logger(self) -> TokenUsageLogger:
        """Get the token usage logger for this workspace."""
        return self._token_logger

    def _register_framework_commands(self) -> None:
        """Register all framework command handlers."""
        for handler in get_framework_commands():
            self._command_router.register(handler)
        self.logger.info(
            f"Registered {len(self._command_router.list_commands(include_hidden=True))} framework commands"
        )

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

    def _build_command_context(self, message: Message) -> CommandContext:
        """Build command execution context for the current message."""
        channel = self._channels.get(message.channel)
        if not channel:
            raise RuntimeError(
                f"No channel found for message.channel: {message.channel}"
            )
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
            channels=self._channels,
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
                        await channel.send_message(
                            message.session_key, command_result.response
                        )

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
                    self.logger.debug(
                        f"Processor {processor.metadata.name} handled message, skipping agent"
                    )
                    return
            except Exception as e:
                self.logger.error(f"Processor {processor.metadata.name} failed: {e}")

        # Inject channel history context for group messages (best-effort)
        processed_message = await self._inject_channel_context(processed_message)

        content_preview = (
            processed_message.content[:50] if processed_message.content else "(empty)"
        )
        self.logger.info(
            f"Received message from {processed_message.channel}: {content_preview}..."
        )

        await self._queue_manager.submit(
            session_key=processed_message.session_key,
            channel_name=processed_message.channel,
            message=processed_message,
        )

    async def _inject_channel_context(self, message: Message) -> Message:
        """Fetch and inject channel history context for group messages.

        Only runs when:
        - Message is from a guild/group (metadata has a non-None guild_id)
        - The channel has context_messages > 0 configured
        - The channel adapter supports fetch_channel_history()

        The formatted XML block is prepended to message.content so the agent
        sees recent conversation history before the triggering message.

        Best-effort: any failure returns the original message unchanged.

        Args:
            message: The processed inbound message.

        Returns:
            The message with channel context prepended, or the original message
            on failure or when context fetch is not applicable.
        """
        # Only fetch context for guild (group) messages
        if not message.metadata.get("guild_id"):
            return message

        # Skip channel context when the session is about to be TTL-rotated.
        # Injecting old conversation history into a fresh thread is contradictory.
        if self._session_ttl_minutes > 0 and self._session_manager.is_session_expired(
            message.session_key, self._session_ttl_minutes
        ):
            self.logger.debug(
                "Skipping channel context for %s (session TTL expired)",
                message.session_key,
            )
            return message

        # Look up the configured limit for this channel
        context_limit = self._channel_context_limits.get(message.channel, 25)
        if context_limit <= 0:
            return message

        channel = self._channels.get(message.channel)
        if channel is None:
            return message

        try:
            # Extract the platform channel ID from the session key
            # session_key format: "{channel_name}:{channel_id}" (channel_name may contain colons)
            channel_id = message.session_key.split(":")[-1]

            entries = await channel.fetch_channel_history(channel_id, limit=context_limit)
            if not entries:
                return message

            channel_label = str(message.metadata.get("channel_label", "unknown"))
            source = (
                message.channel.split("-")[0]
                if "-" in message.channel
                else message.channel
            )

            context_xml = format_channel_context(
                entries,
                bot_user_id=None,
                channel_name=channel_label,
                source=source,
            )

            message.content = f"{context_xml}\n\n{message.content}"
            self.logger.debug(
                "Injected channel context (%d messages) for session %s",
                len(entries),
                message.session_key,
            )

        except Exception:
            self.logger.debug(
                "Channel context fetch failed for session %s, continuing without",
                message.session_key,
                exc_info=True,
            )

        return message

    async def _process_messages(self, session_key: str, messages: list[Message]) -> None:
        """Process collected messages for a session."""
        channel_name = session_key.split(":")[0]
        channel = self._channels.get(channel_name)
        await self._message_processor.process_messages(session_key, messages, channel)

    async def _queue_processor(self) -> None:
        """Background task processing the lane queue."""

        async def handler(item: QueueItem) -> None:
            channel_name, messages = item.payload
            handler_func = self._queue_manager.get_handler(channel_name)
            if handler_func:
                await handler_func(item.session_key, messages)

        await self._lane_queue.process("main", handler)

    async def start(self) -> None:
        """Start workspace runner."""
        self.logger.info(f"Starting workspace runner: {self.workspace_name}")

        # Initialize SQLite checkpointer
        self._db_conn = await aiosqlite.connect(str(self._db_path))
        self._checkpointer = AsyncSqliteSaver(self._db_conn)
        await self._checkpointer.setup()
        self._agent_runner.update_checkpointer(self._checkpointer)
        self.logger.info(f"Initialized SQLite checkpointer: {self._db_path}")

        # MCP: connect servers and inject tools into the agent.
        if self._mcp_manager is not None:
            try:
                await self._mcp_manager.connect()
                mcp_tools = self._mcp_manager.get_tools()
                if mcp_tools:
                    # Register with the factory FIRST so any later rebuild
                    # (e.g. connectors removing search_conversations) keeps MCP tools.
                    self._agent_factory.set_mcp_tools(mcp_tools)
                    current = list(self._agent_runner.additional_tools)
                    self._agent_runner.update_tools(current + mcp_tools)
                    self.logger.info(
                        f"[{self.workspace_name}] Injected {len(mcp_tools)} MCP tools into agent."
                    )
            except Exception as exc:
                self.logger.exception(f"[{self.workspace_name}] MCP startup failed: {exc}")
                # Close the db connection opened earlier this start() so we don't leak it.
                if self._db_conn is not None:
                    await self._db_conn.close()
                    self._db_conn = None
                    self._checkpointer = None
                raise

        # Prune orphaned checkpoint data at startup
        retention_days = (
            self._workspace.config.checkpoint_retention_days
            if self._workspace.config
            else 7
        )
        if retention_days > 0:
            try:
                from openpaw.runtime.session.pruner import CheckpointPruner

                pruner = CheckpointPruner(
                    db_conn=self._db_conn,
                    session_manager=self._session_manager,
                    retention_days=retention_days,
                )
                result = await pruner.prune()
                if result.threads_pruned > 0:
                    self.logger.info(
                        f"Checkpoint pruning: removed {result.threads_pruned} thread(s), "
                        f"{result.checkpoints_deleted} checkpoint(s), "
                        f"{result.writes_deleted} write(s)"
                    )
            except Exception as e:
                self.logger.warning(f"Checkpoint pruning failed (non-fatal): {e}")

        # Initialize vector store if memory search is enabled
        if self._vector_store:
            await self._vector_store.initialize()
            self.logger.info("Vector store initialized")

        # Wire memory search tool
        self._tool_connector.connect_memory_search_tool(
            self._vector_store,
            self._embedding_provider,
            self._checkpointer,
        )

        # Setup channels
        self._channels = await self._lifecycle_manager.setup_channels()
        await self._lifecycle_manager.start_channels()

        # Update connector channels reference
        self._tool_connector._channels = self._channels

        # Register framework commands with channels (e.g., Discord slash commands)
        command_defs = self._command_router.list_commands()
        for channel in self._channels.values():
            await channel.register_commands(command_defs)

        # Start schedulers if needed
        cron_tool_loaded = (
            self._builtin_loader.get_tool_instance("cron") is not None
        )
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

        # Load spawn profiles and create resolver
        workspace_profiles = load_spawn_profiles(
            self._workspace.path / str(TEAM_DIR)
        )
        system_profiles: list[SpawnProfile] = []
        if self.config.team_profiles_path:
            system_profiles = load_spawn_profiles(
                Path(self.config.team_profiles_path), source="system"
            )
        profile_resolver = SpawnProfileResolver(
            workspace_profiles, system_profiles
        )

        # Inject team roster into the workspace system prompt
        if len(profile_resolver) > 0:
            self._workspace.team_roster = TeamRosterBuilder(
                profile_resolver
            ).build()

        # Start sub-agent runner
        subagent_session_logger = SessionLogger(
            self._workspace.path, session_type="subagent"
        )

        # Closure bridges sub-agent lifecycle events to StatusUpdateMiddleware.
        # Reads self._status_update_middleware lazily so it works even if
        # middleware is built after this closure is created.
        async def _subagent_status_callback(
            subagent_id: str,
            event: str,
            text: str,
            emoji: str | None,
        ) -> None:
            mw = self._status_update_middleware
            if mw is None:
                return
            if not mw._config.enabled or not mw._config.subagent_status:
                return
            if event == "start":
                await mw.create_subagent_status(subagent_id, text)
            elif event == "tool":
                await mw.update_subagent_status(subagent_id, text, emoji)
            elif event in ("completed", "failed", "cancelled"):
                await mw.finalize_subagent_status(subagent_id, event)

        self._subagent_runner = SubAgentRunner(
            agent_factory=self._agent_factory.get_agent_factory_closure(),
            store=self._subagent_store,
            channels=self._channels,
            token_logger=self._token_logger,
            workspace_name=self.workspace_name,
            max_concurrent=8,
            result_callback=self._inject_system_event,
            session_logger=subagent_session_logger,
            profile_resolver=profile_resolver,
            agent_factory_instance=self._agent_factory,
            status_callback=_subagent_status_callback,
        )
        self._tool_connector.connect_spawn_tool(self._subagent_runner)
        self._tool_connector.connect_channel_history_tool(self._checkpointer)

        self._running = True
        self._task_service.start()
        self._queue_processor_task = asyncio.create_task(self._queue_processor())
        self._queue_processor_task.add_done_callback(self._on_queue_processor_done)
        self._cleanup_task = asyncio.create_task(
            self._task_service.periodic_cleanup()
        )
        self._supervisor_task = asyncio.create_task(self._task_supervisor())

        self.logger.info(f"Workspace runner '{self.workspace_name}' is running")

        # Lifecycle notification: startup
        lifecycle = (
            self._workspace.config.lifecycle if self._workspace.config else None
        )
        if lifecycle and lifecycle.notify_startup:
            await self._notify_lifecycle("Started")

    def _connect_spawn_tool_to_runner(self) -> None:
        """Connect SpawnTool builtin to the live SubAgentRunner."""
        BuiltinToolConnector._connect_spawn_tool_impl(
            self._builtin_loader,
            self._subagent_runner,
            self.logger,
        )

    def _connect_channel_history_tool(self) -> None:
        """Connect ChannelHistoryTool to live channel adapters."""
        new_runner = BuiltinToolConnector._connect_channel_history_tool_impl(
            self._builtin_loader,
            self._agent_factory,
            self._agent_runner,
            self._message_processor,
            self._channels,
            self._checkpointer,
            self.logger,
        )
        if new_runner is not None:
            self._agent_runner = new_runner
            self._message_processor.update_agent_runner(new_runner)

    def _connect_memory_search_tool(self) -> None:
        """Connect MemorySearchTool builtin to vector store and embedding provider."""
        new_runner = BuiltinToolConnector._connect_memory_search_tool_impl(
            self._builtin_loader,
            self._agent_factory,
            self._agent_runner,
            self._message_processor,
            self._vector_store,
            self._embedding_provider,
            self._checkpointer,
            self.logger,
        )
        if new_runner is not None:
            self._agent_runner = new_runner
            self._message_processor.update_agent_runner(new_runner)

    def _resolve_user_name(self, message: Message) -> str:
        """Resolve display name, defaulting to 'Unknown' (guaranteed non-None)."""
        return (
            resolve_user_name(message.user_id, message.metadata, self._user_aliases)
            or "Unknown"
        )

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
            self.logger.error(
                f"Invalid session_key format for system event: {session_key}"
            )
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

            self.logger.info(
                f"Injected system event into queue for session: {session_key}"
            )

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
        return BuiltinToolConnector._get_browser_builtin_impl(self._builtin_loader)

    async def _notify_lifecycle(self, event: str, detail: str | None = None) -> None:
        """Send a lifecycle notification to all channels.

        Args:
            event: Event name (startup, shutdown, auto_compact).
            detail: Optional detail message.
        """
        await _notify_lifecycle_impl(
            self._channels,
            self.workspace_name,
            self.logger,
            event,
            detail,
        )

    async def _archive_active_conversations(self) -> None:
        """Archive all active conversations on shutdown."""
        if not self._checkpointer or not hasattr(self, "_conversation_archiver"):
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
                self.logger.warning(
                    f"Failed to archive conversation {state.conversation_id}: {e}",
                    exc_info=True,
                )

        if archived_count > 0:
            self.logger.info(f"Archived {archived_count} conversation(s) on shutdown")

    def _on_queue_processor_done(self, task: asyncio.Task[None]) -> None:
        """Callback invoked when the queue processor task completes.

        Logs the exception immediately so crashes are visible even if the
        supervisor has not yet woken up.
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            self.logger.critical(
                f"Queue processor task crashed: {exc}", exc_info=exc
            )

    async def _task_supervisor(self) -> None:
        """Monitor background tasks and notify users on crash.

        Watches the queue processor task. If it dies unexpectedly, sends a
        direct channel message to every active session and attempts to restart
        the processor.
        """
        while self._running:
            try:
                await asyncio.sleep(10.0)
            except asyncio.CancelledError:
                break

            if not self._queue_processor_task or self._queue_processor_task.done():
                exc: BaseException | None = None
                if self._queue_processor_task:
                    exc = self._queue_processor_task.exception()
                self.logger.critical(
                    f"Queue processor is dead (exception: {exc}). Restarting...",
                    exc_info=exc,
                )

                # Notify all active sessions via direct channel send
                for session_key in list(self._session_manager.list_sessions().keys()):
                    channel_name = session_key.split(":")[0]
                    channel = self._channels.get(channel_name)
                    if channel:
                        try:
                            await channel.send_message(
                                session_key,
                                "[SYSTEM] Message processing was interrupted due to an internal error. "
                                "The administrator has been notified. Please retry your message.",
                            )
                        except Exception as e:
                            self.logger.error(
                                f"Failed to send crash notification to {session_key}: {e}"
                            )

                # Restart queue processor
                self._queue_processor_task = asyncio.create_task(
                    self._queue_processor()
                )
                self._queue_processor_task.add_done_callback(
                    self._on_queue_processor_done
                )
                self.logger.info("Restarted queue processor")

    async def stop(self) -> None:
        """Stop workspace runner gracefully."""
        self.logger.info(f"Stopping workspace runner: {self.workspace_name}")
        self._running = False
        task_service = getattr(self, "_task_service", None)
        if task_service:
            task_service.stop()

        # Lifecycle notification: shutdown
        lifecycle = (
            self._workspace.config.lifecycle if self._workspace.config else None
        )
        if lifecycle and lifecycle.notify_shutdown:
            await self._notify_lifecycle("Shutting down")

        # Cancel supervisor
        supervisor_task = getattr(self, "_supervisor_task", None)
        if supervisor_task:
            supervisor_task.cancel()
            try:
                await supervisor_task
            except asyncio.CancelledError:
                pass
            self._supervisor_task = None

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

        # Close MCP manager before DB
        if self._mcp_manager is not None:
            try:
                await self._mcp_manager.close()
                self.logger.info("Closed MCP manager")
            except Exception as exc:
                self.logger.warning(f"[{self.workspace_name}] MCP shutdown error: {exc}")

        # Close database
        if self._db_conn:
            await self._db_conn.close()
            self._db_conn = None
            self.logger.info("Closed checkpointer database connection")

        self.logger.info(f"Workspace runner '{self.workspace_name}' stopped")
