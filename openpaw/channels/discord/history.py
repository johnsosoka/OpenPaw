"""Discord channel history fetching."""

import logging
from typing import Any

from openpaw.model.channel import ChannelHistoryEntry

logger = logging.getLogger(__name__)


class DiscordHistoryFetcher:
    """Fetch recent messages from a Discord channel."""

    def __init__(self, client: Any, resolve_channel: Any) -> None:
        self._client = client
        self._resolve_channel = resolve_channel

    async def fetch_history(
        self,
        channel_id: str,
        limit: int = 25,
        before_message_id: str | None = None,
    ) -> list[ChannelHistoryEntry]:
        """Fetch recent messages from a Discord channel.

        Retrieves up to `limit` messages in reverse-chronological order
        from Discord's API, then returns them in chronological order (oldest
        first) after filtering out the bot's own messages.

        Args:
            channel_id: Discord snowflake channel ID as a string.
            limit: Maximum number of messages to fetch (before self-filtering).
            before_message_id: When provided, fetch only messages sent before
                this message ID (for pagination). Optional.

        Returns:
            List of ChannelHistoryEntry in chronological order (oldest first).
            Returns an empty list on any error.
        """
        try:
            channel = await self._resolve_channel(int(channel_id))

            before_obj: Any | None = None
            if before_message_id is not None:
                before_obj = self._make_before_object(before_message_id)

            entries: list[ChannelHistoryEntry] = []
            async for msg in channel.history(limit=limit, before=before_obj):
                # Skip the bot's own messages — they are not useful context
                if self._client and msg.author == self._client.user:
                    continue

                attachments_summary: str | None = None
                if msg.attachments:
                    names = [a.filename for a in msg.attachments]
                    count = len(names)
                    label = "file" if count == 1 else "files"
                    attachments_summary = f"[{count} {label}: {', '.join(names)}]"

                entries.append(
                    ChannelHistoryEntry(
                        timestamp=msg.created_at,
                        user_id=str(msg.author.id),
                        display_name=msg.author.display_name,
                        content=msg.content or "",
                        is_bot=msg.author.bot,
                        attachments_summary=attachments_summary,
                        message_id=str(msg.id),
                    )
                )

            # Discord returns newest-first; reverse to chronological order
            entries.reverse()
            return entries

        except Exception:
            logger.warning(
                "Failed to fetch channel history for channel %s", channel_id, exc_info=True
            )
            return []

    def _make_before_object(self, before_message_id: str) -> Any:
        """Create a Discord Object for the before-message pagination."""
        import discord

        return discord.Object(id=int(before_message_id))
