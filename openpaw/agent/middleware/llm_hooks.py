"""Pre/post model hooks for LangGraph create_react_agent.

These hooks intercept the agent state before and after model calls,
enabling message sanitization, thinking token stripping, and other
cross-cutting concerns.

Usage with create_react_agent:
    from openpaw.agent.middleware.llm_hooks import build_pre_model_hook, build_post_model_hook

    agent = create_react_agent(
        model=model,
        tools=tools,
        pre_model_hook=build_pre_model_hook(strip_reasoning=True),
        post_model_hook=build_post_model_hook(strip_thinking=True),
    )
"""

import logging
import re
from typing import Any

from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

# Pattern to match <think>...</think> blocks (non-greedy, multiline)
THINKING_TAG_PATTERN = re.compile(r"<think>[\s\S]*?</think>\s*", re.IGNORECASE)


def _sanitize_reasoning_content(state: dict[str, Any]) -> dict[str, Any]:
    """Strip reasoning_content from all AI messages in conversation history.

    Kimi K2.5 (and similar thinking models) populate a `reasoning_content`
    field on assistant messages when thinking mode is active. If these messages
    are replayed in conversation history while thinking is disabled, the API
    returns a 400 error: "thinking is enabled but reasoning_content is missing".

    This hook removes `reasoning_content` from all historical AI messages,
    preventing the API from detecting stale thinking artifacts.
    """
    messages = state.get("messages", [])
    sanitized = False

    for msg in messages:
        if not isinstance(msg, AIMessage):
            continue

        # Strip reasoning_content from additional_kwargs
        if hasattr(msg, "additional_kwargs") and "reasoning_content" in msg.additional_kwargs:
            del msg.additional_kwargs["reasoning_content"]
            sanitized = True

        # Strip from response_metadata if present
        if hasattr(msg, "response_metadata") and "reasoning_content" in getattr(msg, "response_metadata", {}):
            del msg.response_metadata["reasoning_content"]
            sanitized = True

    if sanitized:
        logger.debug("Stripped reasoning_content from conversation history")

    return state


def _strip_thinking_tokens(state: dict[str, Any]) -> dict[str, Any]:
    """Strip thinking tokens from the last AI message (post-model hook).

    Removes <think>...</think> tags from string content and thinking-type
    blocks from structured content (Claude format). Only operates on the
    last message since it runs after each model call.
    """
    messages = state.get("messages", [])
    if not messages:
        return state

    last_message = messages[-1]
    if not isinstance(last_message, AIMessage):
        return state

    # Handle structured content (list of blocks)
    if isinstance(last_message.content, list):
        last_message.content = [
            block
            for block in last_message.content
            if not (isinstance(block, dict) and block.get("type") == "thinking")
            and not (hasattr(block, "type") and getattr(block, "type", None) == "thinking")
        ]

    # Handle string content
    elif isinstance(last_message.content, str):
        cleaned = THINKING_TAG_PATTERN.sub("", last_message.content)
        last_message.content = cleaned.strip()

    return state


def build_pre_model_hook(
    strip_reasoning: bool = False,
) -> Any | None:
    """Build a pre-model hook from enabled middleware options.

    Args:
        strip_reasoning: Strip reasoning_content from AI messages in history.
            Required for Kimi K2.5 and other thinking models to prevent
            stale reasoning artifacts from causing API errors.

    Returns:
        A callable hook, or None if no middleware is enabled.
    """
    if not strip_reasoning:
        return None

    def pre_model_hook(state: dict[str, Any]) -> dict[str, Any]:
        if strip_reasoning:
            state = _sanitize_reasoning_content(state)
        return state

    return pre_model_hook


def build_post_model_hook(
    strip_thinking: bool = False,
) -> Any | None:
    """Build a post-model hook from enabled middleware options.

    Args:
        strip_thinking: Strip <think>...</think> tags and thinking content
            blocks from model responses. Required for models that emit
            visible reasoning tokens (Kimi K2 Thinking, etc.).

    Returns:
        A callable hook, or None if no middleware is enabled.
    """
    if not strip_thinking:
        return None

    def post_model_hook(state: dict[str, Any]) -> dict[str, Any]:
        if strip_thinking:
            state = _strip_thinking_tokens(state)
        return state

    return post_model_hook
