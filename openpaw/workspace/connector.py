"""Builtin tool connector for OpenPaw."""

import logging
from typing import Any

from openpaw.channels.base import ChannelAdapter


class BuiltinToolConnector:
    """Connects builtin tools to runtime components."""

    def __init__(
        self,
        builtin_loader: Any,
        agent_factory: Any,
        agent_runner: Any,
        message_processor: Any,
        channels: dict[str, ChannelAdapter],
        logger: logging.Logger,
    ):
        self._builtin_loader = builtin_loader
        self._agent_factory = agent_factory
        self._agent_runner = agent_runner
        self._message_processor = message_processor
        self._channels = channels
        self._logger = logger

    @staticmethod
    def _connect_memory_search_tool_impl(
        builtin_loader: Any,
        agent_factory: Any,
        agent_runner: Any,
        message_processor: Any,
        vector_store: Any,
        embedding_provider: Any,
        checkpointer: Any,
        logger: logging.Logger,
    ) -> Any | None:
        """Connect MemorySearchTool to vector store and embedding provider.

        Returns the new agent_runner if the agent was rebuilt, otherwise None.
        """
        try:
            memory_tool = builtin_loader.get_tool_instance("memory_search")
            if memory_tool and vector_store and embedding_provider:
                memory_tool.set_context(vector_store, embedding_provider)
                logger.info("Connected MemorySearchTool to vector store")
            elif memory_tool:
                # Vector store not available — remove broken tool from agent
                agent_factory.remove_builtin_tools({"search_conversations"})
                agent_factory.remove_enabled_builtin("memory_search")
                # Rebuild agent without the broken tool.
                new_agent_runner = agent_factory.create_agent(
                    checkpointer=checkpointer
                )
                logger.info(
                    "Removed memory_search tools from agent (vector store not initialized)"
                )
                return new_agent_runner
            else:
                logger.debug("MemorySearchTool not loaded for this workspace")
        except Exception as e:
            logger.warning(f"Failed to connect MemorySearchTool: {e}")
        return None

    def connect_memory_search_tool(
        self,
        vector_store: Any,
        embedding_provider: Any,
        checkpointer: Any,
    ) -> Any | None:
        """Connect MemorySearchTool to vector store and embedding provider."""
        new_runner = self._connect_memory_search_tool_impl(
            self._builtin_loader,
            self._agent_factory,
            self._agent_runner,
            self._message_processor,
            vector_store,
            embedding_provider,
            checkpointer,
            self._logger,
        )
        if new_runner is not None:
            self._agent_runner = new_runner
            self._message_processor.update_agent_runner(new_runner)
        return new_runner

    @staticmethod
    def _connect_channel_history_tool_impl(
        builtin_loader: Any,
        agent_factory: Any,
        agent_runner: Any,
        message_processor: Any,
        channels: dict[str, ChannelAdapter],
        checkpointer: Any,
        logger: logging.Logger,
    ) -> Any | None:
        """Connect ChannelHistoryTool to live channel adapters.

        Returns the new agent_runner if the agent was rebuilt, otherwise None.
        """
        try:
            history_tool = builtin_loader.get_tool_instance("channel_history")
            if not history_tool:
                logger.debug("ChannelHistoryTool not loaded for this workspace")
                return None

            # Find channels that support history browsing
            history_channels = {
                name: ch
                for name, ch in channels.items()
                if ch.supports_history_browsing
            }

            if not history_channels:
                # No history-capable channels — remove the tool so the LLM never
                # sees a broken capability
                agent_factory.remove_builtin_tools({"browse_channel_history"})
                agent_factory.remove_enabled_builtin("channel_history")
                new_agent_runner = agent_factory.create_agent(
                    checkpointer=checkpointer
                )
                logger.info(
                    "Removed channel_history tool (no history-capable channels)"
                )
                return new_agent_runner

            history_tool.set_channels(history_channels)
            logger.info(
                "Connected ChannelHistoryTool to %d channel(s): %s",
                len(history_channels),
                list(history_channels.keys()),
            )
        except Exception as e:
            logger.warning(f"Failed to connect ChannelHistoryTool: {e}")
        return None

    def connect_channel_history_tool(self, checkpointer: Any) -> Any | None:
        """Connect ChannelHistoryTool to live channel adapters."""
        new_runner = self._connect_channel_history_tool_impl(
            self._builtin_loader,
            self._agent_factory,
            self._agent_runner,
            self._message_processor,
            self._channels,
            checkpointer,
            self._logger,
        )
        if new_runner is not None:
            self._agent_runner = new_runner
            self._message_processor.update_agent_runner(new_runner)
        return new_runner

    @staticmethod
    def _connect_spawn_tool_impl(
        builtin_loader: Any,
        subagent_runner: Any,
        logger: logging.Logger,
    ) -> None:
        """Connect SpawnTool builtin to the live SubAgentRunner."""
        try:
            spawn_tool = builtin_loader.get_tool_instance("spawn")
            if spawn_tool:
                spawn_tool.set_runner(subagent_runner)
                logger.info("Connected SpawnTool to SubAgentRunner")
            else:
                logger.debug("SpawnTool not loaded for this workspace")
        except Exception as e:
            logger.warning(f"Failed to connect SpawnTool to runner: {e}")

    def connect_spawn_tool(self, subagent_runner: Any) -> None:
        """Connect SpawnTool builtin to the live SubAgentRunner."""
        self._connect_spawn_tool_impl(
            self._builtin_loader,
            subagent_runner,
            self._logger,
        )

    @staticmethod
    def _get_browser_builtin_impl(builtin_loader: Any) -> Any | None:
        """Get the browser builtin instance if loaded."""
        return builtin_loader.get_tool_instance("browser")

    def get_browser_builtin(self) -> Any | None:
        """Get the browser builtin instance if loaded."""
        return self._get_browser_builtin_impl(self._builtin_loader)
