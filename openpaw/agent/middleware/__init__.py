"""Agent middleware for tool execution interception.

Provides middleware components for:
- Per-tool timeouts (budget protection)
- Queue awareness (steer/interrupt modes)
- Approval gates (human-in-the-loop)
- LLM hooks (thinking token stripping, reasoning sanitization)
- Status reminders (nudge agents to call send_message during long runs)
"""

from openpaw.agent.middleware.approval import ApprovalRequiredError, ApprovalToolMiddleware
from openpaw.agent.middleware.llm_hooks import (
    THINKING_TAG_PATTERN,
    ThinkingTokenMiddleware,
    build_post_model_hook,
    build_pre_model_hook,
)
from openpaw.agent.middleware.plan_event_bridge import PlanEventBridge
from openpaw.agent.middleware.queue_aware import InterruptSignalError, QueueAwareToolMiddleware
from openpaw.agent.middleware.status_reminder import (
    StatusReminderMiddleware,
    inject_framework_instruction,
)
from openpaw.agent.middleware.status_update import StatusUpdateMiddleware
from openpaw.agent.middleware.subagent_status import SubAgentToolMiddleware
from openpaw.agent.middleware.todo_list import TodoListMiddleware
from openpaw.agent.middleware.tool_timeout import ToolTimeoutMiddleware

__all__ = [
    "ApprovalRequiredError",
    "ApprovalToolMiddleware",
    "InterruptSignalError",
    "PlanEventBridge",
    "QueueAwareToolMiddleware",
    "THINKING_TAG_PATTERN",
    "StatusReminderMiddleware",
    "StatusUpdateMiddleware",
    "SubAgentToolMiddleware",
    "ThinkingTokenMiddleware",
    "TodoListMiddleware",
    "ToolTimeoutMiddleware",
    "build_post_model_hook",
    "build_pre_model_hook",
    "inject_framework_instruction",
]
