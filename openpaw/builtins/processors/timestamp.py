"""Timestamp processor for adding temporal context to messages."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from openpaw.builtins.base import (
    BaseBuiltinProcessor,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
    ProcessorResult,
)
from openpaw.model.message import Message

logger = logging.getLogger(__name__)


class TimestampProcessor(BaseBuiltinProcessor):
    """Prepends current date/time context to inbound messages.

    Adds temporal awareness to the agent by including formatted timestamps
    at the beginning of each message. Useful for time-sensitive operations,
    logging, and providing context about when interactions occur.

    No prerequisites required - always available if enabled.

    Config options:
        timezone: Timezone string (default: "UTC")
                  Examples: "America/Los_Angeles", "Europe/London", "Asia/Tokyo"
        format: Datetime format string (default: "%Y-%m-%d %H:%M %Z")
                Uses standard strftime format codes
        template: Template for the context line (default: "[Current time: {datetime}]")
                  Use {datetime} as placeholder for formatted timestamp
    """

    metadata = BuiltinMetadata(
        name="timestamp",
        display_name="Message Timestamp Context",
        description="Prepends current date/time to inbound messages for temporal awareness",
        builtin_type=BuiltinType.PROCESSOR,
        group="context",
        prerequisites=BuiltinPrerequisite(),
        priority=30,
    )

    async def process_inbound(self, message: Message) -> ProcessorResult:
        """Prepend timestamp context to message content.

        Args:
            message: The incoming message from a channel.

        Returns:
            ProcessorResult with timestamp prepended to message content.
        """
        # Get configuration with defaults
        timezone_str = self.config.get("timezone", "UTC")
        format_str = self.config.get("format", "%Y-%m-%d %H:%M %Z")
        template = self.config.get("template", "[Current time: {datetime}]")

        try:
            # Get current time in configured timezone
            tz = ZoneInfo(timezone_str)
            now = datetime.now(tz)

            # Format timestamp
            formatted_time = now.strftime(format_str)

            # Build context line from template
            context_line = template.format(datetime=formatted_time)

            # Prepend to message content
            new_content = f"{context_line}\n\n{message.content}"

            logger.debug(f"Prepended timestamp: {context_line}")

        except Exception as e:
            # Log error but don't break message flow
            logger.error(f"Failed to add timestamp: {e}")
            new_content = message.content

        # Create new message with updated content
        updated_message = Message(
            id=message.id,
            channel=message.channel,
            session_key=message.session_key,
            user_id=message.user_id,
            content=new_content,
            direction=message.direction,
            timestamp=message.timestamp,
            reply_to_id=message.reply_to_id,
            metadata={**message.metadata, "timestamp_added": True},
            attachments=message.attachments,
        )

        return ProcessorResult(message=updated_message)
