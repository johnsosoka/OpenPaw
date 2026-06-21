"""Tests for EmailToolExecutor — all 8 tool execution paths."""

from pathlib import Path

import pytest

from openpaw.builtins.tools.email.base import EmailAttachment

from .conftest import _get_tool, _make_builtin, _make_email_message, MockEmailProvider


class TestSendEmail:
    """Tests for the send_email tool via executor."""

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


class TestNoProvider:
    """All 8 tools must return the provider-not-configured error string."""

    @pytest.mark.asyncio
    async def test_send_email_no_provider(self) -> None:
        builtin = _make_builtin()
        tool = _get_tool(builtin, "send_email")
        result = await tool.ainvoke(
            {"to": ["r@example.com"], "subject": "Hi", "body": "Hello."}
        )
        assert "[Error:" in result
        assert "not configured" in result.lower() or "email provider" in result.lower()

    @pytest.mark.asyncio
    async def test_check_email_no_provider(self) -> None:
        builtin = _make_builtin()
        tool = _get_tool(builtin, "check_email")
        result = await tool.ainvoke({})
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_get_email_no_provider(self) -> None:
        builtin = _make_builtin()
        tool = _get_tool(builtin, "get_email")
        result = await tool.ainvoke({"message_id": "msg001"})
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_search_email_no_provider(self) -> None:
        builtin = _make_builtin()
        tool = _get_tool(builtin, "search_email")
        result = await tool.ainvoke({"query": "from:alice"})
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_reply_email_no_provider(self) -> None:
        builtin = _make_builtin()
        tool = _get_tool(builtin, "reply_email")
        result = await tool.ainvoke({"message_id": "msg001", "body": "My reply."})
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_download_attachment_no_provider(self) -> None:
        builtin = _make_builtin()
        tool = _get_tool(builtin, "download_attachment")
        result = await tool.ainvoke(
            {"message_id": "msg001", "attachment_id": "att_001", "filename": "file.pdf"}
        )
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_mark_as_read_no_provider(self) -> None:
        builtin = _make_builtin()
        tool = _get_tool(builtin, "mark_as_read")
        result = await tool.ainvoke({"message_id": "msg001"})
        assert "[Error:" in result

    @pytest.mark.asyncio
    async def test_mark_as_unread_no_provider(self) -> None:
        builtin = _make_builtin()
        tool = _get_tool(builtin, "mark_as_unread")
        result = await tool.ainvoke({"message_id": "msg001"})
        assert "[Error:" in result
