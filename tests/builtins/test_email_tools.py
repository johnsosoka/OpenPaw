"""Tests for the EmailToolBuiltin tool layer.

All EmailProvider calls are replaced with a MockEmailProvider to isolate
the tool logic from transport-level concerns.
"""

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


# ---------------------------------------------------------------------------
# TestEmailToolBuiltinConstruction
# ---------------------------------------------------------------------------


class TestEmailToolBuiltinConstruction:
    """Tests for EmailToolBuiltin.__init__() config handling."""

    def test_provider_is_none_without_service_account_file(self) -> None:
        builtin = EmailToolBuiltin(config={})
        assert builtin._provider is None

    def test_provider_is_none_without_delegated_user(self) -> None:
        builtin = EmailToolBuiltin(config={"service_account_file": "/fake/sa.json"})
        assert builtin._provider is None

    def test_provider_is_none_for_unsupported_provider_name(self) -> None:
        builtin = EmailToolBuiltin(
            config={
                "provider": "smtp",
                "service_account_file": "/fake/sa.json",
                "delegated_user": "agent@example.com",
            }
        )
        assert builtin._provider is None

    def test_workspace_root_set_from_config(self, tmp_path: Path) -> None:
        builtin = EmailToolBuiltin(config={"workspace_path": str(tmp_path)})
        assert builtin._workspace_root == tmp_path

    def test_workspace_root_none_when_absent(self) -> None:
        builtin = EmailToolBuiltin(config={})
        assert builtin._workspace_root is None

    def test_policy_configured_from_allowed_recipients(self) -> None:
        builtin = EmailToolBuiltin(
            config={"allowed_recipients": ["*@mycompany.com"], "max_recipients": 5}
        )
        assert builtin._policy.allowed_patterns == ["*@mycompany.com"]
        assert builtin._policy.max_recipients == 5

    def test_get_langchain_tool_returns_eight_tools(self) -> None:
        builtin = EmailToolBuiltin(config={})
        tools = builtin.get_langchain_tool()
        assert len(tools) == 8

    def test_tool_names(self) -> None:
        builtin = EmailToolBuiltin(config={})
        names = {t.name for t in builtin.get_langchain_tool()}
        expected = {
            "send_email",
            "check_email",
            "get_email",
            "search_email",
            "reply_email",
            "download_attachment",
            "mark_as_read",
            "mark_as_unread",
        }
        assert names == expected


# ---------------------------------------------------------------------------
# TestAllToolsWhenProviderIsNone
# ---------------------------------------------------------------------------


class TestAllToolsWhenProviderIsNone:
    """All 8 tools must return the _PROVIDER_NOT_CONFIGURED error string
    when no provider has been successfully initialized."""

    @pytest.fixture
    def no_provider_builtin(self) -> EmailToolBuiltin:
        builtin = EmailToolBuiltin(config={})
        assert builtin._provider is None
        return builtin

    @pytest.mark.asyncio
    async def test_send_email_no_provider(self, no_provider_builtin: EmailToolBuiltin) -> None:
        tool = _get_tool(no_provider_builtin, "send_email")
        result = await tool.ainvoke(
            {"to": ["r@example.com"], "subject": "Hi", "body": "Hello."}
        )
        assert "[Error:" in result
        assert "not configured" in result.lower() or "email provider" in result.lower()

    @pytest.mark.asyncio
    async def test_check_email_no_provider(self, no_provider_builtin: EmailToolBuiltin) -> None:
        tool = _get_tool(no_provider_builtin, "check_email")
        result = await tool.ainvoke({})
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_get_email_no_provider(self, no_provider_builtin: EmailToolBuiltin) -> None:
        tool = _get_tool(no_provider_builtin, "get_email")
        result = await tool.ainvoke({"message_id": "msg001"})
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_search_email_no_provider(
        self, no_provider_builtin: EmailToolBuiltin
    ) -> None:
        tool = _get_tool(no_provider_builtin, "search_email")
        result = await tool.ainvoke({"query": "from:alice"})
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_reply_email_no_provider(
        self, no_provider_builtin: EmailToolBuiltin
    ) -> None:
        tool = _get_tool(no_provider_builtin, "reply_email")
        result = await tool.ainvoke({"message_id": "msg001", "body": "My reply."})
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_download_attachment_no_provider(
        self, no_provider_builtin: EmailToolBuiltin
    ) -> None:
        tool = _get_tool(no_provider_builtin, "download_attachment")
        result = await tool.ainvoke(
            {"message_id": "msg001", "attachment_id": "att_001", "filename": "file.pdf"}
        )
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_mark_as_read_no_provider(
        self, no_provider_builtin: EmailToolBuiltin
    ) -> None:
        tool = _get_tool(no_provider_builtin, "mark_as_read")
        result = await tool.ainvoke({"message_id": "msg001"})
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_mark_as_unread_no_provider(
        self, no_provider_builtin: EmailToolBuiltin
    ) -> None:
        tool = _get_tool(no_provider_builtin, "mark_as_unread")
        result = await tool.ainvoke({"message_id": "msg001"})
        assert "[Error:" in result


