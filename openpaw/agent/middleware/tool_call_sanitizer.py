"""Tool call sanitizer middleware.

Sanitizes model-generated tool call names to comply with provider constraints
(e.g., AWS Bedrock requires [a-zA-Z0-9_-]+ and max 64 chars). Prevents
checkpoint poisoning from hallucinated invalid tool names.
"""

import logging
import re
from typing import Any

from langchain.agents.middleware import ModelResponse, wrap_model_call
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

# Bedrock tool name validation pattern (AWS requirement)
# Define locally to avoid circular import dependency on runner.py
BEDROCK_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
MAX_TOOL_NAME_LENGTH = 64


def _sanitize_tool_name(name: str) -> str:
    """Sanitize a tool name to comply with Bedrock constraints.

    Replaces invalid characters with underscores and truncates to max length.
    Ensures the result is non-empty and matches [a-zA-Z0-9_-]+.

    Args:
        name: Original tool name from model response.

    Returns:
        Sanitized tool name.
    """
    # Replace any character not in [a-zA-Z0-9_-] with underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)

    # Collapse consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)

    # Strip leading/trailing underscores
    sanitized = sanitized.strip("_")

    # Truncate to max length
    if len(sanitized) > MAX_TOOL_NAME_LENGTH:
        sanitized = sanitized[:MAX_TOOL_NAME_LENGTH].rstrip("_")

    # Fallback if empty after sanitization
    if not sanitized:
        sanitized = "unknown_tool"

    return sanitized


@wrap_model_call
async def tool_call_sanitizer(request: Any, handler: Any) -> ModelResponse:
    """Sanitize tool call names in model responses before checkpointing.

    Intercepts model responses and fixes tool call names that violate
    provider constraints. This prevents checkpoint poisoning where an
    invalid tool name in the conversation history causes all subsequent
    API calls to fail with validation errors.

    Args:
        request: Model request (passed through to handler).
        handler: Async callable that invokes the actual LLM.

    Returns:
        ModelResponse with sanitized tool call names.
    """
    response = await handler(request)

    if not response.result:
        return response

    for message in response.result:
        if not isinstance(message, AIMessage):
            continue

        if not message.tool_calls:
            continue

        for tool_call in message.tool_calls:
            original_name = tool_call.get("name", "")
            if not original_name:
                continue

            # Check if name is already valid
            if (
                BEDROCK_TOOL_NAME_PATTERN.match(original_name)
                and len(original_name) <= MAX_TOOL_NAME_LENGTH
            ):
                continue

            # Sanitize the invalid name
            fixed_name = _sanitize_tool_name(original_name)
            tool_call["name"] = fixed_name

            logger.warning(
                f"Sanitized invalid tool call name: '{original_name}' -> '{fixed_name}'"
            )

    return response


def get_tool_call_sanitizer() -> Any:
    """Return the @wrap_model_call middleware instance.

    Returns:
        AgentMiddleware instance for tool call sanitization.
    """
    return tool_call_sanitizer
