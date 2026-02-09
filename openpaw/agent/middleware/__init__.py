"""Agent middleware for tool execution interception.

Provides middleware components for:
- Queue awareness (steer/interrupt modes)
- Approval gates (human-in-the-loop)
- LLM hooks (thinking token stripping, reasoning sanitization)
"""

from openpaw.agent.middleware.approval import ApprovalRequiredError, ApprovalToolMiddleware
from openpaw.agent.middleware.llm_hooks import (
    THINKING_TAG_PATTERN,
    build_post_model_hook,
    build_pre_model_hook,
)
from openpaw.agent.middleware.queue_aware import InterruptSignalError, QueueAwareToolMiddleware

__all__ = [
    "ApprovalRequiredError",
    "ApprovalToolMiddleware",
    "InterruptSignalError",
    "QueueAwareToolMiddleware",
    "THINKING_TAG_PATTERN",
    "build_post_model_hook",
    "build_pre_model_hook",
]
