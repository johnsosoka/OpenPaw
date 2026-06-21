"""Tests for GmailComposer and _build_mime_message."""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from openpaw.builtins.tools.email.gmail import _build_mime_message


class TestBuildMimeMessage:
    """Tests for _build_mime_message()."""

    def test_simple_message_is_mime_text(self) -> None:
        msg = _build_mime_message(
            sender="a@b.com",
            to=["c@d.com"],
            subject="Hello",
            body="Body text.",
            cc=None,
            bcc=None,
            reply_to_message_id=None,
            attachments=None,
        )
        assert isinstance(msg, MIMEText)

    def test_message_with_attachments_is_multipart(self) -> None:
        atts = [("file.txt", b"content", "text/plain")]
        msg = _build_mime_message(
            sender="a@b.com",
            to=["c@d.com"],
            subject="Hello",
            body="Body.",
            cc=None,
            bcc=None,
            reply_to_message_id=None,
            attachments=atts,
        )
        assert isinstance(msg, MIMEMultipart)

    def test_from_header_set(self) -> None:
        msg = _build_mime_message(
            sender="sender@example.com",
            to=["r@example.com"],
            subject="S",
            body="B",
            cc=None,
            bcc=None,
            reply_to_message_id=None,
            attachments=None,
        )
        assert msg["From"] == "sender@example.com"

    def test_to_header_multiple_recipients_joined(self) -> None:
        msg = _build_mime_message(
            sender="s@example.com",
            to=["a@example.com", "b@example.com"],
            subject="S",
            body="B",
            cc=None,
            bcc=None,
            reply_to_message_id=None,
            attachments=None,
        )
        assert "a@example.com" in msg["To"]
        assert "b@example.com" in msg["To"]

    def test_cc_header_set_when_provided(self) -> None:
        msg = _build_mime_message(
            sender="s@example.com",
            to=["r@example.com"],
            subject="S",
            body="B",
            cc=["cc@example.com"],
            bcc=None,
            reply_to_message_id=None,
            attachments=None,
        )
        assert msg["Cc"] == "cc@example.com"

    def test_bcc_header_set_when_provided(self) -> None:
        msg = _build_mime_message(
            sender="s@example.com",
            to=["r@example.com"],
            subject="S",
            body="B",
            cc=None,
            bcc=["bcc@example.com"],
            reply_to_message_id=None,
            attachments=None,
        )
        assert msg["Bcc"] == "bcc@example.com"

    def test_no_cc_header_when_none(self) -> None:
        msg = _build_mime_message(
            sender="s@example.com",
            to=["r@example.com"],
            subject="S",
            body="B",
            cc=None,
            bcc=None,
            reply_to_message_id=None,
            attachments=None,
        )
        assert msg["Cc"] is None

    def test_reply_sets_in_reply_to_header(self) -> None:
        msg = _build_mime_message(
            sender="s@example.com",
            to=["r@example.com"],
            subject="Re: Orig",
            body="Reply body.",
            cc=None,
            bcc=None,
            reply_to_message_id="abc123@mail.example.com",
            attachments=None,
        )
        assert "<abc123@mail.example.com>" in msg["In-Reply-To"]

    def test_reply_sets_references_header(self) -> None:
        msg = _build_mime_message(
            sender="s@example.com",
            to=["r@example.com"],
            subject="Re: Orig",
            body="Reply body.",
            cc=None,
            bcc=None,
            reply_to_message_id="abc123@mail.example.com",
            attachments=None,
        )
        assert "<abc123@mail.example.com>" in msg["References"]

    def test_reply_strips_angle_brackets_from_message_id(self) -> None:
        """If caller already includes angle brackets, they should not be doubled."""
        msg = _build_mime_message(
            sender="s@example.com",
            to=["r@example.com"],
            subject="Re: S",
            body="B",
            cc=None,
            bcc=None,
            reply_to_message_id="<already-bracketed@example.com>",
            attachments=None,
        )
        # Should appear exactly once with one pair of brackets.
        in_reply_to = msg["In-Reply-To"]
        assert in_reply_to.count("<") == 1
        assert in_reply_to.count(">") == 1

    def test_attachment_added_to_multipart(self) -> None:
        content = b"Hello attachment"
        atts = [("hello.txt", content, "text/plain")]
        msg = _build_mime_message(
            sender="s@example.com",
            to=["r@example.com"],
            subject="With attachment",
            body="See attached.",
            cc=None,
            bcc=None,
            reply_to_message_id=None,
            attachments=atts,
        )
        assert isinstance(msg, MIMEMultipart)
        # There should be at least two parts: body + attachment.
        assert len(msg.get_payload()) >= 2

    def test_attachment_with_unknown_mime_type_uses_application(self) -> None:
        """MIME type without subtype (malformed) should fall back to MIMEApplication."""
        atts = [("weirdfile.xyz", b"data", "application/octet-stream")]
        msg = _build_mime_message(
            sender="s@example.com",
            to=["r@example.com"],
            subject="S",
            body="B",
            cc=None,
            bcc=None,
            reply_to_message_id=None,
            attachments=atts,
        )
        assert isinstance(msg, MIMEMultipart)
