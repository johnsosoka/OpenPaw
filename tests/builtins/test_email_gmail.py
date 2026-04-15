"""Tests for the Gmail provider — pure parsing helpers and the GmailProvider class.

All Google API calls are mocked. Pure helper functions are tested by importing
them directly from the gmail module so there is no I/O.
"""

import base64
import sys
import types
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out google.oauth2 / googleapiclient before importing the provider,
# since those packages may not be installed in the test environment.
# ---------------------------------------------------------------------------


def _build_google_stubs() -> None:
    """Register minimal google.* stubs in sys.modules if not already present."""
    if "google" in sys.modules:
        return

    google = types.ModuleType("google")
    oauth2 = types.ModuleType("google.oauth2")
    sa = types.ModuleType("google.oauth2.service_account")

    class _Credentials:
        @classmethod
        def from_service_account_file(cls, path: str, **kwargs: object) -> "_Credentials":
            return cls()

    sa.Credentials = _Credentials  # type: ignore[attr-defined]
    oauth2.service_account = sa  # type: ignore[attr-defined]
    google.oauth2 = oauth2  # type: ignore[attr-defined]

    googleapiclient = types.ModuleType("googleapiclient")
    discovery = types.ModuleType("googleapiclient.discovery")
    discovery.build = MagicMock()  # type: ignore[attr-defined]
    googleapiclient.discovery = discovery  # type: ignore[attr-defined]

    errors_mod = types.ModuleType("googleapiclient.errors")

    class HttpError(Exception):
        def __init__(self, resp: object, content: bytes) -> None:
            self.resp = resp
            self.content = content

    errors_mod.HttpError = HttpError  # type: ignore[attr-defined]
    googleapiclient.errors = errors_mod  # type: ignore[attr-defined]

    sys.modules["google"] = google
    sys.modules["google.oauth2"] = oauth2
    sys.modules["google.oauth2.service_account"] = sa
    sys.modules["googleapiclient"] = googleapiclient
    sys.modules["googleapiclient.discovery"] = discovery
    sys.modules["googleapiclient.errors"] = errors_mod


_build_google_stubs()

