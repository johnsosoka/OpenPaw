"""Workspace initialization service for OpenPaw."""

import logging
from typing import Any

from openpaw.agent.metrics import TokenUsageLogger
from openpaw.agent.middleware import (
    ApprovalToolMiddleware,
    QueueAwareToolMiddleware,
    ToolTimeoutMiddleware,
)
from openpaw.agent.middleware.status_reminder import StatusReminderMiddleware
from openpaw.agent.runner import AgentRunner
from openpaw.builtins.base import BaseBuiltinProcessor
from openpaw.builtins.loader import BuiltinLoader
from openpaw.core.config import Config, merge_configs
from openpaw.core.config.models import ApprovalGatesConfig, ToolTimeoutsConfig
from openpaw.runtime.approval import ApprovalGateManager
from openpaw.runtime.session.archiver import ConversationArchiver
from openpaw.runtime.session.manager import SessionManager
from openpaw.stores.subagent import SubAgentStore
from openpaw.stores.task import TaskStore
from openpaw.workspace.agent_factory import AgentFactory, filter_workspace_tools
from openpaw.workspace.message_processor import MessageProcessor
from openpaw.workspace.tool_loader import load_workspace_tools


class WorkspaceInitializer:
    """Initializes workspace components."""

    def __init__(
        self,
        config: Config,
        workspace: Any,
        merged_config: dict[str, Any],
        logger: logging.Logger,
    ):
        self._config = config
        self._workspace = workspace
        self._merged_config = merged_config
        self._logger = logger

    def init_stores(self) -> tuple[TaskStore, SubAgentStore, TokenUsageLogger]:
        """Initialize persistence stores and token logger."""
        task_store = TaskStore(self._workspace.path)
        subagent_store = SubAgentStore(self._workspace.path)
        token_logger = TokenUsageLogger(self._workspace.path)
        return task_store, subagent_store, token_logger

    def init_memory(self) -> tuple[Any, Any, Any, ConversationArchiver]:
        """Initialize memory search infrastructure and conversation archiver."""
        vector_store: Any | None = None
        embedding_provider: Any | None = None
        indexer: Any | None = None

        memory_config = (
            self._workspace.config.memory if self._workspace.config else None
        )
        if memory_config and memory_config.enabled:
            try:
                from openpaw.stores.vector.factory import (
                    create_embedding_provider,
                    create_vector_store,
                )
                from openpaw.stores.vector.indexer import ConversationIndexer

                vector_store = create_vector_store(
                    provider=memory_config.vector_store.provider,
                    config=memory_config.vector_store.model_dump(),
                    workspace_path=self._workspace.path,
                )
                embedding_provider = create_embedding_provider(
                    provider=memory_config.embedding.provider,
                    config=memory_config.embedding.model_dump(),
                )
                indexer = ConversationIndexer(
                    vector_store=vector_store,
                    embedding_provider=embedding_provider,
                )
                self._logger.info("Memory search infrastructure initialized")
            except Exception as e:
                self._logger.error(f"Failed to initialize memory search: {e}")
                vector_store = None
                embedding_provider = None
                indexer = None

        workspace_timezone: str = (
            self._workspace.config.timezone if self._workspace.config else "UTC"
        )
        conversation_archiver = ConversationArchiver(
            workspace_path=self._workspace.path,
            workspace_name=self._workspace.name,
            timezone=workspace_timezone,
            indexer=indexer,
        )
        return vector_store, embedding_provider, indexer, conversation_archiver

    def init_builtins(
        self,
        task_store: TaskStore,
        builtin_loader: BuiltinLoader | None = None,
        workspace_tools: list[Any] | None = None,
    ) -> tuple[
        BuiltinLoader,
        list[Any],
        list[BaseBuiltinProcessor],
        list[Any],
        list[str],
        dict[int, str],
        bool,
    ]:
        """Load builtin tools, processors, and workspace tools."""
        workspace_builtins_config = None
        if self._workspace.config and self._workspace.config.builtins:
            workspace_builtins_config = self._workspace.config.builtins

        # Aggregate user_aliases from all channels (first-wins on conflict)
        user_aliases: dict[int, str] = {}
        for ch_config in self._merged_config.get("channels", []):
            for uid, name in ch_config.get("user_aliases", {}).items():
                if uid not in user_aliases:
                    user_aliases[uid] = name

        if builtin_loader is None:
            # Use first channel config for builtin loader compatibility
            workspace_channel_config = (
                self._merged_config.get("channels") or [{}]
            )[0]

            builtin_loader = BuiltinLoader(
                global_config=self._config.builtins,
                workspace_config=workspace_builtins_config,
                workspace_path=self._workspace.path,
                channel_config=workspace_channel_config,
                workspace_timezone=self._workspace_timezone(),
                task_store=task_store,
            )

        builtin_tools = builtin_loader.load_tools()
        processors: list[BaseBuiltinProcessor] = builtin_loader.load_processors()
        enabled_builtin_names = builtin_loader.get_loaded_tool_names()

        # Determine if any channel has persistent logging enabled
        channel_logging_enabled = any(
            ch.get("channel_log", {}).get("enabled", False)
            for ch in self._merged_config.get("channels", [])
        )

        if builtin_tools:
            self._logger.info(
                f"Loaded {len(builtin_tools)} builtin tools for workspace: {self._workspace.name}"
            )
        if processors:
            self._logger.info(
                f"Loaded {len(processors)} builtin processors for workspace: {self._workspace.name}"
            )

        workspace_tools = load_workspace_tools(
            self._workspace.tools_path, workspace_root=self._workspace.path
        )
        if workspace_tools:
            tool_names = [t.name for t in workspace_tools]
            self._logger.info(
                f"Loaded {len(workspace_tools)} workspace tools: {tool_names}"
            )

        if workspace_tools and self._workspace.config:
            workspace_tools = filter_workspace_tools(
                workspace_tools,
                self._workspace.config.workspace_tools,
                self._logger,
            )

        return (
            builtin_loader,
            builtin_tools,
            processors,
            workspace_tools,
            enabled_builtin_names,
            user_aliases,
            channel_logging_enabled,
        )

    def init_agent(
        self,
        builtin_loader: BuiltinLoader,
        builtin_tools: list[Any],
        workspace_tools: list[Any],
        enabled_builtin_names: list[str],
        user_aliases: dict[int, str],
        token_logger: TokenUsageLogger,
        conversation_archiver: ConversationArchiver,
        session_manager: SessionManager,
        queue_manager: Any,
        channel_logging_enabled: bool = False,
    ) -> tuple[
        QueueAwareToolMiddleware,
        ApprovalToolMiddleware,
        ApprovalGateManager | None,
        AgentFactory,
        AgentRunner,
        MessageProcessor,
        ToolTimeoutMiddleware,
        StatusReminderMiddleware | None,
    ]:
        """Set up middleware, agent factory, agent runner, and message processor."""
        # Create middleware
        queue_middleware = QueueAwareToolMiddleware()
        approval_middleware = ApprovalToolMiddleware()
        approval_manager: ApprovalGateManager | None = None

        approval_config = self._get_approval_config()
        if approval_config and approval_config.enabled:
            approval_manager = ApprovalGateManager(approval_config)
            self._logger.info("Approval gates enabled")

        # Resolve model string from merged config
        agent_config = self._merged_config.get("model", {})
        model_str = agent_config.get("model", self._config.agent.model)
        if agent_config.get("provider"):
            model_str = f"{agent_config['provider']}:{agent_config['model']}"
        self._logger.info(f"Initializing agent with model: {model_str}")

        # Extract extra model kwargs beyond the known set.
        known_model_keys = {
            "provider",
            "model",
            "api_key",
            "temperature",
            "max_turns",
            "region",
            "timeout_seconds",
            "max_output_tokens",
            "max_retries",
        }
        extra_model_kwargs = {
            k: v
            for k, v in agent_config.items()
            if k not in known_model_keys and v is not None
        }

        # Workspace-level max_output_tokens becomes "max_tokens" for LangChain providers
        workspace_max_output_tokens = agent_config.get("max_output_tokens")
        if workspace_max_output_tokens is not None:
            extra_model_kwargs["max_tokens"] = workspace_max_output_tokens
            self._logger.info(
                f"Applying workspace max_output_tokens cap: {workspace_max_output_tokens}"
            )

        # Forward max_retries explicitly (default 3 from WorkspaceModelConfig).
        workspace_max_retries = agent_config.get("max_retries", 3)
        extra_model_kwargs["max_retries"] = workspace_max_retries
        if workspace_max_retries and workspace_max_retries > 0:
            self._logger.info(f"Retry config: max_retries={workspace_max_retries}")

        if extra_model_kwargs:
            self._logger.info(
                f"Passing extra model kwargs: {list(extra_model_kwargs.keys())}"
            )

        # Build middleware list (order matters: timeout → status_reminder → queue → approval)
        tool_timeouts_config = self._get_tool_timeouts_config()
        tool_timeout_middleware = ToolTimeoutMiddleware(tool_timeouts_config)
        middlewares = [
            tool_timeout_middleware.get_middleware(),
            queue_middleware.get_middleware(),
        ]
        if approval_manager:
            middlewares.append(approval_middleware.get_middleware())

        # Create status reminder middleware only when send_message builtin is active.
        status_reminder_middleware: StatusReminderMiddleware | None = None
        if "send_message" in enabled_builtin_names:
            status_reminder_config = (
                self._workspace.config.status_reminder
                if self._workspace.config
                else None
            )
            if status_reminder_config is None:
                from openpaw.core.config.models import StatusReminderConfig

                status_reminder_config = StatusReminderConfig()
            status_reminder_middleware = StatusReminderMiddleware(
                status_reminder_config
            )
            # Insert after timeout middleware, before queue/approval
            middlewares.insert(1, status_reminder_middleware)
            self._logger.info(
                "Status reminder middleware enabled (threshold=%d)",
                status_reminder_config.threshold,
            )

        # Create agent factory and initial agent runner (checkpointer added in start())
        agent_factory = AgentFactory(
            workspace=self._workspace,
            model=model_str,
            api_key=agent_config.get(
                "api_key", self._config.agent.api_key
            ),
            max_turns=agent_config.get(
                "max_turns", self._config.agent.max_turns
            ),
            temperature=agent_config.get(
                "temperature", self._config.agent.temperature
            ),
            region=agent_config.get("region"),
            timeout_seconds=agent_config.get("timeout_seconds", 300.0),
            builtin_tools=builtin_tools,
            workspace_tools=workspace_tools,
            enabled_builtin_names=enabled_builtin_names,
            extra_model_kwargs=extra_model_kwargs,
            middleware=middlewares,
            logger=self._logger,
            provider_catalog=self._config.providers,
            channel_logging_enabled=channel_logging_enabled,
        )
        agent_runner = agent_factory.create_agent(checkpointer=None)

        # Create message processor
        message_processor = MessageProcessor(
            agent_runner=agent_runner,
            session_manager=session_manager,
            queue_manager=queue_manager,
            builtin_loader=builtin_loader,
            queue_middleware=queue_middleware,
            approval_middleware=approval_middleware,
            approval_manager=approval_manager,
            workspace_name=self._workspace.name,
            token_logger=token_logger,
            logger=self._logger,
            conversation_archiver=conversation_archiver,
            auto_compact_config=(
                self._workspace.config.auto_compact
                if self._workspace.config
                else None
            ),
            user_aliases=user_aliases,
            session_ttl_minutes=self._merged_config.get(
                "session_ttl_minutes", 180
            ),
            lifecycle_config=(
                self._workspace.config.lifecycle
                if self._workspace.config
                else None
            ),
            status_reminder_middleware=status_reminder_middleware,
        )

        return (
            queue_middleware,
            approval_middleware,
            approval_manager,
            agent_factory,
            agent_runner,
            message_processor,
            tool_timeout_middleware,
            status_reminder_middleware,
        )

    @staticmethod
    def merge_workspace_config(
        global_config: Config, workspace: Any
    ) -> dict[str, Any]:
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

        # Channels: list of channel configs (already normalized by model_validator)
        if workspace.config.channels:
            workspace_dict["channels"] = [
                ch.model_dump(exclude_none=True) for ch in workspace.config.channels
            ]

        return merge_configs(global_dict, workspace_dict)

    def _get_approval_config(self) -> ApprovalGatesConfig | None:
        """Get approval gates config from workspace or global."""
        if self._workspace.config and self._workspace.config.approval_gates:
            if self._workspace.config.approval_gates.enabled:
                return self._workspace.config.approval_gates
        if hasattr(self._config, "approval_gates") and self._config.approval_gates:
            if self._config.approval_gates.enabled:
                return self._config.approval_gates
        return None

    def _get_tool_timeouts_config(self) -> ToolTimeoutsConfig:
        """Get tool timeouts config from workspace or global.

        Returns:
            ToolTimeoutsConfig (always returns a valid config, uses defaults if not configured).
        """
        if self._workspace.config:
            return self._workspace.config.tool_timeouts
        return self._config.tool_timeouts

    def _workspace_timezone(self) -> str:
        """Return the workspace timezone string."""
        return (
            self._workspace.config.timezone
            if self._workspace.config
            else "UTC"
        )
