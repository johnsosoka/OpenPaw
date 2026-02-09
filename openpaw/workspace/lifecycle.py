"""Lifecycle management for WorkspaceRunner components."""

import logging
from typing import Any

from openpaw.builtins.loader import BuiltinLoader
from openpaw.channels.base import ChannelAdapter
from openpaw.channels.factory import create_channel
from openpaw.core.config import Config
from openpaw.core.queue.manager import QueueManager
from openpaw.runtime.scheduling.heartbeat import HeartbeatScheduler
from openpaw.runtime.session.manager import SessionManager


class LifecycleManager:
    """Manages startup and shutdown of workspace components."""

    def __init__(
        self,
        workspace_name: str,
        workspace_path: Any,
        workspace_config: Any,
        merged_config: dict[str, Any],
        config: Config,
        queue_manager: QueueManager,
        message_handler: Any,
        queue_handler: Any,
        builtin_loader: BuiltinLoader,
        workspace_timezone: str,
        session_manager: SessionManager,
        approval_handler: Any,
        logger: logging.Logger,
    ):
        """Initialize lifecycle manager.

        Args:
            workspace_name: Name of the workspace.
            workspace_path: Path to workspace directory.
            workspace_config: Workspace configuration object.
            merged_config: Merged global + workspace config.
            config: Global configuration.
            queue_manager: Queue manager instance.
            message_handler: Raw inbound message callback (from channel).
            queue_handler: Batched message processing callback (after debounce).
            builtin_loader: Builtin tool/processor loader.
            workspace_timezone: Workspace timezone string.
            session_manager: Session management.
            approval_handler: Approval resolution callback.
            logger: Logger instance.
        """
        self._workspace_name = workspace_name
        self._workspace_path = workspace_path
        self._workspace_config = workspace_config
        self._merged_config = merged_config
        self._config = config
        self._queue_manager = queue_manager
        self._message_handler = message_handler
        self._queue_handler = queue_handler
        self._builtin_loader = builtin_loader
        self._workspace_timezone = workspace_timezone
        self._session_manager = session_manager
        self._approval_handler = approval_handler
        self._logger = logger

        self._channels: dict[str, ChannelAdapter] = {}
        self._cron_scheduler: Any = None
        self._heartbeat_scheduler: HeartbeatScheduler | None = None

    async def setup_channels(self) -> dict[str, ChannelAdapter]:
        """Initialize configured channels via factory.

        Returns:
            Dictionary of initialized channels.

        Raises:
            ValueError: If channel configuration is invalid.
        """
        workspace_channel = self._merged_config.get("channel", {})
        if not workspace_channel:
            raise ValueError(
                f"Workspace '{self._workspace_name}' must define channel configuration in agent.yaml"
            )

        channel_type = workspace_channel.get("type", "telegram")
        token = workspace_channel.get("token")
        if not token:
            raise ValueError(
                f"Workspace '{self._workspace_name}' must define channel.token in agent.yaml"
            )

        channel = create_channel(channel_type, workspace_channel, self._workspace_name)
        channel.on_message(self._message_handler)
        self._channels[channel_type] = channel
        await self._queue_manager.register_handler(channel_type, self._queue_handler)

        # Log security mode
        allow_all = workspace_channel.get("allow_all", False)
        allowed_users = workspace_channel.get("allowed_users", [])
        allowed_groups = workspace_channel.get("allowed_groups", [])
        if allow_all:
            self._logger.warning(f"Workspace '{self._workspace_name}': allow_all=true (insecure mode)")
        elif allowed_users or allowed_groups:
            self._logger.info(
                f"Workspace '{self._workspace_name}': Allowlist mode "
                f"({len(allowed_users)} users, {len(allowed_groups)} groups)"
            )
        else:
            self._logger.warning(
                f"Workspace '{self._workspace_name}': Empty allowlist - all requests will be denied"
            )

        self._logger.info(f"Initialized {channel_type} channel for workspace: {self._workspace_name}")
        return self._channels

    async def start_channels(self) -> None:
        """Start all configured channels."""
        for name, channel in self._channels.items():
            await channel.start()
            self._logger.info(f"Started channel: {name}")

        # Connect approval callback to channels
        for channel in self._channels.values():
            if hasattr(channel, "on_approval"):
                channel.on_approval(self._approval_handler)

    async def stop_channels(self) -> None:
        """Stop all configured channels."""
        for name, channel in self._channels.items():
            await channel.stop()
            self._logger.info(f"Stopped channel: {name}")

    async def setup_cron_scheduler(
        self,
        workspace_crons: list[Any],
        agent_factory: Any,
        token_logger: Any,
    ) -> None:
        """Initialize and start cron scheduler.

        Args:
            workspace_crons: List of cron job definitions.
            agent_factory: Callable that creates agent instances.
            token_logger: Token usage logger.
        """
        try:
            from openpaw.runtime.scheduling.cron import CronScheduler

            self._cron_scheduler = CronScheduler(
                workspace_path=self._workspace_path,
                agent_factory=agent_factory,
                channels=self._channels,
                token_logger=token_logger,
                workspace_name=self._workspace_name,
                timezone=self._workspace_timezone,
            )

            await self._cron_scheduler.start()
            self._logger.info(f"Started cron scheduler with {len(workspace_crons)} jobs")

            # Connect CronTool to live scheduler for dynamic task scheduling
            self._connect_cron_tool_to_scheduler()

        except ImportError as e:
            self._logger.warning(f"Cron scheduler not available: {e}")
        except Exception as e:
            self._logger.error(f"Failed to start cron scheduler: {e}", exc_info=True)

    async def stop_cron_scheduler(self) -> None:
        """Stop cron scheduler if running."""
        if self._cron_scheduler:
            await self._cron_scheduler.stop()
            self._logger.info("Stopped cron scheduler")

    async def setup_heartbeat_scheduler(
        self,
        agent_factory: Any,
        token_logger: Any,
    ) -> None:
        """Initialize and start heartbeat scheduler if enabled.

        Args:
            agent_factory: Callable that creates agent instances.
            token_logger: Token usage logger.
        """
        # Get heartbeat config from workspace only - no global fallback
        if not self._workspace_config or not self._workspace_config.heartbeat:
            return

        heartbeat_config = self._workspace_config.heartbeat
        if not heartbeat_config.enabled:
            return

        try:
            self._heartbeat_scheduler = HeartbeatScheduler(
                workspace_name=self._workspace_name,
                workspace_path=self._workspace_path,
                agent_factory=agent_factory,
                channels=self._channels,
                config=heartbeat_config,
                timezone=self._workspace_timezone,
                token_logger=token_logger,
            )

            await self._heartbeat_scheduler.start()
            self._logger.info(
                f"Started heartbeat scheduler (interval: {heartbeat_config.interval_minutes}min)"
            )

        except Exception as e:
            self._logger.error(f"Failed to start heartbeat scheduler: {e}", exc_info=True)

    async def stop_heartbeat_scheduler(self) -> None:
        """Stop heartbeat scheduler if running."""
        if self._heartbeat_scheduler:
            await self._heartbeat_scheduler.stop()
            self._logger.info("Stopped heartbeat scheduler")

    def _connect_cron_tool_to_scheduler(self) -> None:
        """Connect CronTool builtin to the live CronScheduler."""
        try:
            cron_tool = self._builtin_loader.get_tool_instance("cron")
            if cron_tool:
                cron_tool.set_scheduler(self._cron_scheduler)
                self._logger.info("Connected CronTool to live scheduler")
            else:
                self._logger.debug("CronTool not loaded for this workspace")
        except Exception as e:
            self._logger.warning(f"Failed to connect CronTool to scheduler: {e}")

    def get_channels(self) -> dict[str, ChannelAdapter]:
        """Get the initialized channels.

        Returns:
            Dictionary of channels.
        """
        return self._channels