# ---------------------------------------------------------------------------
# TestResolveAttachments
# ---------------------------------------------------------------------------


class TestResolveAttachments:
    """Tests for EmailToolBuiltin._resolve_attachments()."""

    def test_empty_paths_returns_empty_list_and_no_error(self, tmp_path: Path) -> None:
        builtin = _make_builtin(workspace_path=tmp_path)
        attachments, error = builtin._resolve_attachments([])
        assert attachments == []
        assert error is None

    def test_valid_file_resolved_correctly(self, tmp_path: Path) -> None:
        sample = tmp_path / "doc.txt"
        sample.write_text("content")
        builtin = _make_builtin(workspace_path=tmp_path)
        attachments, error = builtin._resolve_attachments(["doc.txt"])
        assert error is None
        assert len(attachments) == 1
        name, content, mime_type = attachments[0]
        assert name == "doc.txt"
        assert content == b"content"
        assert "text" in mime_type

    def test_nonexistent_file_returns_error(self, tmp_path: Path) -> None:
        builtin = _make_builtin(workspace_path=tmp_path)
        _, error = builtin._resolve_attachments(["missing.pdf"])
        assert error is not None
        assert "[Error:" in error
        assert "missing.pdf" in error

    def test_path_outside_sandbox_returns_error(self, tmp_path: Path) -> None:
        builtin = _make_builtin(workspace_path=tmp_path)
        _, error = builtin._resolve_attachments(["../etc/passwd"])
        assert error is not None
        assert "[Error:" in error

    def test_absolute_path_rejected_by_sandbox(self, tmp_path: Path) -> None:
        builtin = _make_builtin(workspace_path=tmp_path)
        _, error = builtin._resolve_attachments(["/etc/passwd"])
        assert error is not None
        assert "[Error:" in error

    def test_no_workspace_path_returns_error(self) -> None:
        builtin = _make_builtin()  # no workspace_path
        _, error = builtin._resolve_attachments(["somefile.txt"])
        assert error is not None
        assert "[Error:" in error

    def test_directory_path_returns_error(self, tmp_path: Path) -> None:
        subdir = tmp_path / "mydir"
        subdir.mkdir()
        builtin = _make_builtin(workspace_path=tmp_path)
        _, error = builtin._resolve_attachments(["mydir"])
        assert error is not None
        assert "[Error:" in error

    def test_multiple_valid_files_all_resolved(self, tmp_path: Path) -> None:
        for name in ["a.txt", "b.txt", "c.txt"]:
            (tmp_path / name).write_text(f"content of {name}")
        builtin = _make_builtin(workspace_path=tmp_path)
        attachments, error = builtin._resolve_attachments(["a.txt", "b.txt", "c.txt"])
        assert error is None
        assert len(attachments) == 3

    def test_first_invalid_file_stops_processing(self, tmp_path: Path) -> None:
        (tmp_path / "good.txt").write_text("good")
        builtin = _make_builtin(workspace_path=tmp_path)
        _, error = builtin._resolve_attachments(["good.txt", "missing.pdf"])
        assert error is not None
        assert "missing.pdf" in error

    def test_mime_type_defaults_to_octet_stream_for_unknown_extension(
        self, tmp_path: Path
    ) -> None:
        unknown = tmp_path / "data.xyzzy"
        unknown.write_bytes(b"\x00\x01\x02")
        builtin = _make_builtin(workspace_path=tmp_path)
        attachments, error = builtin._resolve_attachments(["data.xyzzy"])
        assert error is None
        _, _, mime_type = attachments[0]
        assert mime_type == "application/octet-stream"


# ---------------------------------------------------------------------------
# TestSendEmail
# ---------------------------------------------------------------------------


