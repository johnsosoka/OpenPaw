"""OpenPaw domain models - pure business entities.

This package contains stable dataclasses and enums representing core business
concepts. These models have no dependencies on infrastructure or application
logic, making them the foundation of the codebase.
"""

# Message domain
# Cron domain
from openpaw.model.cron import CronDefinition, CronOutputConfig, DynamicCronTask
from openpaw.model.message import Attachment, Message, MessageDirection

# Session domain
from openpaw.model.session import SessionState

# Sub-agent domain
from openpaw.model.subagent import SubAgentRequest, SubAgentResult, SubAgentStatus

# Task domain
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
    "CronDefinition",
    "CronOutputConfig",
    "DynamicCronTask",
]
