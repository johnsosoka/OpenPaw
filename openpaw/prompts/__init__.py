"""Centralized prompt templates for the OpenPaw framework.

All framework prompt text — system prompt sections, runtime injection
templates, processor output formats, and command prompts — lives here.
"""

from openpaw.prompts.commands import COMPACTED_TEMPLATE, SUMMARIZE_PROMPT
from openpaw.prompts.framework import (
    FRAMEWORK_ORIENTATION,
    SECTION_SHELL_HYGIENE,
    build_capability_summary,
)
from openpaw.prompts.heartbeat import (
    ACTIVE_TASKS_TEMPLATE,
    HEARTBEAT_PROMPT,
    build_task_summary,
)
from openpaw.prompts.system_events import (
    FOLLOWUP_TEMPLATE,
    INTERRUPT_NOTIFICATION,
    STEER_SKIP_MESSAGE,
    SUBAGENT_COMPLETED_SHORT_TEMPLATE,
    SUBAGENT_COMPLETED_TEMPLATE,
    SUBAGENT_FAILED_TEMPLATE,
    SUBAGENT_TIMED_OUT_TEMPLATE,
    TIMEOUT_NOTIFICATION_GENERIC,
    TIMEOUT_NOTIFICATION_TEMPLATE,
    TIMEOUT_WARNING_TEMPLATE,
    TOOL_DENIED_TEMPLATE,
)

__all__ = [
    "ACTIVE_TASKS_TEMPLATE",
    "COMPACTED_TEMPLATE",
    "FOLLOWUP_TEMPLATE",
    "FRAMEWORK_ORIENTATION",
    "HEARTBEAT_PROMPT",
    "INTERRUPT_NOTIFICATION",
    "SECTION_SHELL_HYGIENE",
    "STEER_SKIP_MESSAGE",
    "SUBAGENT_COMPLETED_SHORT_TEMPLATE",
    "SUBAGENT_COMPLETED_TEMPLATE",
    "SUBAGENT_FAILED_TEMPLATE",
    "SUBAGENT_TIMED_OUT_TEMPLATE",
    "SUMMARIZE_PROMPT",
    "TIMEOUT_NOTIFICATION_GENERIC",
    "TIMEOUT_NOTIFICATION_TEMPLATE",
    "TIMEOUT_WARNING_TEMPLATE",
    "TOOL_DENIED_TEMPLATE",
    "build_capability_summary",
    "build_task_summary",
]