class TestSendEmail:
    """Tests for the send_email tool."""

    @pytest.mark.asyncio
    async def test_successful_send_returns_message_id(self, tmp_path: Path) -> None:
        mock_provider = MockEmailProvider()
        builtin = _make_builtin(workspace_path=tmp_path, provider=mock_provider)
        tool = _get_tool(builtin, "send_email")

        result = await tool.ainvoke(
            {"to": ["alice@example.com"], "subject": "Hello", "body": "Body text."}
        )

        assert "mock_sent_id" in result
        assert len(mock_provider.sent_messages) == 1

    @pytest.mark.asyncio
    async def test_recipient_policy_violation_blocked(self, tmp_path: Path) -> None:
        mock_provider = MockEmailProvider()
        builtin = _make_builtin(
            workspace_path=tmp_path,
            allowed_recipients=["*@company.com"],
            provider=mock_provider,
        )
        tool = _get_tool(builtin, "send_email")

        result = await tool.ainvoke(
            {
                "to": ["outsider@gmail.com"],
                "subject": "Blocked",
                "body": "Should not send.",
            }
        )

        assert "[Error:" in result
        assert "policy" in result.lower() or "allowlist" in result.lower()
        assert len(mock_provider.sent_messages) == 0

    @pytest.mark.asyncio
    async def test_cc_recipients_checked_against_policy(self, tmp_path: Path) -> None:
        mock_provider = MockEmailProvider()
        builtin = _make_builtin(
            workspace_path=tmp_path,
            allowed_recipients=["*@company.com"],
            provider=mock_provider,
        )
        tool = _get_tool(builtin, "send_email")

        result = await tool.ainvoke(
            {
                "to": ["alice@company.com"],
                "subject": "Test",
                "body": "Body.",
                "cc": ["outsider@gmail.com"],
            }
        )

        assert "[Error:" in result
        assert len(mock_provider.sent_messages) == 0

    @pytest.mark.asyncio
    async def test_provider_exception_returns_error_string(self, tmp_path: Path) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.send_exception = RuntimeError("SMTP connection refused")
        builtin = _make_builtin(workspace_path=tmp_path, provider=mock_provider)
        tool = _get_tool(builtin, "send_email")

        result = await tool.ainvoke(
            {"to": ["alice@example.com"], "subject": "Hi", "body": "Body."}
        )

        assert "[Error:" in result
        assert "SMTP connection refused" in result

    @pytest.mark.asyncio
    async def test_attachment_included_in_send(self, tmp_path: Path) -> None:
        (tmp_path / "doc.txt").write_text("document content")
        mock_provider = MockEmailProvider()
        builtin = _make_builtin(workspace_path=tmp_path, provider=mock_provider)
        tool = _get_tool(builtin, "send_email")

        result = await tool.ainvoke(
            {
                "to": ["alice@example.com"],
                "subject": "With attachment",
                "body": "See attached.",
                "attachment_paths": ["doc.txt"],
            }
        )

        assert "1 attachment" in result

    @pytest.mark.asyncio
    async def test_invalid_attachment_path_returns_error(self, tmp_path: Path) -> None:
        mock_provider = MockEmailProvider()
        builtin = _make_builtin(workspace_path=tmp_path, provider=mock_provider)
        tool = _get_tool(builtin, "send_email")

        result = await tool.ainvoke(
            {
                "to": ["alice@example.com"],
                "subject": "Hi",
                "body": "Body.",
                "attachment_paths": ["nonexistent.pdf"],
            }
        )

        assert "[Error:" in result
        assert len(mock_provider.sent_messages) == 0


# ---------------------------------------------------------------------------
# TestCheckEmail
# ---------------------------------------------------------------------------


class TestCheckEmail:
    """Tests for the check_email tool."""

    @pytest.mark.asyncio
    async def test_returns_formatted_summaries(self) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.list_result = [
            _make_email_message(msg_id="m1", subject="First Email"),
            _make_email_message(msg_id="m2", subject="Second Email"),
        ]
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "check_email")

        result = await tool.ainvoke({"max_results": 10})

        assert "First Email" in result
        assert "Second Email" in result
        assert "2 message" in result

    @pytest.mark.asyncio
    async def test_no_messages_returns_informative_string(self) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.list_result = []
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "check_email")

        result = await tool.ainvoke({})

        assert "No messages" in result

    @pytest.mark.asyncio
    async def test_provider_exception_returns_error_string(self) -> None:
        mock_provider = MockEmailProvider()

        async def fail_list(*args, **kwargs):
            raise RuntimeError("Service unavailable")

        mock_provider.list_messages = fail_list  # type: ignore[method-assign]
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "check_email")

        result = await tool.ainvoke({})

        assert "[Error:" in result


