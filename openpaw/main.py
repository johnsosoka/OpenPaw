"""Workspace runner for OpenPaw."""

import asyncio
import logging
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from openpaw.channels.base import Message
from openpaw.channels.telegram import TelegramChannel
from openpaw.core.agent import AgentRunner
from openpaw.core.config import Config, merge_configs
from openpaw.queue.lane import LaneQueue, QueueItem, QueueMode
from openpaw.queue.manager import QueueManager
from openpaw.workspace.loader import WorkspaceLoader

logger = logging.getLogger(__name__)


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

        self._workspace_loader = WorkspaceLoader(config.workspaces_path)
        self._workspace = self._workspace_loader.load(workspace_name)

        # Merge workspace config with global config if workspace has agent.yaml
        self._merged_config = self._merge_workspace_config(config, self._workspace)

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

        # Checkpointer for multi-turn conversation memory
        # InMemorySaver persists within session; use SqliteSaver for disk persistence
        self._checkpointer = InMemorySaver()

        # Use merged model config for agent
        agent_config = self._merged_config.get("model", {})
        model_str = agent_config.get("model", config.agent.model)
        if agent_config.get("provider"):
            model_str = f"{agent_config['provider']}:{agent_config['model']}"

        self._agent_runner = AgentRunner(
            workspace=self._workspace,
            model=model_str,
            api_key=agent_config.get("api_key", config.agent.api_key),
            max_turns=agent_config.get("max_turns", config.agent.max_turns),
            temperature=agent_config.get("temperature", config.agent.temperature),
            checkpointer=self._checkpointer,
        )

        self._channels: dict[str, TelegramChannel] = {}
        self._cron_scheduler: Any = None
        self._queue_processor_task: asyncio.Task[None] | None = None
        self._running = False

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

    async def _setup_channels(self) -> None:
        """Initialize configured channels.

        Each workspace MUST define its own channel configuration.
        Raises an error if no channel is configured.
        """
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

        if channel_type == "telegram":
            allowed_users = workspace_channel.get("allowed_users", [])
            allowed_groups = workspace_channel.get("allowed_groups", [])
            allow_all = workspace_channel.get("allow_all", False)

            telegram = TelegramChannel(
                token=token,
                allowed_users=allowed_users,
                allowed_groups=allowed_groups,
                allow_all=allow_all,
                workspace_name=self.workspace_name,
            )
            telegram.on_message(self._handle_inbound_message)
            self._channels["telegram"] = telegram
            await self._queue_manager.register_handler("telegram", self._process_telegram_messages)

            # Log security mode
            if allow_all:
                logger.warning(f"Workspace '{self.workspace_name}': allow_all=true (insecure mode)")
            elif allowed_users or allowed_groups:
                logger.info(
                    f"Workspace '{self.workspace_name}': Allowlist mode "
                    f"({len(allowed_users)} users, {len(allowed_groups)} groups)"
                )
            else:
                logger.warning(
                    f"Workspace '{self.workspace_name}': Empty allowlist - all requests will be denied"
                )

            logger.info(f"Initialized Telegram channel for workspace: {self.workspace_name}")
        else:
            raise ValueError(f"Unsupported channel type: {channel_type}")

    async def _handle_inbound_message(self, message: Message) -> None:
        """Handle an inbound message from any channel."""
        logger.info(f"Received message from {message.channel}: {message.content[:50]}...")

        if message.is_command:
            command, args = message.parse_command()
            if command == "queue":
                await self._handle_queue_command(message, args)
                return

        await self._queue_manager.submit(
            session_key=message.session_key,
            channel_name=message.channel,
            message=message,
        )

    async def _handle_queue_command(self, message: Message, args: str) -> None:
        """Handle /queue command to set queue mode."""
        mode_str = args.strip().lower()
        mode_map = {
            "collect": QueueMode.COLLECT,
            "steer": QueueMode.STEER,
            "followup": QueueMode.FOLLOWUP,
            "interrupt": QueueMode.INTERRUPT,
            "default": QueueMode.COLLECT,
            "reset": QueueMode.COLLECT,
        }

        mode = mode_map.get(mode_str)
        if mode:
            await self._queue_manager.set_session_mode(message.session_key, mode)
            channel = self._channels.get(message.channel)
            if channel:
                await channel.send_message(message.session_key, f"Queue mode set to: {mode.value}")
        else:
            channel = self._channels.get(message.channel)
            if channel:
                await channel.send_message(
                    message.session_key,
                    f"Unknown mode: {mode_str}. Valid: collect, steer, followup, interrupt, default",
                )

    async def _process_telegram_messages(self, session_key: str, messages: list[Message]) -> None:
        """Process collected messages for a Telegram session."""
        combined_content = "\n".join(m.content for m in messages)

        thread_id = session_key

        try:
            response = await self._agent_runner.run(
                message=combined_content,
                thread_id=thread_id,
            )

            channel = self._channels.get("telegram")
            if channel and response:
                await channel.send_message(session_key, response)

        except Exception as e:
            logger.error(f"Error processing messages for {session_key}: {e}")
            channel = self._channels.get("telegram")
            if channel:
                await channel.send_message(session_key, f"Error: {e}")

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
        logger.info(f"Starting workspace runner: {self.workspace_name}")

        await self._setup_channels()

        for name, channel in self._channels.items():
            await channel.start()
            logger.info(f"Started channel: {name}")

        # Start cron scheduler if workspace has cron definitions
        if self._workspace.crons:
            await self._setup_cron_scheduler()

        self._running = True

        self._queue_processor_task = asyncio.create_task(self._queue_processor())

        logger.info(f"Workspace runner '{self.workspace_name}' is running")

    async def _setup_cron_scheduler(self) -> None:
        """Initialize and start cron scheduler if workspace has cron jobs."""
        try:
            from openpaw.cron.scheduler import CronScheduler

            def agent_factory() -> AgentRunner:
                """Factory to create fresh agent instances for cron jobs."""
                return AgentRunner(
                    workspace=self._workspace,
                    model=self._agent_runner.model_id,
                    api_key=self._agent_runner.api_key,
                    max_turns=self._agent_runner.max_turns,
                    temperature=self._agent_runner.temperature,
                    checkpointer=None,  # No checkpointer for cron jobs
                )

            self._cron_scheduler = CronScheduler(
                workspace_path=self._workspace.path,
                agent_factory=agent_factory,
                channels=self._channels,
            )

            await self._cron_scheduler.start()
            logger.info(f"Started cron scheduler with {len(self._workspace.crons)} jobs")

        except ImportError as e:
            logger.warning(f"Cron scheduler not available: {e}")
        except Exception as e:
            logger.error(f"Failed to start cron scheduler: {e}", exc_info=True)

    async def stop(self) -> None:
        """Stop workspace runner gracefully."""
        logger.info(f"Stopping workspace runner: {self.workspace_name}")
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
            logger.info("Stopped cron scheduler")

        for name, channel in self._channels.items():
            await channel.stop()
            logger.info(f"Stopped channel: {name}")

        logger.info(f"Workspace runner '{self.workspace_name}' stopped")
