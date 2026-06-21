"""Response processing for agent runs.

Extracts text from LangGraph message output, handles structured content blocks
(Bedrock), and strips thinking tokens.
"""

import logging
from typing import Any

from openpaw.agent.middleware.llm_hooks import THINKING_TAG_PATTERN

logger = logging.getLogger(__name__)


class ResponseProcessor:
    """Processes raw agent output into user-facing response text."""

    def __init__(self, strip_thinking: bool, log_label: str, model_id: str):
        """Initialize the response processor.

        Args:
            strip_thinking: Whether to strip thinking tokens from responses.
            log_label: Label for logging (workspace name or profile label).
            model_id: Current model identifier for logging.
        """
        self._strip_thinking = strip_thinking
        self._log_label = log_label
        self._model_id = model_id

    @staticmethod
    def strip_thinking_tokens(text: str) -> str:
        """Strip thinking tokens from string content.

        Handles edge cases where ThinkingTokenMiddleware doesn't catch
        <thinking> tags in string content.
        """
        cleaned = THINKING_TAG_PATTERN.sub("", text)
        return cleaned.strip()

    @staticmethod
    def extract_text_from_content(content: Any) -> str:
        """Extract text from message content, handling both string and structured formats.

        Bedrock models return content as a list of typed blocks:
        [{"type": "thinking", ...}, {"type": "text", "text": "answer"}]

        Blocks may be dicts or objects with type/text attributes.

        Returns:
            Extracted text content, or empty string if no text blocks found.
        """
        if not isinstance(content, list):
            return str(content)

        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    text_parts.append(block["text"])
            elif hasattr(block, "type") and hasattr(block, "text"):
                if getattr(block, "type") == "text" and getattr(block, "text"):
                    text_parts.append(block.text)
        return "\n".join(text_parts)

    def process(self, final_messages: list[Any]) -> str:
        """Extract and process the response text from final messages.

        Args:
            final_messages: List of messages from the agent stream.

        Returns:
            Processed response text.
        """
        if not final_messages:
            return ""

        last_message = final_messages[-1]
        if hasattr(last_message, "content"):
            raw_response = self.extract_text_from_content(last_message.content)
        else:
            raw_response = str(last_message)

        # Fallback: strip thinking tags from string content if middleware missed them
        if self._strip_thinking and "<thinking>" in raw_response.lower():
            logger.warning(
                f"Fallback thinking stripping triggered "
                f"(workspace: {self._log_label}, model: {self._model_id})"
            )
            return self.strip_thinking_tokens(raw_response)
        return raw_response