# ---------------------------------------------------------------------------
# TestGetEmail
# ---------------------------------------------------------------------------


class TestGetEmail:
    """Tests for the get_email tool."""

    @pytest.mark.asyncio
    async def test_returns_full_format(self) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.get_result = _make_email_message(
            msg_id="msg_full", body="This is the full body."
        )
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "get_email")

        result = await tool.ainvoke({"message_id": "msg_full"})

        assert "msg_full" in result
        assert "This is the full body." in result
        assert "---" in result

    @pytest.mark.asyncio
    async def test_provider_exception_returns_error_string(self) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.get_exception = RuntimeError("Message not found")
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "get_email")

        result = await tool.ainvoke({"message_id": "ghost_id"})

        assert "[Error:" in result
        assert "ghost_id" in result


# ---------------------------------------------------------------------------
# TestSearchEmail
# ---------------------------------------------------------------------------


class TestSearchEmail:
    """Tests for the search_email tool."""

    @pytest.mark.asyncio
    async def test_returns_matching_summaries(self) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.search_result = [
            _make_email_message(subject="Invoice #123"),
        ]
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "search_email")

        result = await tool.ainvoke({"query": "subject:invoice"})

        assert "Invoice #123" in result
        assert "1 result" in result

    @pytest.mark.asyncio
    async def test_no_results_returns_informative_string(self) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.search_result = []
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "search_email")

        result = await tool.ainvoke({"query": "from:nobody@nowhere.com"})

        assert "No messages" in result

    @pytest.mark.asyncio
    async def test_query_included_in_no_results_message(self) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.search_result = []
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "search_email")

        result = await tool.ainvoke({"query": "is:unread"})

        assert "is:unread" in result


# ---------------------------------------------------------------------------
# TestReplyEmail
# ---------------------------------------------------------------------------


class TestReplyEmail:
    """Tests for the reply_email tool."""

    @pytest.mark.asyncio
    async def test_successful_reply_sends_to_original_sender(self) -> None:
        mock_provider = MockEmailProvider()
        original = _make_email_message(
            msg_id="orig_001",
            thread_id="thr_001",
            sender="alice@example.com",
        )
        mock_provider.get_result = original

        builtin = _make_builtin(
            allowed_recipients=["*@example.com"], provider=mock_provider
        )
        tool = _get_tool(builtin, "reply_email")

        result = await tool.ainvoke({"message_id": "orig_001", "body": "My reply."})

        assert "[Error:" not in result
        assert "alice@example.com" in result
        assert len(mock_provider.sent_messages) == 1

    @pytest.mark.asyncio
    async def test_reply_uses_re_prefix_for_subject(self) -> None:
        mock_provider = MockEmailProvider()
        original = _make_email_message(
            subject="Original Subject",
            sender="alice@example.com",
        )
        mock_provider.get_result = original

        builtin = _make_builtin(
            allowed_recipients=["*@example.com"], provider=mock_provider
        )
        tool = _get_tool(builtin, "reply_email")

        await tool.ainvoke({"message_id": "orig_001", "body": "Reply."})

        sent = mock_provider.sent_messages[0]
        assert sent["subject"] == "Re: Original Subject"

    @pytest.mark.asyncio
    async def test_reply_includes_threading_headers(self) -> None:
        mock_provider = MockEmailProvider()
        original = _make_email_message(
            msg_id="orig_001",
            thread_id="thr_001",
            sender="alice@example.com",
        )
        mock_provider.get_result = original

        builtin = _make_builtin(
            allowed_recipients=["*@example.com"], provider=mock_provider
        )
        tool = _get_tool(builtin, "reply_email")

        await tool.ainvoke({"message_id": "orig_001", "body": "Replying."})

        sent = mock_provider.sent_messages[0]
        assert sent["reply_to_message_id"] == "orig_001"
        assert sent["thread_id"] == "thr_001"

    @pytest.mark.asyncio
    async def test_reply_blocked_when_sender_not_in_policy(self) -> None:
        mock_provider = MockEmailProvider()
        original = _make_email_message(
            sender="external@gmail.com",
        )
        mock_provider.get_result = original

        builtin = _make_builtin(
            allowed_recipients=["*@company.com"], provider=mock_provider
        )
        tool = _get_tool(builtin, "reply_email")

        result = await tool.ainvoke({"message_id": "msg001", "body": "Reply."})

        assert "[Error:" in result
        assert "external@gmail.com" in result
        assert len(mock_provider.sent_messages) == 0

    @pytest.mark.asyncio
    async def test_reply_fetch_failure_returns_error(self) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.get_exception = RuntimeError("Message not found")

        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "reply_email")

        result = await tool.ainvoke({"message_id": "ghost_msg", "body": "Reply."})

        assert "[Error:" in result
        assert "ghost_msg" in result

    @pytest.mark.asyncio
    async def test_reply_with_attachment(self, tmp_path: Path) -> None:
        (tmp_path / "attachment.txt").write_text("attached data")
        mock_provider = MockEmailProvider()
        original = _make_email_message(sender="alice@example.com")
        mock_provider.get_result = original

        builtin = _make_builtin(
            workspace_path=tmp_path,
            allowed_recipients=["*@example.com"],
            provider=mock_provider,
        )
        tool = _get_tool(builtin, "reply_email")

        result = await tool.ainvoke(
            {
                "message_id": "msg001",
                "body": "Reply with attachment.",
                "attachment_paths": ["attachment.txt"],
            }
        )

        assert "1 attachment" in result


