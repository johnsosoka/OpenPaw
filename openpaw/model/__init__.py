"""OpenPaw domain models - pure business entities.

This package contains stable dataclasses and enums representing core business
concepts. These models have no dependencies on infrastructure or application
logic, making them the foundation of the codebase.

Note: CronDefinition and CronOutputConfig (Pydantic + APScheduler) live in
openpaw.core.config.models. Only the pure DynamicCronTask dataclass belongs here.
"""

from openpaw.model.cron import DynamicCronTask
from openpaw.model.message import Attachment, Message, MessageDirection
from openpaw.model.session import SessionState
from openpaw.model.subagent import SubAgentRequest, SubAgentResult, SubAgentStatus
from openpaw.model.task import Task, TaskPriority, TaskStatus, TaskType

__all__ = [
    # Message
    "Attachment",
    "Message",
    "MessageDirection",
    # Task
    "Task",
    "TaskPriority",
    "TaskStatus",
    "TaskType",
    # Session
    "SessionState",
    # Sub-agent
    "SubAgentRequest",
    "SubAgentResult",
    "SubAgentStatus",
    # Cron
    "DynamicCronTask",
]
