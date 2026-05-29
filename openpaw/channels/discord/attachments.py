"""Discord attachment download utilities."""

import logging
from typing import Any

from openpaw.channels.helpers import map_mime_type_to_attachment_type
from openpaw.model.message import Attachment

logger = logging.getLogger(__name__)


class DiscordAttachmentDownloader:
    """Download attachments from Discord messages."""

    async def download_all(self, discord_message: Any) -> list[Attachment]:
        """Download all attachments from a discord.Message.

        Determines the OpenPaw attachment type from the Discord MIME type.

        Args:
            discord_message: The discord.Message whose attachments to download.

        Returns:
            List of Attachment objects with raw bytes populated.
        """
        result: list[Attachment] = []

        for discord_attachment in discord_message.attachments:
            try:
                data = await discord_attachment.read()
            except Exception as e:
                logger.error(
                    "Failed to download attachment '%s': %s",
                    discord_attachment.filename,
                    e,
                )
                continue

            content_type = discord_attachment.content_type or "application/octet-stream"
            attachment_type = map_mime_type_to_attachment_type(content_type)

            result.append(
                Attachment(
                    type=attachment_type,
                    data=data,
                    filename=discord_attachment.filename,
                    mime_type=content_type,
                    metadata={"file_size": discord_attachment.size},
                )
            )

            logger.info(
                "Downloaded attachment: %s (%d bytes, %s)",
                discord_attachment.filename,
                discord_attachment.size,
                content_type,
            )

        return result
