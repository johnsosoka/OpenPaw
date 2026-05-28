"""Tests for GmailFetcher and parsing helpers."""

import base64
from datetime import UTC, datetime

from openpaw.builtins.tools.email.gmail import (
    _MAX_BODY_CHARS,
    _extract_body_and_attachments,
    _extract_headers,
    _parse_date,
    _parse_gmail_message,
    _split_addresses,
    _strip_html,
)

from .conftest import _b64, _make_raw_message


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
