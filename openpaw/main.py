"""Main entry point for OpenPaw."""

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from openpaw.channels.base import Message
from openpaw.channels.telegram import TelegramChannel
from openpaw.core.agent import AgentRunner
from openpaw.core.config import Config, load_config
from openpaw.queue.lane import LaneQueue, QueueItem, QueueMode
from openpaw.queue.manager import QueueManager
from openpaw.workspace.loader import WorkspaceLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class OpenPaw:
    """Main application orchestrating channels, queues, and agents."""

    def __init__(self, config: Config, workspace_name: str):
        """Initialize OpenPaw.

        Args:
            config: Application configuration.
            workspace_name: Name of the agent workspace to load.
        """
        self.config = config
        self.workspace_name = workspace_name

        self._workspace_loader = WorkspaceLoader(config.workspaces_path)
        self._workspace = self._workspace_loader.load(workspace_name)

        self._lane_queue = LaneQueue(
            main_concurrency=config.lanes.main_concurrency,
            subagent_concurrency=config.lanes.subagent_concurrency,
            cron_concurrency=config.lanes.cron_concurrency,
        )

        self._queue_manager = QueueManager(
            lane_queue=self._lane_queue,
            default_mode=QueueMode(config.queue.mode),
            default_debounce_ms=config.queue.debounce_ms,
            default_cap=config.queue.cap,
            default_drop_policy=config.queue.drop_policy,
        )

        # Checkpointer for multi-turn conversation memory
        # InMemorySaver persists within session; use SqliteSaver for disk persistence
        self._checkpointer = InMemorySaver()

        self._agent_runner = AgentRunner(
            workspace=self._workspace,
            model=config.agent.model,
            api_key=config.agent.api_key,
            max_turns=config.agent.max_turns,
            temperature=config.agent.temperature,
            checkpointer=self._checkpointer,
        )

        self._channels: dict[str, TelegramChannel] = {}
        self._running = False

    async def _setup_channels(self) -> None:
        """Initialize configured channels."""
        tg_config = self.config.channels.telegram
        if tg_config.token:
            telegram = TelegramChannel(
                token=tg_config.token,
                allowed_users=tg_config.allowed_users,
                allowed_groups=tg_config.allowed_groups,
            )
            telegram.on_message(self._handle_inbound_message)
            self._channels["telegram"] = telegram
            await self._queue_manager.register_handler("telegram", self._process_telegram_messages)

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
        """Start OpenPaw."""
        logger.info(f"Starting OpenPaw with workspace: {self.workspace_name}")

        await self._setup_channels()

        for name, channel in self._channels.items():
            await channel.start()
            logger.info(f"Started channel: {name}")

        self._running = True

        asyncio.create_task(self._queue_processor())

        logger.info("OpenPaw is running. Press Ctrl+C to stop.")

    async def stop(self) -> None:
        """Stop OpenPaw gracefully."""
        logger.info("Stopping OpenPaw...")
        self._running = False

        for name, channel in self._channels.items():
            await channel.stop()
            logger.info(f"Stopped channel: {name}")

        logger.info("OpenPaw stopped.")


async def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="OpenPaw - AI Agent Framework")
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to configuration file",
    )
    parser.add_argument(
        "-w", "--workspace",
        type=str,
        required=True,
        help="Name of the agent workspace to load",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = load_config(args.config)

    app = OpenPaw(config, args.workspace)

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def signal_handler() -> None:
        stop_event.set()

    loop.add_signal_handler(signal.SIGINT, signal_handler)
    loop.add_signal_handler(signal.SIGTERM, signal_handler)

    await app.start()
    await stop_event.wait()
    await app.stop()


def run() -> None:
    """Entry point for poetry scripts."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
