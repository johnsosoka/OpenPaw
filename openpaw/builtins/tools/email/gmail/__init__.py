"""Gmail provider implementation using Google service account + domain-wide delegation.

All blocking googleapiclient calls are dispatched via asyncio.to_thread() to keep
the event loop free. Errors from the Google API are caught and returned as
user-friendly strings — exceptions never bubble up to callers.
"""

import threading
from typing import Any

from openpaw.builtins.tools.email.base import EmailProvider
from openpaw.builtins.tools.email.gmail.attachments import GmailAttachmentHandler
from openpaw.builtins.tools.email.gmail.compose import GmailComposer
from openpaw.builtins.tools.email.gmail.fetch import GmailFetcher
from openpaw.builtins.tools.email.gmail.labels import GmailLabelManager

# Gmail OAuth2 scopes required for read, send, and label modification.
_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailProvider(EmailProvider):
    """Email provider backed by the Gmail API via service account delegation.

    Uses a Google Workspace service account with domain-wide delegation enabled
    so the agent can act on behalf of any user in the organization.

    Args:
        service_account_file: Absolute path to the service account JSON key file.
        delegated_user: The email address of the user to impersonate
            (e.g., "agent@yourdomain.com").
    """

    def __init__(self, service_account_file: str, delegated_user: str) -> None:
        self._service_account_file = service_account_file
        self._delegated_user = delegated_user
        self._service: Any = None
        self._service_lock = threading.Lock()

        # Internal helpers
        self._composer = GmailComposer(delegated_user)
        self._fetcher = GmailFetcher(self._get_service)
        self._label_manager = GmailLabelManager(self._get_service)
        self._attachment_handler = GmailAttachmentHandler(self._get_service)

    # ------------------------------------------------------------------
    # Lazy client initialization
    # ------------------------------------------------------------------

    def _get_service(self) -> Any:
        """Return the Gmail API service, building it on first call.

        Thread-safe via double-checked locking. This is intentionally
        synchronous — it is always called from within asyncio.to_thread().
        """
        if self._service is not None:
            return self._service

        with self._service_lock:
            if self._service is not None:
                return self._service

            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
                self._service_account_file,
                scopes=_SCOPES,
                subject=self._delegated_user,
            )
            self._service = build("gmail", "v1", credentials=credentials)

        return self._service

    # ------------------------------------------------------------------
    # EmailProvider interface — delegates to internal helpers
    # ------------------------------------------------------------------

    async def send(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to_message_id: str | None = None,
        thread_id: str | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
    ) -> str:
        """Send an email and return the sent message ID."""
        import asyncio
        import base64

        from openpaw.builtins.tools.email.gmail.base import _format_api_error

        mime_message = self._composer.build_mime_message(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            reply_to_message_id=reply_to_message_id,
            attachments=attachments,
        )

        raw = base64.urlsafe_b64encode(mime_message.as_bytes()).decode("utf-8")
        payload: dict[str, Any] = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id

        def _do_send() -> Any:
            service = self._get_service()
            return (
                service.users()
                .messages()
                .send(userId="me", body=payload)
                .execute()
            )

        try:
            result = await asyncio.to_thread(_do_send)
            message_id: str = result.get("id", "unknown")
            return message_id
        except Exception as exc:
            raise RuntimeError(_format_api_error("send email", exc)) from exc

    async def list_messages(
        self,
        max_results: int = 10,
        label: str = "INBOX",
    ) -> list[Any]:
        """List recent messages from the given label/folder."""
        return await self._fetcher.list_messages(max_results=max_results, label=label)

    async def get_message(self, message_id: str) -> Any:
        """Retrieve a single message with full body content."""
        return await self._fetcher.get_message(message_id)

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[Any]:
        """Search messages using Gmail query syntax."""
        return await self._fetcher.search(query=query, max_results=max_results)

    async def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        filename_hint: str = "",
    ) -> Any:
        """Download an attachment's raw bytes from Gmail."""
        return await self._attachment_handler.download_attachment(
            message_id=message_id,
            attachment_id=attachment_id,
            filename_hint=filename_hint,
        )

    async def mark_as_read(self, message_id: str) -> None:
        """Remove the UNREAD label from a message."""
        await self._label_manager.mark_as_read(message_id)

    async def mark_as_unread(self, message_id: str) -> None:
        """Add the UNREAD label to a message."""
        await self._label_manager.mark_as_unread(message_id)


# Backwards-compatible standalone function that old tests import directly.
def _build_mime_message(
    sender: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None,
    bcc: list[str] | None,
    reply_to_message_id: str | None,
    attachments: list[tuple[str, bytes, str]] | None,
) -> Any:
    """Construct a RFC 2822 MIME message (backwards-compatible wrapper)."""
    composer = GmailComposer(sender)
    return composer.build_mime_message(
        to=to,
        subject=subject,
        body=body,
        cc=cc,
        bcc=bcc,
        reply_to_message_id=reply_to_message_id,
        attachments=attachments,
    )


# Backwards compatibility: re-export helpers that tests import directly.
from openpaw.builtins.tools.email.gmail.base import _format_api_error, _pad_base64  # noqa: E402
from openpaw.builtins.tools.email.gmail.fetch import (  # noqa: E402
    _MAX_BODY_CHARS,
    _extract_body_and_attachments,
    _extract_headers,
    _parse_date,
    _parse_gmail_message,
    _split_addresses,
    _strip_html,
)

__all__ = [
    "GmailProvider",
    "GmailComposer",
    "_build_mime_message",
    "_format_api_error",
    "_pad_base64",
    "_parse_gmail_message",
    "_extract_headers",
    "_parse_date",
    "_split_addresses",
    "_extract_body_and_attachments",
    "_strip_html",
    "_MAX_BODY_CHARS",
]
