"""Gmail label management — mark as read/unread."""

import asyncio
import logging
from typing import Any

from openpaw.builtins.tools.email.gmail.base import _format_api_error

logger = logging.getLogger(__name__)


class GmailLabelManager:
    """Modify Gmail message labels."""

    def __init__(self, get_service_callback: Any) -> None:
        self._get_service = get_service_callback

    async def mark_as_read(self, message_id: str) -> None:
        """Remove the UNREAD label from a message.

        Args:
            message_id: The Gmail message ID to mark as read.

        Raises:
            RuntimeError: If the API call fails.
        """

        def _modify() -> None:
            service = self._get_service()
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()

        try:
            await asyncio.to_thread(_modify)
            logger.debug(f"Marked message {message_id} as read")
        except Exception as exc:
            raise RuntimeError(
                _format_api_error(f"mark message {message_id} as read", exc)
            ) from exc

    async def mark_as_unread(self, message_id: str) -> None:
        """Add the UNREAD label to a message.

        Args:
            message_id: The Gmail message ID to mark as unread.

        Raises:
            RuntimeError: If the API call fails.
        """

        def _modify() -> None:
            service = self._get_service()
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": ["UNREAD"]},
            ).execute()

        try:
            await asyncio.to_thread(_modify)
            logger.debug(f"Marked message {message_id} as unread")
        except Exception as exc:
            raise RuntimeError(
                _format_api_error(f"mark message {message_id} as unread", exc)
            ) from exc