# ---------------------------------------------------------------------------
# TestDownloadAttachment
# ---------------------------------------------------------------------------


class TestDownloadAttachment:
    """Tests for the download_attachment tool."""

    @pytest.mark.asyncio
    async def test_saves_to_downloads_email_directory(self, tmp_path: Path) -> None:
        content = b"PDF binary content"
        mock_provider = MockEmailProvider()
        mock_provider.download_result = EmailAttachment(
            filename="invoice.pdf",
            mime_type="application/pdf",
            size_bytes=len(content),
            attachment_id="att_001",
            content=content,
        )
        builtin = _make_builtin(workspace_path=tmp_path, provider=mock_provider)
        tool = _get_tool(builtin, "download_attachment")

        result = await tool.ainvoke(
            {"message_id": "msg001", "attachment_id": "att_001", "filename": "invoice.pdf"}
        )

        assert "[Error:" not in result
        saved_path = tmp_path / "downloads" / "email" / "invoice.pdf"
        assert saved_path.exists()
        assert saved_path.read_bytes() == content

    @pytest.mark.asyncio
    async def test_workspace_relative_path_returned(self, tmp_path: Path) -> None:
        content = b"content"
        mock_provider = MockEmailProvider()
        mock_provider.download_result = EmailAttachment(
            filename="report.pdf",
            mime_type="application/pdf",
            size_bytes=len(content),
            content=content,
        )
        builtin = _make_builtin(workspace_path=tmp_path, provider=mock_provider)
        tool = _get_tool(builtin, "download_attachment")

        result = await tool.ainvoke(
            {"message_id": "msg001", "attachment_id": "att_001", "filename": "report.pdf"}
        )

        assert "downloads/email" in result
        assert "report.pdf" in result

    @pytest.mark.asyncio
    async def test_save_as_overrides_filename(self, tmp_path: Path) -> None:
        content = b"data"
        mock_provider = MockEmailProvider()
        mock_provider.download_result = EmailAttachment(
            filename="original_name.pdf",
            mime_type="application/pdf",
            size_bytes=len(content),
            content=content,
        )
        builtin = _make_builtin(workspace_path=tmp_path, provider=mock_provider)
        tool = _get_tool(builtin, "download_attachment")

        result = await tool.ainvoke(
            {
                "message_id": "msg001",
                "attachment_id": "att_001",
                "filename": "original_name.pdf",
                "save_as": "custom_name.pdf",
            }
        )

        assert "custom_name.pdf" in result
        assert not (tmp_path / "downloads" / "email" / "original_name.pdf").exists()
        saved = tmp_path / "downloads" / "email" / "custom_name.pdf"
        assert saved.exists()

    @pytest.mark.asyncio
    async def test_no_workspace_path_returns_error(self) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.download_result = EmailAttachment(
            filename="file.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            content=b"data",
        )
        builtin = _make_builtin(provider=mock_provider)  # no workspace_path
        tool = _get_tool(builtin, "download_attachment")

        result = await tool.ainvoke(
            {"message_id": "msg001", "attachment_id": "att_001", "filename": "file.pdf"}
        )

        assert "[Error:" in result
        assert "workspace" in result.lower()

    @pytest.mark.asyncio
    async def test_provider_exception_returns_error_string(
        self, tmp_path: Path
    ) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.download_exception = RuntimeError("Attachment unavailable")
        builtin = _make_builtin(workspace_path=tmp_path, provider=mock_provider)
        tool = _get_tool(builtin, "download_attachment")

        result = await tool.ainvoke(
            {"message_id": "msg001", "attachment_id": "att_bad", "filename": "file.pdf"}
        )

        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_null_content_returns_error(self, tmp_path: Path) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.download_result = EmailAttachment(
            filename="empty.pdf",
            mime_type="application/pdf",
            size_bytes=0,
            content=None,  # Provider returned no content
        )
        builtin = _make_builtin(workspace_path=tmp_path, provider=mock_provider)
        tool = _get_tool(builtin, "download_attachment")

        result = await tool.ainvoke(
            {"message_id": "msg001", "attachment_id": "att_empty", "filename": "empty.pdf"}
        )

        assert "[Error:" in result
        assert "no content" in result.lower()

    @pytest.mark.asyncio
    async def test_duplicate_filename_deduplicated(self, tmp_path: Path) -> None:
        """If a file already exists, a deduplicated name should be used."""
        content = b"data"
        # Pre-create the target file so deduplication kicks in.
        save_dir = tmp_path / "downloads" / "email"
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / "report.pdf").write_bytes(b"original")

        mock_provider = MockEmailProvider()
        mock_provider.download_result = EmailAttachment(
            filename="report.pdf",
            mime_type="application/pdf",
            size_bytes=len(content),
            content=content,
        )
        builtin = _make_builtin(workspace_path=tmp_path, provider=mock_provider)
        tool = _get_tool(builtin, "download_attachment")

        result = await tool.ainvoke(
            {"message_id": "msg001", "attachment_id": "att_001", "filename": "report.pdf"}
        )

        # The deduplicated file should exist alongside the original.
        assert "[Error:" not in result
        files = list(save_dir.iterdir())
        assert len(files) == 2

    @pytest.mark.asyncio
    async def test_size_reported_in_kb(self, tmp_path: Path) -> None:
        content = b"x" * 2048  # 2 KB
        mock_provider = MockEmailProvider()
        mock_provider.download_result = EmailAttachment(
            filename="data.bin",
            mime_type="application/octet-stream",
            size_bytes=len(content),
            content=content,
        )
        builtin = _make_builtin(workspace_path=tmp_path, provider=mock_provider)
        tool = _get_tool(builtin, "download_attachment")

        result = await tool.ainvoke(
            {"message_id": "msg001", "attachment_id": "att_001", "filename": "data.bin"}
        )

        assert "2.0 KB" in result


