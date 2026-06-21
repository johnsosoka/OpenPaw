"""Gmail attachment download handler."""

import asyncio
import base64
import logging
from typing import Any

from openpaw.builtins.tools.email.base import EmailAttachment
from openpaw.builtins.tools.email.gmail.base import _format_api_error, _pad_base64

logger = logging.getLogger(__name__)


class GmailAttachmentHandler:
    """Download attachments from Gmail messages."""

    def __init__(self, get_service_callback: Any) -> None:
        self._get_service = get_service_callback

    async def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        filename_hint: str = "",
    ) -> EmailAttachment:
        """Download an attachment's raw bytes from Gmail.

        Args:
            message_id: The Gmail message that contains the attachment.
            attachment_id: The Gmail attachment ID.
            filename_hint: Original filename from message metadata.

        Returns:
            EmailAttachment with content populated.

        Raises:
            RuntimeError: If the download fails.
        """

        def _download() -> Any:
            service = self._get_service()
            return (
                service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
                .execute()
            )

        try:
            result = await asyncio.to_thread(_download)
        except Exception as exc:
            raise RuntimeError(
                _format_api_error(f"download attachment {attachment_id}", exc)
            ) from exc

        raw_data = result.get("data", "")
        content = base64.urlsafe_b64decode(_pad_base64(raw_data))
        size = result.get("size", len(content))

        return EmailAttachment(
            filename=filename_hint,
            mime_type="application/octet-stream",
            size_bytes=size,
            attachment_id=attachment_id,
            content=content,
        )
