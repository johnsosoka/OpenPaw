"""Shared fixtures for email tool tests."""

import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openpaw.builtins.tools.email.base import (
    EmailAttachment,
    EmailMessage,
    EmailProvider,
)

# ---------------------------------------------------------------------------
# Stub out google packages so EmailToolBuiltin can be imported without them.
# ---------------------------------------------------------------------------


def _ensure_google_stubs() -> None:
    if "google" in sys.modules:
        return
    google = types.ModuleType("google")
    oauth2 = types.ModuleType("google.oauth2")
    sa = types.ModuleType("google.oauth2.service_account")
    sa.Credentials = MagicMock()  # type: ignore[attr-defined]
    oauth2.service_account = sa  # type: ignore[attr-defined]
    google.oauth2 = oauth2  # type: ignore[attr-defined]
    googleapiclient = types.ModuleType("googleapiclient")
    discovery = types.ModuleType("googleapiclient.discovery")
    discovery.build = MagicMock()  # type: ignore[attr-defined]
    googleapiclient.discovery = discovery  # type: ignore[attr-defined]
    sys.modules["google"] = google
    sys.modules["google.oauth2"] = oauth2
    sys.modules["google.oauth2.service_account"] = sa
    sys.modules["googleapiclient"] = googleapiclient
    sys.modules["googleapiclient.discovery"] = discovery


_ensure_google_stubs()

from openpaw.builtins.tools.email import EmailToolBuiltin  # noqa: E402

# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


class MockEmailProvider(EmailProvider):
    """In-memory EmailProvider for testing — no I/O, configurable return values."""

    def __init__(self) -> None:
        self.sent_messages: list[dict] = []
        self.send_result: str = "mock_sent_id"
        self.send_exception: Exception | None = None
        self.list_result: list[EmailMessage] = []
        self.get_result: EmailMessage | None = None
        self.get_exception: Exception | None = None
        self.search_result: list[EmailMessage] = []
        self.download_result: EmailAttachment | None = None
        self.download_exception: Exception | None = None
        self.mark_read_exception: Exception | None = None
        self.mark_unread_exception: Exception | None = None

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
        if self.send_exception:
            raise self.send_exception
        self.sent_messages.append(
            {
                "to": to,
                "subject": subject,
                "body": body,
                "cc": cc,
                "bcc": bcc,
                "reply_to_message_id": reply_to_message_id,
                "thread_id": thread_id,
            }
        )
        return self.send_result

    async def list_messages(
        self, max_results: int = 10, label: str = "INBOX"
    ) -> list[EmailMessage]:
        return self.list_result

    async def get_message(self, message_id: str) -> EmailMessage:
        if self.get_exception:
            raise self.get_exception
        if self.get_result:
            return self.get_result
        raise RuntimeError(f"No mock result set for message_id={message_id}")

    async def search(self, query: str, max_results: int = 10) -> list[EmailMessage]:
        return self.search_result

    async def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        filename_hint: str = "",
    ) -> EmailAttachment:
        if self.download_exception:
            raise self.download_exception
        if self.download_result:
            return self.download_result
        raise RuntimeError("No mock download result set")

    async def mark_as_read(self, message_id: str) -> None:
        if self.mark_read_exception:
            raise self.mark_read_exception

    async def mark_as_unread(self, message_id: str) -> None:
        if self.mark_unread_exception:
            raise self.mark_unread_exception


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_email_message(
    *,
    msg_id: str = "msg001",
    thread_id: str = "thread001",
    subject: str = "Test Subject",
    sender: str = "alice@example.com",
    recipients: list[str] | None = None,
    body: str = "Email body.",
    snippet: str = "Email body.",
    cc: list[str] | None = None,
    labels: list[str] | None = None,
    attachments: list[EmailAttachment] | None = None,
) -> EmailMessage:
    return EmailMessage(
        id=msg_id,
        thread_id=thread_id,
        subject=subject,
        sender=sender,
        recipients=recipients or ["bob@example.com"],
        body=body,
        date=datetime(2024, 3, 15, 10, 30, tzinfo=UTC),
        snippet=snippet,
        cc=cc or [],
        labels=labels or ["INBOX"],
        attachments=attachments or [],
    )


def _make_builtin(
    *,
    workspace_path: Path | None = None,
    allowed_recipients: list[str] | None = None,
    max_recipients: int = 10,
    provider: MockEmailProvider | None = None,
) -> EmailToolBuiltin:
    """Construct an EmailToolBuiltin with a mock provider injected directly."""
    config: dict = {
        "allowed_recipients": allowed_recipients or ["*@example.com"],
        "max_recipients": max_recipients,
    }
    if workspace_path:
        config["workspace_path"] = str(workspace_path)
    # Bypass __init__ provider construction by passing no service_account_file.
    builtin = EmailToolBuiltin(config=config)
    if provider is not None:
        builtin._provider = provider
    return builtin


def _get_tool(builtin: EmailToolBuiltin, name: str):
    """Extract a named tool from the builtin by name."""
    tools = {t.name: t for t in builtin.get_langchain_tool()}
    return tools[name]
