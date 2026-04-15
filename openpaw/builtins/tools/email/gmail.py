"""Gmail provider implementation using Google service account + domain-wide delegation.

All blocking googleapiclient calls are dispatched via asyncio.to_thread() to keep
the event loop free. Errors from the Google API are caught and returned as
user-friendly strings — exceptions never bubble up to callers.
"""

import asyncio
import base64
import logging
import threading
from datetime import UTC, datetime
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from openpaw.builtins.tools.email.base import (
    EmailAttachment,
    EmailMessage,
    EmailProvider,
)

logger = logging.getLogger(__name__)

# Gmail OAuth2 scopes required for read, send, and label modification.
_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Safety valve: cap body text to avoid flooding the agent's context window.
_MAX_BODY_CHARS = 50_000


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
            logger.info(f"Gmail API service initialized for {self._delegated_user}")

        return self._service

    # ------------------------------------------------------------------
    # EmailProvider interface
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
        """Send an email and return the sent message ID.

        Constructs a proper RFC 2822 / MIME message. When replying, sets the
        In-Reply-To and References headers so Gmail threads the message correctly.

        Args:
            to: Primary recipient addresses.
            subject: Email subject line.
            body: Plain text body.
            cc: CC recipient addresses.
            bcc: BCC recipient addresses.
            reply_to_message_id: RFC 2822 Message-ID of the message being replied to.
            thread_id: Gmail thread ID to attach this message to.
            attachments: Sequence of (filename, content_bytes, mime_type) tuples.

        Returns:
            The sent message ID.

        Raises:
            RuntimeError: On MIME construction or API failure.
        """
        mime_message = _build_mime_message(
            sender=self._delegated_user,
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
            logger.info(f"Email sent successfully (message_id={message_id})")
            return message_id
        except Exception as exc:
            raise RuntimeError(_format_api_error("send email", exc)) from exc

    async def list_messages(
        self,
        max_results: int = 10,
        label: str = "INBOX",
    ) -> list[EmailMessage]:
        """List recent messages from the given label/folder.

        Performs two round-trips: one to list message IDs, one batch of individual
        fetches (format=metadata) for headers + snippet.

        Args:
            max_results: Maximum number of messages to return (capped at 100).
            label: Gmail label to list from (e.g., "INBOX", "SENT", "SPAM").

        Returns:
            List of EmailMessage objects with metadata. Body is empty for list results;
            call get_message() for the full body.
        """
        max_results = min(max_results, 100)

        def _list_ids() -> list[str]:
            service = self._get_service()
            resp = (
                service.users()
                .messages()
                .list(userId="me", labelIds=[label], maxResults=max_results)
                .execute()
            )
            return [m["id"] for m in resp.get("messages", [])]

        try:
            message_ids = await asyncio.to_thread(_list_ids)
        except Exception as exc:
            logger.error(f"Failed to list messages: {exc}")
            return []

        if not message_ids:
            return []

        # Fetch metadata for each message concurrently.
        tasks = [self._fetch_message(mid, full=False) for mid in message_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        messages: list[EmailMessage] = []
        for item in results:
            if isinstance(item, EmailMessage):
                messages.append(item)
            else:
                logger.warning(f"Skipping failed message fetch: {item}")

        return messages

    async def get_message(self, message_id: str) -> EmailMessage:
        """Retrieve a single message with full body content.

        Args:
            message_id: The Gmail message ID.

        Returns:
            Full EmailMessage including body text and attachment metadata.

        Raises:
            RuntimeError: If the message cannot be fetched (wraps the underlying error).
        """
        result = await self._fetch_message(message_id, full=True)
        if isinstance(result, Exception):
            raise RuntimeError(f"Failed to retrieve message {message_id}: {result}") from result
        return result

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[EmailMessage]:
        """Search messages using Gmail query syntax.

        Supports the full Gmail search language (e.g., ``from:alice@example.com``,
        ``subject:invoice``, ``has:attachment``, ``after:2024/01/01``).

        Args:
            query: Gmail search query string.
            max_results: Maximum results to return (capped at 100).

        Returns:
            List of matching EmailMessage objects with metadata.
        """
        max_results = min(max_results, 100)

        def _search() -> list[str]:
            service = self._get_service()
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            return [m["id"] for m in resp.get("messages", [])]

        try:
            message_ids = await asyncio.to_thread(_search)
        except Exception as exc:
            logger.error(f"Search failed (query={query!r}): {exc}")
            return []

        if not message_ids:
            return []

        tasks = [self._fetch_message(mid, full=False) for mid in message_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        messages: list[EmailMessage] = []
        for item in results:
            if isinstance(item, EmailMessage):
                messages.append(item)
            else:
                logger.warning(f"Skipping failed message fetch during search: {item}")

        return messages

    async def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        filename_hint: str = "",
    ) -> EmailAttachment:
        """Download an attachment's raw bytes from Gmail.

        Args:
            message_id: The Gmail message that contains the attachment.
            attachment_id: The Gmail attachment ID (from EmailAttachment.attachment_id).
            filename_hint: Original filename from message metadata (the Gmail
                attachments API does not return the filename in the download response).

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_message(
        self, message_id: str, full: bool
    ) -> EmailMessage | Exception:
        """Fetch a single Gmail message and parse it into an EmailMessage.

        Args:
            message_id: The Gmail message ID.
            full: When True, fetches the full payload (body + attachments).
                  When False, fetches only metadata and snippet.

        Returns:
            An EmailMessage on success, or the Exception on failure.
        """
        msg_format = "full" if full else "metadata"

        def _get() -> Any:
            service = self._get_service()
            return (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format=msg_format)
                .execute()
            )

        try:
            raw = await asyncio.to_thread(_get)
        except Exception as exc:
            logger.warning(f"Failed to fetch message {message_id}: {exc}")
            return exc

        try:
            return _parse_gmail_message(raw, include_body=full)
        except Exception as exc:
            logger.warning(f"Failed to parse message {message_id}: {exc}")
            return exc


# ------------------------------------------------------------------
# Pure parsing helpers (no I/O)
# ------------------------------------------------------------------


def _parse_gmail_message(raw: dict[str, Any], include_body: bool) -> EmailMessage:
    """Parse a raw Gmail API message dict into an EmailMessage.

    Args:
        raw: The dict returned by messages.get().
        include_body: Whether to extract and decode the body text.

    Returns:
        Populated EmailMessage.
    """
    headers = _extract_headers(raw.get("payload", {}).get("headers", []))

    date = _parse_date(headers.get("date", ""))
    recipients = _split_addresses(headers.get("to", ""))
    cc = _split_addresses(headers.get("cc", ""))
    labels: list[str] = raw.get("labelIds", [])
    snippet: str = raw.get("snippet", "")

    body = ""
    attachments: list[EmailAttachment] = []

    if include_body:
        payload = raw.get("payload", {})
        body, attachments = _extract_body_and_attachments(payload)
        body = body[:_MAX_BODY_CHARS]

    return EmailMessage(
        id=raw.get("id", ""),
        thread_id=raw.get("threadId", ""),
        subject=headers.get("subject", "(no subject)"),
        sender=headers.get("from", ""),
        recipients=recipients,
        body=body,
        date=date,
        snippet=snippet,
        cc=cc,
        labels=labels,
        attachments=attachments,
    )


def _extract_headers(header_list: list[dict[str, str]]) -> dict[str, str]:
    """Flatten a Gmail headers list into a lowercase-keyed dict.

    When a header appears multiple times, the last value wins.

    Args:
        header_list: List of {"name": ..., "value": ...} dicts from Gmail API.

    Returns:
        Dict mapping lowercase header name → value.
    """
    result: dict[str, str] = {}
    for h in header_list:
        name = h.get("name", "").lower()
        value = h.get("value", "")
        if name:
            result[name] = value
    return result


def _parse_date(date_str: str) -> datetime:
    """Parse a RFC 2822 date string into an aware datetime (UTC fallback).

    Args:
        date_str: Date header value from the Gmail message.

    Returns:
        Timezone-aware datetime. Returns epoch UTC if parsing fails.
    """
    if not date_str:
        return datetime.fromtimestamp(0, tz=UTC)

    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(date_str)
        # Ensure tz-aware; naive dates are treated as UTC.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        logger.debug(f"Could not parse date header: {date_str!r}")
        return datetime.fromtimestamp(0, tz=UTC)


def _split_addresses(header_value: str) -> list[str]:
    """Split a comma-separated address header into individual addresses.

    Args:
        header_value: Raw header value (e.g., "Alice <a@b.com>, Bob <b@c.com>").

    Returns:
        List of address strings. Empty list if the header is blank.
    """
    if not header_value.strip():
        return []
    return [addr.strip() for addr in header_value.split(",") if addr.strip()]


def _extract_body_and_attachments(
    payload: dict[str, Any],
) -> tuple[str, list[EmailAttachment]]:
    """Walk the MIME payload tree and extract plain text body + attachment metadata.

    Gmail stores messages as a recursive tree of parts. This function does a
    depth-first walk, collecting:
    - The first ``text/plain`` part it finds as the body.
    - Any parts with a Content-Disposition of "attachment" as EmailAttachment entries.

    Args:
        payload: The ``payload`` dict from a Gmail message (format=full).

    Returns:
        Tuple of (body_text, list_of_attachments).
    """
    body_parts: list[str] = []
    attachments: list[EmailAttachment] = []

    _walk_payload(payload, body_parts, attachments)

    body = "\n".join(body_parts)
    return body, attachments


def _walk_payload(
    part: dict[str, Any],
    body_parts: list[str],
    attachments: list[EmailAttachment],
) -> None:
    """Recursively walk a Gmail payload part, filling body_parts and attachments.

    Args:
        part: A single MIME part dict from the Gmail API.
        body_parts: Accumulator list for body text segments.
        attachments: Accumulator list for attachment metadata.
    """
    mime_type: str = part.get("mimeType", "")
    filename: str = part.get("filename", "")
    body_data: dict[str, Any] = part.get("body", {})
    sub_parts: list[dict[str, Any]] = part.get("parts", [])

    # Determine Content-Disposition from part headers.
    part_headers = _extract_headers(part.get("headers", []))
    disposition = part_headers.get("content-disposition", "")

    # Attachment: named part or explicitly marked as attachment.
    if filename and body_data.get("attachmentId"):
        attachment_id = body_data["attachmentId"]
        size = body_data.get("size", 0)
        content_id = part_headers.get("content-id", "")
        # Skip inline images with a content-id (embedded in HTML), keep true attachments.
        is_inline_image = "inline" in disposition and content_id
        if not is_inline_image:
            attachments.append(
                EmailAttachment(
                    filename=filename,
                    mime_type=mime_type,
                    size_bytes=size,
                    attachment_id=attachment_id,
                    content=None,
                )
            )
        return  # Do not descend into attachment parts.

    # Plain text body — take the first one found in the tree.
    if mime_type == "text/plain" and not sub_parts:
        raw_data = body_data.get("data", "")
        if raw_data:
            text = base64.urlsafe_b64decode(_pad_base64(raw_data)).decode(
                "utf-8", errors="replace"
            )
            body_parts.append(text)
        return

    # HTML fallback: if we have no plain text yet and this is text/html, convert.
    if mime_type == "text/html" and not sub_parts and not body_parts:
        raw_data = body_data.get("data", "")
        if raw_data:
            html = base64.urlsafe_b64decode(_pad_base64(raw_data)).decode(
                "utf-8", errors="replace"
            )
            body_parts.append(_strip_html(html))
        return

    # Multipart container — recurse into sub-parts.
    for sub_part in sub_parts:
        _walk_payload(sub_part, body_parts, attachments)


def _strip_html(html: str) -> str:
    """Remove HTML tags from a string, leaving readable plain text.

    A lightweight fallback for when no text/plain part is available. Uses the
    stdlib ``email`` + ``html.parser`` to avoid external dependencies.

    Args:
        html: Raw HTML string.

    Returns:
        Plain text with tags stripped. Whitespace is normalized.
    """
    from html.parser import HTMLParser

    class _Stripper(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self._chunks: list[str] = []

        def handle_data(self, data: str) -> None:
            self._chunks.append(data)

        def get_text(self) -> str:
            return " ".join(self._chunks)

    stripper = _Stripper()
    try:
        stripper.feed(html)
        return stripper.get_text()
    except Exception:
        return html  # Return raw HTML as fallback if parsing fails.


def _pad_base64(data: str) -> str:
    """Add missing base64 padding characters.

    Gmail uses base64url without padding. Python's base64.urlsafe_b64decode
    requires correct padding.

    Args:
        data: Potentially unpadded base64url string.

    Returns:
        Properly padded base64url string.
    """
    remainder = len(data) % 4
    if remainder:
        data += "=" * (4 - remainder)
    return data


def _build_mime_message(
    sender: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None,
    bcc: list[str] | None,
    reply_to_message_id: str | None,
    attachments: list[tuple[str, bytes, str]] | None,
) -> MIMEMultipart | MIMEText:
    """Construct a RFC 2822 MIME message ready for base64url encoding.

    Uses MIMEMultipart when attachments are present, otherwise falls back to a
    simple MIMEText to keep the message compact.

    Args:
        sender: From address.
        to: Primary recipient list.
        subject: Subject line.
        body: Plain text body.
        cc: CC recipients.
        bcc: BCC recipients (included in headers; Gmail handles actual delivery).
        reply_to_message_id: RFC 2822 Message-ID for threading.
        attachments: List of (filename, content_bytes, mime_type) tuples.

    Returns:
        Assembled MIME message object.
    """
    if attachments:
        msg: MIMEMultipart | MIMEText = MIMEMultipart()
        msg.attach(MIMEText(body, "plain", "utf-8"))
    else:
        msg = MIMEText(body, "plain", "utf-8")

    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)

    if reply_to_message_id:
        # Strip any surrounding angle brackets before adding them back, to be safe.
        clean_id = reply_to_message_id.strip().strip("<>")
        msg["In-Reply-To"] = f"<{clean_id}>"
        msg["References"] = f"<{clean_id}>"

    if attachments and isinstance(msg, MIMEMultipart):
        for filename, content_bytes, mime_type in attachments:
            main_type, _, sub_type = mime_type.partition("/")
            if main_type and sub_type:
                part: MIMEBase = MIMEBase(main_type, sub_type)
                part.set_payload(content_bytes)
                from email import encoders

                encoders.encode_base64(part)
            else:
                # Fallback for unrecognised or missing MIME types.
                part = MIMEApplication(content_bytes)

            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)

    return msg


def _format_api_error(action: str, exc: Exception) -> str:
    """Return a user-friendly error string for a Gmail API exception.

    Attempts to extract a meaningful message from HttpError responses.
    Falls back to a generic message for unexpected exception types.

    Args:
        action: Short description of what was being attempted (e.g., "send email").
        exc: The caught exception.

    Returns:
        A formatted "[Error: ...]" string safe to return to the agent.
    """
    # googleapiclient.errors.HttpError exposes .status_code (int) directly,
    # or .resp.status on the underlying httplib2 response object.
    status_code: int | None = None
    try:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            resp = getattr(exc, "resp", None)
            if resp is not None:
                status_code = getattr(resp, "status", None)
        if status_code is not None:
            status_code = int(status_code)
    except (ValueError, TypeError):
        pass

    if status_code == 429:
        return "[Error: Gmail API rate limit reached. Please wait a moment and try again.]"
    if status_code == 401:
        return "[Error: Gmail authentication failed. Check the service account credentials.]"
    if status_code == 403:
        return (
            "[Error: Gmail API access denied. "
            "Verify that domain-wide delegation is enabled for this service account "
            "and that the correct scopes have been granted.]"
        )
    if status_code == 404:
        return "[Error: Requested Gmail resource not found. Check the message or attachment ID.]"
    if status_code is not None and status_code >= 500:
        return f"[Error: Gmail API server error ({status_code}). Please try again later.]"

    # Generic fallback — include the exception message but avoid raw tracebacks.
    logger.error(f"Unexpected error during '{action}': {exc}", exc_info=True)
    return f"[Error: Failed to {action}: {exc}]"
