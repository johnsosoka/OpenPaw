"""Agent middleware for tool execution interception.

Provides middleware components for:
- Queue awareness (steer/interrupt modes)
- Queue check (before model calls)
- Approval gates (human-in-the-loop)
- LLM hooks (thinking token stripping, reasoning sanitization)
- Tool call sanitization (checkpoint poisoning prevention)
"""

from openpaw.agent.middleware.approval import ApprovalRequiredError, ApprovalToolMiddleware
from openpaw.agent.middleware.llm_hooks import (
    THINKING_TAG_PATTERN,
    build_post_model_hook,
    build_pre_model_hook,
)
from openpaw.agent.middleware.queue_aware import (
    STEER_EXEMPT_TOOLS,
    InterruptSignalError,
    QueueAwareToolMiddleware,
    SteerState,
)
from openpaw.agent.middleware.queue_check import get_queue_check_middleware
from openpaw.agent.middleware.tool_call_sanitizer import get_tool_call_sanitizer

__all__ = [
    "ApprovalRequiredError",
    "ApprovalToolMiddleware",
    "InterruptSignalError",
    "QueueAwareToolMiddleware",
    "STEER_EXEMPT_TOOLS",
    "SteerState",
    "get_queue_check_middleware",
    "get_tool_call_sanitizer",
    "THINKING_TAG_PATTERN",
    "build_post_model_hook",
    "build_pre_model_hook",
]