# ---------------------------------------------------------------------------
# TestMarkAsRead / TestMarkAsUnread
# ---------------------------------------------------------------------------


class TestMarkAsRead:
    """Tests for the mark_as_read tool."""

    @pytest.mark.asyncio
    async def test_successful_mark_returns_confirmation(self) -> None:
        mock_provider = MockEmailProvider()
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "mark_as_read")

        result = await tool.ainvoke({"message_id": "msg_001"})

        assert "msg_001" in result
        assert "read" in result.lower()

    @pytest.mark.asyncio
    async def test_provider_exception_returns_error(self) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.mark_read_exception = RuntimeError("API error")
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "mark_as_read")

        result = await tool.ainvoke({"message_id": "msg_001"})

        assert "[Error:" in result


class TestMarkAsUnread:
    """Tests for the mark_as_unread tool."""

    @pytest.mark.asyncio
    async def test_successful_mark_returns_confirmation(self) -> None:
        mock_provider = MockEmailProvider()
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "mark_as_unread")

        result = await tool.ainvoke({"message_id": "msg_002"})

        assert "msg_002" in result
        assert "unread" in result.lower()

    @pytest.mark.asyncio
    async def test_provider_exception_returns_error(self) -> None:
        mock_provider = MockEmailProvider()
        mock_provider.mark_unread_exception = RuntimeError("Forbidden")
        builtin = _make_builtin(provider=mock_provider)
        tool = _get_tool(builtin, "mark_as_unread")

        result = await tool.ainvoke({"message_id": "msg_002"})

        assert "[Error:" in result
