"""Gmail message fetching and parsing."""

import asyncio
import base64
import logging
from datetime import UTC, datetime
from typing import Any

from openpaw.builtins.tools.email.base import EmailAttachment, EmailMessage
from openpaw.builtins.tools.email.gmail.base import _pad_base64

logger = logging.getLogger(__name__)

# Safety valve: cap body text to avoid flooding the agent's context window.
_MAX_BODY_CHARS = 50_000


class GmailFetcher:
    """Fetch and parse Gmail messages via the API."""

    def __init__(self, get_service_callback: Any) -> None:
        self._get_service = get_service_callback

    async def fetch_message(
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

    async def list_messages(
        self,
        max_results: int = 10,
        label: str = "INBOX",
    ) -> list[EmailMessage]:
        """List recent messages from the given label/folder.

        Args:
            max_results: Maximum number of messages to return (capped at 100).
            label: Gmail label to list from.

        Returns:
            List of EmailMessage objects with metadata.
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
        tasks = [self.fetch_message(mid, full=False) for mid in message_ids]
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
            RuntimeError: If the message cannot be fetched.
        """
        result = await self.fetch_message(message_id, full=True)
        if isinstance(result, Exception):
            raise RuntimeError(f"Failed to retrieve message {message_id}: {result}") from result
        return result

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[EmailMessage]:
        """Search messages using Gmail query syntax.

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

        tasks = [self.fetch_message(mid, full=False) for mid in message_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        messages: list[EmailMessage] = []
        for item in results:
            if isinstance(item, EmailMessage):
                messages.append(item)
            else:
                logger.warning(f"Skipping failed message fetch during search: {item}")

        return messages


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
