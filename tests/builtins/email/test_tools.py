"""Tests for EmailToolBuiltin construction and metadata."""

from pathlib import Path

from openpaw.builtins.tools.email import EmailToolBuiltin
from openpaw.builtins.tools.email.models import (
    CheckEmailInput,
    DownloadAttachmentInput,
    GetEmailInput,
    MarkAsReadInput,
    MarkAsUnreadInput,
    ReplyEmailInput,
    SearchEmailInput,
    SendEmailInput,
)

from .conftest import _make_builtin, _make_email_message


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


class TestAllToolsWhenProviderIsNone:
    """All 8 tools must return the provider-not-configured error string
    when no provider has been successfully initialized."""

    def test_send_email_no_provider(self) -> None:
        builtin = EmailToolBuiltin(config={})
        assert builtin._provider is None
        tool = builtin.get_langchain_tool()[0]
        assert tool.name == "send_email"

    def test_check_email_no_provider(self) -> None:
        builtin = EmailToolBuiltin(config={})
        assert builtin._provider is None
        tool = builtin.get_langchain_tool()[1]
        assert tool.name == "check_email"

    def test_get_email_no_provider(self) -> None:
        builtin = EmailToolBuiltin(config={})
        assert builtin._provider is None
        tool = builtin.get_langchain_tool()[2]
        assert tool.name == "get_email"

    def test_search_email_no_provider(self) -> None:
        builtin = EmailToolBuiltin(config={})
        assert builtin._provider is None
        tool = builtin.get_langchain_tool()[3]
        assert tool.name == "search_email"

    def test_reply_email_no_provider(self) -> None:
        builtin = EmailToolBuiltin(config={})
        assert builtin._provider is None
        tool = builtin.get_langchain_tool()[4]
        assert tool.name == "reply_email"

    def test_download_attachment_no_provider(self) -> None:
        builtin = EmailToolBuiltin(config={})
        assert builtin._provider is None
        tool = builtin.get_langchain_tool()[5]
        assert tool.name == "download_attachment"

    def test_mark_as_read_no_provider(self) -> None:
        builtin = EmailToolBuiltin(config={})
        assert builtin._provider is None
        tool = builtin.get_langchain_tool()[6]
        assert tool.name == "mark_as_read"

    def test_mark_as_unread_no_provider(self) -> None:
        builtin = EmailToolBuiltin(config={})
        assert builtin._provider is None
        tool = builtin.get_langchain_tool()[7]
        assert tool.name == "mark_as_unread"


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
