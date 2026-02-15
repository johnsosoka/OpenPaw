"""Shared workspace context for component dependency injection."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openpaw.agent.metrics import TokenUsageLogger
from openpaw.core.queue.lane import LaneQueue
from openpaw.core.queue.manager import QueueManager
from openpaw.runtime.session.archiver import ConversationArchiver
from openpaw.runtime.session.manager import SessionManager
from openpaw.stores.subagent import SubAgentStore
from openpaw.stores.task import TaskStore


@dataclass
class WorkspaceContext:
    """Shared dependencies for workspace components.

    Created once during WorkspaceRunner initialization and passed to
    sub-components (MessageProcessor, LifecycleManager, AgentFactory).
    Groups the "data foundation" that multiple components need.
    """

    # Identity
    workspace_name: str
    workspace_path: Path
    workspace: Any  # AgentWorkspace (avoid circular import)
    merged_config: dict[str, Any]
    timezone: str

    # Stores
    task_store: TaskStore
    subagent_store: SubAgentStore
    token_logger: TokenUsageLogger

    # Queue
    lane_queue: LaneQueue
    queue_manager: QueueManager

    # Session
    session_manager: SessionManager
    conversation_archiver: ConversationArchiver

    # Checkpointer (set during start())
    db_path: Path = field(default_factory=lambda: Path())

    # Logger
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))
