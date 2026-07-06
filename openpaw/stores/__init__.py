"""Persistence layer for OpenPaw domain models.

This package contains store classes for managing persistent state:
- TaskStore: Task tracking and lifecycle management
- SubAgentStore: Sub-agent request and result persistence
- DynamicCronStore: Agent self-scheduled task storage
- ApprovalGateManager: Human-in-the-loop approval state
- SkillStore: Validated, atomic skill writes with lifecycle events
"""

from openpaw.runtime.approval import ApprovalGateManager, PendingApproval
from openpaw.stores.cron import DynamicCronStore, create_interval_task, create_once_task
from openpaw.stores.skill import (
    SkillLimits,
    SkillRejectedError,
    SkillStore,
    SkillValidationError,
)
from openpaw.stores.subagent import SubAgentStore, create_subagent_request
from openpaw.stores.task import TaskStore, create_task

__all__ = [
    # Task store
    "TaskStore",
    "create_task",
    # SubAgent store
    "SubAgentStore",
    "create_subagent_request",
    # Cron store
    "DynamicCronStore",
    "create_once_task",
    "create_interval_task",
    # Approval store
    "ApprovalGateManager",
    "PendingApproval",
    # Skill store
    "SkillStore",
    "SkillLimits",
    "SkillRejectedError",
    "SkillValidationError",
]