# Now safe to import the module under test.
from openpaw.builtins.tools.email.gmail import (  # noqa: E402
    GmailProvider,
    _build_mime_message,
    _extract_body_and_attachments,
    _extract_headers,
    _format_api_error,
    _pad_base64,
    _parse_date,
    _parse_gmail_message,
    _split_addresses,
    _strip_html,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _b64(text: str) -> str:
    """Base64url-encode a string (no padding), as Gmail API does."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8").rstrip("=")


def _make_raw_message(
    *,
    msg_id: str = "msg001",
    thread_id: str = "thread001",
    snippet: str = "This is a snippet.",
    labels: list[str] | None = None,
    headers: list[dict] | None = None,
    payload: dict | None = None,
) -> dict:
    """Build a minimal raw Gmail API message dict."""
    default_headers = [
        {"name": "From", "value": "alice@example.com"},
        {"name": "To", "value": "bob@example.com"},
        {"name": "Subject", "value": "Test Subject"},
        {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
    ]
    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": snippet,
        "labelIds": labels or ["INBOX"],
        "payload": payload or {"headers": headers or default_headers, "mimeType": "text/plain"},
    }


@pytest.fixture
def provider() -> GmailProvider:
    """Return a GmailProvider with mocked Google API service."""
    with patch("google.oauth2.service_account.Credentials.from_service_account_file"):
        with patch("googleapiclient.discovery.build"):
            prov = GmailProvider(
                service_account_file="/fake/sa.json",
                delegated_user="agent@example.com",
            )
    # Inject a mock service so _get_service() returns without hitting disk/network.
    prov._service = MagicMock()
    return prov


# ---------------------------------------------------------------------------
# _extract_headers
# ---------------------------------------------------------------------------


class TestExtractHeaders:
    """Tests for _extract_headers()."""

    def test_empty_list_returns_empty_dict(self) -> None:
        assert _extract_headers([]) == {}

    def test_single_header_lowercased(self) -> None:
        result = _extract_headers([{"name": "From", "value": "alice@example.com"}])
        assert result == {"from": "alice@example.com"}

    def test_multiple_headers(self) -> None:
        headers = [
            {"name": "From", "value": "alice@example.com"},
            {"name": "To", "value": "bob@example.com"},
            {"name": "Subject", "value": "Hi"},
        ]
        result = _extract_headers(headers)
        assert result["from"] == "alice@example.com"
        assert result["to"] == "bob@example.com"
        assert result["subject"] == "Hi"

    def test_duplicate_header_last_value_wins(self) -> None:
        headers = [
            {"name": "X-Header", "value": "first"},
            {"name": "X-Header", "value": "second"},
        ]
        result = _extract_headers(headers)
        assert result["x-header"] == "second"

    def test_empty_name_entry_is_skipped(self) -> None:
        headers = [
            {"name": "", "value": "should-be-skipped"},
            {"name": "Subject", "value": "Real"},
        ]
        result = _extract_headers(headers)
        assert "" not in result
        assert result["subject"] == "Real"

    def test_mixed_case_header_names_normalized(self) -> None:
        headers = [{"name": "Content-TYPE", "value": "text/plain"}]
        assert _extract_headers(headers)["content-type"] == "text/plain"


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


class TestParseDate:
    """Tests for _parse_date()."""

    def test_valid_rfc2822_date(self) -> None:
        dt = _parse_date("Mon, 15 Jan 2024 10:30:00 +0000")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 10
        assert dt.tzinfo is not None

    def test_empty_string_returns_epoch(self) -> None:
        dt = _parse_date("")
        assert dt == datetime.fromtimestamp(0, tz=UTC)

    def test_invalid_string_returns_epoch(self) -> None:
        dt = _parse_date("not-a-date-at-all")
        assert dt == datetime.fromtimestamp(0, tz=UTC)

    def test_result_is_timezone_aware(self) -> None:
        dt = _parse_date("Fri, 01 Mar 2024 09:00:00 -0500")
        assert dt.tzinfo is not None

    def test_date_with_timezone_offset(self) -> None:
        dt = _parse_date("Mon, 15 Jan 2024 10:30:00 +0500")
        # Should parse successfully (tz-aware)
        assert dt.year == 2024

    def test_none_like_whitespace_returns_epoch(self) -> None:
        dt = _parse_date("   ")
        # " " is truthy so parsedate_to_datetime will be attempted and fail
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# _split_addresses
# ---------------------------------------------------------------------------


class TestSplitAddresses:
    """Tests for _split_addresses()."""

    def test_empty_string_returns_empty_list(self) -> None:
        assert _split_addresses("") == []

    def test_whitespace_only_returns_empty_list(self) -> None:
        assert _split_addresses("   ") == []

    def test_single_address(self) -> None:
        assert _split_addresses("alice@example.com") == ["alice@example.com"]

    def test_multiple_comma_separated(self) -> None:
        result = _split_addresses("alice@example.com, bob@example.com")
        assert result == ["alice@example.com", "bob@example.com"]

    def test_strips_whitespace_around_each_address(self) -> None:
        result = _split_addresses("  alice@example.com  ,  bob@example.com  ")
        assert result == ["alice@example.com", "bob@example.com"]

    def test_display_name_format_preserved(self) -> None:
        result = _split_addresses("Alice <alice@example.com>, Bob <bob@example.com>")
        assert len(result) == 2
        assert "Alice <alice@example.com>" in result

    def test_empty_segments_filtered_out(self) -> None:
        # Double commas produce empty segments.
        result = _split_addresses("alice@example.com,,bob@example.com")
        assert "" not in result
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _pad_base64
# ---------------------------------------------------------------------------


class TestPadBase64:
    """Tests for _pad_base64()."""

    def test_no_padding_needed_when_divisible_by_four(self) -> None:
        data = "ABCD"
        assert _pad_base64(data) == "ABCD"

    def test_adds_one_pad_char(self) -> None:
        data = "ABC"  # length 3 → needs 1 padding
        padded = _pad_base64(data)
        assert padded == "ABC="

    def test_adds_two_pad_chars(self) -> None:
        data = "AB"  # length 2 → needs 2 padding
        padded = _pad_base64(data)
        assert padded == "AB=="

    def test_adds_three_pad_chars(self) -> None:
        data = "A"  # length 1 → needs 3 padding
        padded = _pad_base64(data)
        assert padded == "A==="

    def test_padded_string_is_decodable(self) -> None:
        original = "Hello, World!"
        encoded = base64.urlsafe_b64encode(original.encode()).decode().rstrip("=")
        decoded = base64.urlsafe_b64decode(_pad_base64(encoded)).decode()
        assert decoded == original


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------


class TestStripHtml:
    """Tests for _strip_html()."""

    def test_plain_text_unchanged(self) -> None:
        result = _strip_html("No tags here")
        assert "No tags here" in result

    def test_removes_simple_tags(self) -> None:
        result = _strip_html("<p>Hello <b>World</b></p>")
        assert "<p>" not in result
        assert "<b>" not in result
        assert "Hello" in result
        assert "World" in result

    def test_removes_html_and_body_tags(self) -> None:
        html = "<html><body><p>Content</p></body></html>"
        result = _strip_html(html)
        assert "<html>" not in result
        assert "Content" in result

    def test_empty_string(self) -> None:
        assert _strip_html("") == ""

    def test_tags_only_returns_whitespace(self) -> None:
        result = _strip_html("<br/><hr/>")
        assert "<br" not in result

    def test_preserves_text_content_from_nested_tags(self) -> None:
        html = "<div><span><em>Nested</em></span></div>"
        assert "Nested" in _strip_html(html)


# ---------------------------------------------------------------------------
# _format_api_error
# ---------------------------------------------------------------------------


class TestFormatApiError:
    """Tests for _format_api_error()."""

    def _exc_with_status(self, code: int) -> Exception:
        """Create a minimal exception with a status_code attribute."""
        exc = Exception("API error")
        exc.status_code = code  # type: ignore[attr-defined]
        return exc

    def test_401_authentication_error(self) -> None:
        result = _format_api_error("send email", self._exc_with_status(401))
        assert "authentication" in result.lower() or "credentials" in result.lower()
        assert "[Error:" in result

    def test_403_access_denied_error(self) -> None:
        result = _format_api_error("list messages", self._exc_with_status(403))
        assert "access denied" in result.lower() or "delegation" in result.lower()
        assert "[Error:" in result

    def test_404_not_found_error(self) -> None:
        result = _format_api_error("get message", self._exc_with_status(404))
        assert "not found" in result.lower()
        assert "[Error:" in result

    def test_429_rate_limit_error(self) -> None:
        result = _format_api_error("search", self._exc_with_status(429))
        assert "rate limit" in result.lower()
        assert "[Error:" in result

    def test_500_server_error(self) -> None:
        result = _format_api_error("send", self._exc_with_status(500))
        assert "server error" in result.lower() or "500" in result
        assert "[Error:" in result

    def test_503_server_error(self) -> None:
        result = _format_api_error("list", self._exc_with_status(503))
        assert "[Error:" in result
        assert "503" in result

    def test_unknown_error_includes_exception_message(self) -> None:
        exc = Exception("Something unusual happened")
        result = _format_api_error("do something", exc)
        assert "[Error:" in result

    def test_no_status_code_falls_through_to_generic(self) -> None:
        exc = ValueError("No status here")
        result = _format_api_error("act", exc)
        assert "[Error:" in result

    def test_resp_dict_status_code_extracted(self) -> None:
        """HttpError style: .resp object with 'status' attribute."""
        exc = Exception("HttpError")
        resp = MagicMock()
        resp.status = "401"
        exc.resp = resp  # type: ignore[attr-defined]
        result = _format_api_error("fetch", exc)
        assert "[Error:" in result
        assert "authentication" in result.lower() or "credentials" in result.lower()


# ---------------------------------------------------------------------------
# _extract_body_and_attachments
# ---------------------------------------------------------------------------


class TestExtractBodyAndAttachments:
    """Tests for _extract_body_and_attachments() via the payload walker."""

    def test_simple_text_plain_message(self) -> None:
        text = "Hello from plain text."
        payload = {
            "mimeType": "text/plain",
            "body": {"data": _b64(text)},
            "headers": [],
        }
        body, attachments = _extract_body_and_attachments(payload)
        assert text in body
        assert attachments == []

    def test_html_only_message_strips_tags(self) -> None:
        html = "<p>Hello from <b>HTML</b>.</p>"
        payload = {
            "mimeType": "text/html",
            "body": {"data": _b64(html)},
            "headers": [],
        }
        body, attachments = _extract_body_and_attachments(payload)
        assert "<p>" not in body
        assert "Hello" in body
        assert "HTML" in body
        assert attachments == []

    def test_multipart_plain_and_html_prefers_plain(self) -> None:
        plain_text = "Plain text version."
        html_text = "<p>HTML version.</p>"
        payload = {
            "mimeType": "multipart/alternative",
            "body": {},
            "headers": [],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64(plain_text)}, "headers": []},
                {"mimeType": "text/html", "body": {"data": _b64(html_text)}, "headers": []},
            ],
        }
        body, _ = _extract_body_and_attachments(payload)
        assert plain_text in body
        # HTML version should not bleed through
        assert "<p>" not in body

    def test_attachment_extracted_with_metadata(self) -> None:
        payload = {
            "mimeType": "multipart/mixed",
            "body": {},
            "headers": [],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64("Body text.")},
                    "headers": [],
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "invoice.pdf",
                    "body": {"attachmentId": "att_001", "size": 2048},
                    "headers": [],
                },
            ],
        }
        body, attachments = _extract_body_and_attachments(payload)
        assert "Body text." in body
        assert len(attachments) == 1
        assert attachments[0].filename == "invoice.pdf"
        assert attachments[0].attachment_id == "att_001"
        assert attachments[0].size_bytes == 2048
        assert attachments[0].mime_type == "application/pdf"
        assert attachments[0].content is None

    def test_inline_image_skipped(self) -> None:
        """Inline images (with Content-ID and inline disposition) should not appear as attachments."""
        payload = {
            "mimeType": "multipart/related",
            "body": {},
            "headers": [],
            "parts": [
                {
                    "mimeType": "image/png",
                    "filename": "logo.png",
                    "body": {"attachmentId": "att_img", "size": 512},
                    "headers": [
                        {"name": "Content-Disposition", "value": "inline"},
                        {"name": "Content-ID", "value": "<logo@example.com>"},
                    ],
                },
            ],
        }
        _, attachments = _extract_body_and_attachments(payload)
        assert attachments == []

    def test_multiple_attachments(self) -> None:
        payload = {
            "mimeType": "multipart/mixed",
            "body": {},
            "headers": [],
            "parts": [
                {
                    "mimeType": "application/pdf",
                    "filename": "file1.pdf",
                    "body": {"attachmentId": "att_1", "size": 1000},
                    "headers": [],
                },
                {
                    "mimeType": "application/zip",
                    "filename": "file2.zip",
                    "body": {"attachmentId": "att_2", "size": 2000},
                    "headers": [],
                },
            ],
        }
        _, attachments = _extract_body_and_attachments(payload)
        assert len(attachments) == 2
        filenames = {a.filename for a in attachments}
        assert "file1.pdf" in filenames
        assert "file2.zip" in filenames

    def test_empty_payload_returns_empty_body_and_no_attachments(self) -> None:
        body, attachments = _extract_body_and_attachments({})
        assert body == ""
        assert attachments == []

    def test_nested_multipart_traversal(self) -> None:
        """Plain text buried inside nested multipart parts should still be found."""
        inner_text = "Deep nested plain text."
        payload = {
            "mimeType": "multipart/mixed",
            "body": {},
            "headers": [],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "body": {},
                    "headers": [],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": _b64(inner_text)},
                            "headers": [],
                        }
                    ],
                }
            ],
        }
        body, _ = _extract_body_and_attachments(payload)
        assert inner_text in body


# ---------------------------------------------------------------------------
# _parse_gmail_message
# ---------------------------------------------------------------------------


class TestParseGmailMessage:
    """Tests for _parse_gmail_message()."""

    def test_basic_message_fields_populated(self) -> None:
        raw = _make_raw_message(msg_id="xyz", thread_id="thr")
        msg = _parse_gmail_message(raw, include_body=False)
        assert msg.id == "xyz"
        assert msg.thread_id == "thr"

    def test_subject_from_headers(self) -> None:
        raw = _make_raw_message(
            headers=[
                {"name": "From", "value": "a@b.com"},
                {"name": "To", "value": "c@d.com"},
                {"name": "Subject", "value": "My Subject"},
                {"name": "Date", "value": "Mon, 15 Jan 2024 10:00:00 +0000"},
            ]
        )
        msg = _parse_gmail_message(raw, include_body=False)
        assert msg.subject == "My Subject"

    def test_missing_subject_defaults_to_no_subject(self) -> None:
        raw = _make_raw_message(
            headers=[
                {"name": "From", "value": "a@b.com"},
                {"name": "To", "value": "c@d.com"},
                {"name": "Date", "value": "Mon, 15 Jan 2024 10:00:00 +0000"},
            ]
        )
        msg = _parse_gmail_message(raw, include_body=False)
        assert msg.subject == "(no subject)"

    def test_snippet_extracted(self) -> None:
        raw = _make_raw_message(snippet="Quick preview here.")
        msg = _parse_gmail_message(raw, include_body=False)
        assert msg.snippet == "Quick preview here."

    def test_labels_extracted(self) -> None:
        raw = _make_raw_message(labels=["INBOX", "UNREAD", "IMPORTANT"])
        msg = _parse_gmail_message(raw, include_body=False)
        assert "INBOX" in msg.labels
        assert "UNREAD" in msg.labels

    def test_body_empty_when_include_body_false(self) -> None:
        raw = _make_raw_message()
        msg = _parse_gmail_message(raw, include_body=False)
        assert msg.body == ""

    def test_body_populated_when_include_body_true(self) -> None:
        body_text = "This is the full body."
        payload = {
            "headers": [
                {"name": "From", "value": "a@b.com"},
                {"name": "To", "value": "c@d.com"},
                {"name": "Date", "value": "Mon, 15 Jan 2024 10:00:00 +0000"},
                {"name": "Subject", "value": "Subj"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64(body_text)},
        }
        raw = _make_raw_message(payload=payload)
        msg = _parse_gmail_message(raw, include_body=True)
        assert body_text in msg.body

    def test_recipients_parsed_from_to_header(self) -> None:
        raw = _make_raw_message(
            headers=[
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "r1@example.com, r2@example.com"},
                {"name": "Date", "value": "Mon, 15 Jan 2024 10:00:00 +0000"},
            ]
        )
        msg = _parse_gmail_message(raw, include_body=False)
        assert "r1@example.com" in msg.recipients
        assert "r2@example.com" in msg.recipients

    def test_cc_parsed_from_cc_header(self) -> None:
        raw = _make_raw_message(
            headers=[
                {"name": "From", "value": "a@b.com"},
                {"name": "To", "value": "c@d.com"},
                {"name": "Cc", "value": "cc1@example.com, cc2@example.com"},
                {"name": "Date", "value": "Mon, 15 Jan 2024 10:00:00 +0000"},
            ]
        )
        msg = _parse_gmail_message(raw, include_body=False)
        assert "cc1@example.com" in msg.cc
        assert "cc2@example.com" in msg.cc

    def test_attachments_not_populated_when_include_body_false(self) -> None:
        raw = _make_raw_message()
        msg = _parse_gmail_message(raw, include_body=False)
        assert msg.attachments == []

    def test_body_truncated_at_max_chars(self) -> None:
        """Body should be capped at _MAX_BODY_CHARS characters."""
        from openpaw.builtins.tools.email.gmail import _MAX_BODY_CHARS

        long_body = "x" * (_MAX_BODY_CHARS + 1000)
        payload = {
            "headers": [
                {"name": "From", "value": "a@b.com"},
                {"name": "To", "value": "c@d.com"},
                {"name": "Date", "value": "Mon, 15 Jan 2024 10:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64(long_body)},
        }
        raw = _make_raw_message(payload=payload)
        msg = _parse_gmail_message(raw, include_body=True)
        assert len(msg.body) == _MAX_BODY_CHARS


# ---------------------------------------------------------------------------
# _build_mime_message
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# GmailProvider — integration-style with mocked service
# ---------------------------------------------------------------------------


class TestGmailProviderSend:
    """Tests for GmailProvider.send() with a mocked Gmail service."""

    @pytest.mark.asyncio
    async def test_successful_send_returns_message_id(self, provider: GmailProvider) -> None:
        provider._service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "sent_msg_001"
        }
        result = await provider.send(
            to=["recipient@example.com"],
            subject="Test",
            body="Hello.",
        )
        assert result == "sent_msg_001"

    @pytest.mark.asyncio
    async def test_api_error_returns_error_string(self, provider: GmailProvider) -> None:
        exc = Exception("API failure")
        exc.status_code = 500  # type: ignore[attr-defined]
        provider._service.users.return_value.messages.return_value.send.return_value.execute.side_effect = exc

        with pytest.raises(RuntimeError):
            await provider.send(
                to=["recipient@example.com"],
                subject="Test",
                body="Hello.",
            )

    @pytest.mark.asyncio
    async def test_send_with_thread_id_included_in_payload(
        self, provider: GmailProvider
    ) -> None:
        execute_mock = MagicMock(return_value={"id": "sent_001"})
        send_mock = MagicMock()
        send_mock.execute = execute_mock

        messages_mock = MagicMock()
        messages_mock.send = MagicMock(return_value=send_mock)
        provider._service.users.return_value.messages.return_value = messages_mock

        await provider.send(
            to=["r@example.com"],
            subject="Re: Thread",
            body="Reply.",
            thread_id="thread_abc",
        )

        call_kwargs = messages_mock.send.call_args[1]
        assert call_kwargs["body"].get("threadId") == "thread_abc"


class TestGmailProviderMarkAsRead:
    """Tests for GmailProvider.mark_as_read()."""

    @pytest.mark.asyncio
    async def test_mark_as_read_calls_modify_with_remove_unread(
        self, provider: GmailProvider
    ) -> None:
        modify_mock = MagicMock()
        modify_mock.execute = MagicMock(return_value={})
        provider._service.users.return_value.messages.return_value.modify.return_value = (
            modify_mock
        )

        await provider.mark_as_read("msg_001")

        provider._service.users.return_value.messages.return_value.modify.assert_called_once()
        call_kwargs = provider._service.users.return_value.messages.return_value.modify.call_args[1]
        assert "UNREAD" in call_kwargs["body"]["removeLabelIds"]

    @pytest.mark.asyncio
    async def test_mark_as_read_raises_on_api_error(self, provider: GmailProvider) -> None:
        provider._service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = Exception(
            "API down"
        )
        with pytest.raises(RuntimeError):
            await provider.mark_as_read("msg_001")


class TestGmailProviderMarkAsUnread:
    """Tests for GmailProvider.mark_as_unread()."""

    @pytest.mark.asyncio
    async def test_mark_as_unread_calls_modify_with_add_unread(
        self, provider: GmailProvider
    ) -> None:
        modify_mock = MagicMock()
        modify_mock.execute = MagicMock(return_value={})
        provider._service.users.return_value.messages.return_value.modify.return_value = (
            modify_mock
        )

        await provider.mark_as_unread("msg_002")

        call_kwargs = provider._service.users.return_value.messages.return_value.modify.call_args[1]
        assert "UNREAD" in call_kwargs["body"]["addLabelIds"]

    @pytest.mark.asyncio
    async def test_mark_as_unread_raises_on_api_error(self, provider: GmailProvider) -> None:
        provider._service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = Exception(
            "Network error"
        )
        with pytest.raises(RuntimeError):
            await provider.mark_as_unread("msg_002")


class TestGmailProviderDownloadAttachment:
    """Tests for GmailProvider.download_attachment()."""

    @pytest.mark.asyncio
    async def test_successful_download_returns_attachment_with_content(
        self, provider: GmailProvider
    ) -> None:
        raw_bytes = b"PDF content here"
        encoded = base64.urlsafe_b64encode(raw_bytes).decode()
        att_chain = provider._service.users.return_value.messages.return_value
        att_chain.attachments.return_value.get.return_value.execute.return_value = {
            "data": encoded,
            "size": len(raw_bytes),
        }

        att = await provider.download_attachment("msg_001", "att_001")

        assert att.content == raw_bytes
        assert att.size_bytes == len(raw_bytes)
        assert att.attachment_id == "att_001"

    @pytest.mark.asyncio
    async def test_download_failure_raises_runtime_error(
        self, provider: GmailProvider
    ) -> None:
        att_chain = provider._service.users.return_value.messages.return_value
        att_chain.attachments.return_value.get.return_value.execute.side_effect = Exception(
            "Download failed"
        )
        with pytest.raises(RuntimeError):
            await provider.download_attachment("msg_001", "att_bad")


class TestGmailProviderGetMessage:
    """Tests for GmailProvider.get_message()."""

    def _make_full_raw(self) -> dict:
        body_text = "Full body content."
        return {
            "id": "msg_full",
            "threadId": "thr_full",
            "snippet": "Full body content.",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "To", "value": "recipient@example.com"},
                    {"name": "Subject", "value": "Full Message"},
                    {"name": "Date", "value": "Tue, 20 Feb 2024 14:00:00 +0000"},
                ],
                "mimeType": "text/plain",
                "body": {"data": _b64(body_text)},
            },
        }

    @pytest.mark.asyncio
    async def test_get_message_returns_email_message(self, provider: GmailProvider) -> None:
        provider._service.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            self._make_full_raw()
        )

        msg = await provider.get_message("msg_full")

        assert msg.id == "msg_full"
        assert msg.subject == "Full Message"
        assert "Full body content." in msg.body

    @pytest.mark.asyncio
    async def test_get_message_raises_on_api_failure(self, provider: GmailProvider) -> None:
        provider._service.users.return_value.messages.return_value.get.return_value.execute.side_effect = Exception(
            "Not found"
        )
        with pytest.raises(RuntimeError):
            await provider.get_message("nonexistent")


class TestGmailProviderListMessages:
    """Tests for GmailProvider.list_messages()."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_messages(self, provider: GmailProvider) -> None:
        provider._service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }

        result = await provider.list_messages()
        assert result == []

    @pytest.mark.asyncio
    async def test_caps_max_results_at_100(self, provider: GmailProvider) -> None:
        list_mock = MagicMock()
        list_mock.execute.return_value = {"messages": []}
        provider._service.users.return_value.messages.return_value.list.return_value = list_mock

        await provider.list_messages(max_results=200)

        call_kwargs = provider._service.users.return_value.messages.return_value.list.call_args[1]
        assert call_kwargs["maxResults"] <= 100

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_api_error(self, provider: GmailProvider) -> None:
        provider._service.users.return_value.messages.return_value.list.return_value.execute.side_effect = Exception(
            "Service unavailable"
        )

        result = await provider.list_messages()
        assert result == []
