"""Tests for email base data models and RecipientPolicy.

Covers pure data model behaviour — no I/O, no API calls, no mocking needed.
"""

from datetime import UTC, datetime

import pytest

from openpaw.builtins.tools.email.base import (
    EmailAttachment,
    EmailMessage,
    RecipientPolicy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(
    *,
    msg_id: str = "abc123",
    thread_id: str = "thread_1",
    subject: str = "Hello",
    sender: str = "alice@example.com",
    recipients: list[str] | None = None,
    body: str = "Body text.",
    date: datetime | None = None,
    snippet: str = "Body text.",
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
        date=date or datetime(2024, 3, 15, 10, 30, tzinfo=UTC),
        snippet=snippet,
        cc=cc or [],
        labels=labels or [],
        attachments=attachments or [],
    )


# ---------------------------------------------------------------------------
# EmailAttachment
# ---------------------------------------------------------------------------


class TestEmailAttachment:
    """Tests for the EmailAttachment dataclass."""

    def test_minimal_construction(self) -> None:
        att = EmailAttachment(
            filename="invoice.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
        )
        assert att.filename == "invoice.pdf"
        assert att.mime_type == "application/pdf"
        assert att.size_bytes == 1024
        assert att.attachment_id == ""
        assert att.content is None

    def test_full_construction(self) -> None:
        content = b"PDF content bytes"
        att = EmailAttachment(
            filename="report.pdf",
            mime_type="application/pdf",
            size_bytes=len(content),
            attachment_id="att_abc123",
            content=content,
        )
        assert att.attachment_id == "att_abc123"
        assert att.content == content

    def test_content_defaults_to_none(self) -> None:
        att = EmailAttachment(filename="photo.jpg", mime_type="image/jpeg", size_bytes=50000)
        assert att.content is None

    def test_zero_size_is_valid(self) -> None:
        att = EmailAttachment(filename="empty.txt", mime_type="text/plain", size_bytes=0)
        assert att.size_bytes == 0


# ---------------------------------------------------------------------------
# EmailMessage.format_summary
# ---------------------------------------------------------------------------


class TestEmailMessageFormatSummary:
    """Tests for EmailMessage.format_summary()."""

    def test_includes_message_id(self) -> None:
        msg = _make_message(msg_id="msg_xyz")
        assert "msg_xyz" in msg.format_summary()

    def test_includes_date_formatted_as_year_month_day(self) -> None:
        msg = _make_message(date=datetime(2024, 7, 4, 9, 0, tzinfo=UTC))
        assert "2024-07-04" in msg.format_summary()

    def test_includes_sender(self) -> None:
        msg = _make_message(sender="carol@example.com")
        assert "carol@example.com" in msg.format_summary()

    def test_includes_single_recipient(self) -> None:
        msg = _make_message(recipients=["dan@example.com"])
        assert "dan@example.com" in msg.format_summary()

    def test_includes_multiple_recipients_comma_separated(self) -> None:
        msg = _make_message(recipients=["dan@example.com", "eve@example.com"])
        summary = msg.format_summary()
        assert "dan@example.com" in summary
        assert "eve@example.com" in summary

    def test_includes_subject(self) -> None:
        msg = _make_message(subject="Q4 Report")
        assert "Q4 Report" in msg.format_summary()

    def test_includes_snippet(self) -> None:
        msg = _make_message(snippet="Please review the attached...")
        assert "Please review the attached..." in msg.format_summary()

    def test_no_attachment_note_when_empty(self) -> None:
        msg = _make_message(attachments=[])
        assert "attachment" not in msg.format_summary()

    def test_attachment_count_shown_when_present(self) -> None:
        atts = [
            EmailAttachment(filename=f"file{i}.pdf", mime_type="application/pdf", size_bytes=100)
            for i in range(3)
        ]
        msg = _make_message(attachments=atts)
        summary = msg.format_summary()
        assert "3 attachment" in summary

    def test_cc_shown_when_present(self) -> None:
        msg = _make_message(cc=["manager@example.com"])
        assert "manager@example.com" in msg.format_summary()

    def test_no_cc_section_when_empty(self) -> None:
        msg = _make_message(cc=[])
        assert "CC:" not in msg.format_summary()

    def test_single_attachment_uses_correct_plural(self) -> None:
        att = EmailAttachment(filename="single.pdf", mime_type="application/pdf", size_bytes=500)
        msg = _make_message(attachments=[att])
        assert "1 attachment" in msg.format_summary()


# ---------------------------------------------------------------------------
# EmailMessage.format_full
# ---------------------------------------------------------------------------


class TestEmailMessageFormatFull:
    """Tests for EmailMessage.format_full()."""

    def test_includes_message_id(self) -> None:
        msg = _make_message(msg_id="full_msg_001")
        assert "full_msg_001" in msg.format_full()

    def test_includes_thread_id(self) -> None:
        msg = _make_message(thread_id="thread_99")
        assert "thread_99" in msg.format_full()

    def test_includes_date_with_seconds(self) -> None:
        msg = _make_message(date=datetime(2024, 12, 25, 8, 30, 45, tzinfo=UTC))
        full = msg.format_full()
        assert "2024-12-25" in full
        assert "08:30:45" in full

    def test_includes_subject(self) -> None:
        msg = _make_message(subject="Important Notice")
        assert "Important Notice" in msg.format_full()

    def test_includes_body(self) -> None:
        msg = _make_message(body="This is the full body content.")
        assert "This is the full body content." in msg.format_full()

    def test_includes_separator_before_body(self) -> None:
        msg = _make_message()
        assert "---" in msg.format_full()

    def test_attachment_section_when_present(self) -> None:
        att = EmailAttachment(
            filename="report.pdf",
            mime_type="application/pdf",
            size_bytes=2048,
            attachment_id="att_001",
        )
        msg = _make_message(attachments=[att])
        full = msg.format_full()
        assert "Attachments:" in full
        assert "report.pdf" in full
        assert "att_001" in full

    def test_attachment_size_formatted_in_kb(self) -> None:
        att = EmailAttachment(
            filename="big.zip",
            mime_type="application/zip",
            size_bytes=51200,  # 50 KB
        )
        msg = _make_message(attachments=[att])
        assert "50.0 KB" in msg.format_full()

    def test_no_attachments_section_when_empty(self) -> None:
        msg = _make_message(attachments=[])
        assert "Attachments:" not in msg.format_full()

    def test_cc_section_when_present(self) -> None:
        msg = _make_message(cc=["cc1@example.com", "cc2@example.com"])
        full = msg.format_full()
        assert "CC:" in full
        assert "cc1@example.com" in full

    def test_no_cc_section_when_empty(self) -> None:
        msg = _make_message(cc=[])
        assert "CC:" not in msg.format_full()

    def test_labels_section_when_present(self) -> None:
        msg = _make_message(labels=["INBOX", "UNREAD"])
        full = msg.format_full()
        assert "Labels:" in full
        assert "INBOX" in full

    def test_no_labels_section_when_empty(self) -> None:
        msg = _make_message(labels=[])
        assert "Labels:" not in msg.format_full()

    def test_multiple_attachments_all_listed(self) -> None:
        atts = [
            EmailAttachment(
                filename=f"file{i}.txt",
                mime_type="text/plain",
                size_bytes=100 * (i + 1),
                attachment_id=f"att_{i}",
            )
            for i in range(3)
        ]
        msg = _make_message(attachments=atts)
        full = msg.format_full()
        for i in range(3):
            assert f"file{i}.txt" in full
            assert f"att_{i}" in full


# ---------------------------------------------------------------------------
# RecipientPolicy.validate — empty allowlist
# ---------------------------------------------------------------------------


class TestRecipientPolicyEmptyAllowlist:
    """An empty allowed_patterns list must block ALL outbound sends."""

    def test_blocks_any_single_recipient(self) -> None:
        policy = RecipientPolicy(allowed_patterns=[])
        error = policy.validate(["anyone@anywhere.com"])
        assert error is not None
        assert "disabled" in error.lower() or "allowed_recipients" in error.lower()

    def test_blocks_multiple_recipients(self) -> None:
        policy = RecipientPolicy(allowed_patterns=[])
        error = policy.validate(["a@a.com", "b@b.com"])
        assert error is not None

    def test_error_mentions_configuration(self) -> None:
        policy = RecipientPolicy(allowed_patterns=[])
        error = policy.validate(["x@y.com"])
        assert "allowed_recipients" in error


# ---------------------------------------------------------------------------
# RecipientPolicy.validate — no recipients
# ---------------------------------------------------------------------------


class TestRecipientPolicyNoRecipients:
    """Sending to an empty list must return an error."""

    def test_empty_list_returns_error(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@example.com"])
        error = policy.validate([])
        assert error is not None
        assert "no recipients" in error.lower()


# ---------------------------------------------------------------------------
# RecipientPolicy.validate — max recipients
# ---------------------------------------------------------------------------


class TestRecipientPolicyMaxRecipients:
    """Exceeding max_recipients must return an informative error."""

    def test_exactly_at_limit_is_allowed(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@example.com"], max_recipients=3)
        error = policy.validate(["a@example.com", "b@example.com", "c@example.com"])
        assert error is None

    def test_one_over_limit_is_blocked(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@example.com"], max_recipients=2)
        error = policy.validate(["a@example.com", "b@example.com", "c@example.com"])
        assert error is not None
        assert "3" in error
        assert "2" in error

    def test_error_mentions_maximum(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@example.com"], max_recipients=5)
        recipients = [f"user{i}@example.com" for i in range(6)]
        error = policy.validate(recipients)
        assert "Maximum" in error or "maximum" in error


# ---------------------------------------------------------------------------
# RecipientPolicy.validate — wildcard patterns
# ---------------------------------------------------------------------------


class TestRecipientPolicyWildcard:
    """Wildcard glob patterns must match correctly."""

    def test_domain_wildcard_matches_any_user(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@company.com"])
        assert policy.validate(["alice@company.com"]) is None
        assert policy.validate(["bob@company.com"]) is None

    def test_domain_wildcard_rejects_other_domain(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@company.com"])
        error = policy.validate(["alice@other.com"])
        assert error is not None

    def test_full_wildcard_allows_anything(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*"])
        assert policy.validate(["anyone@anywhere.net"]) is None

    def test_subdomain_pattern_matches_subdomain(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@*.company.com"])
        assert policy.validate(["dev@mail.company.com"]) is None

    def test_subdomain_pattern_does_not_match_root_domain(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@*.company.com"])
        error = policy.validate(["dev@company.com"])
        assert error is not None

    def test_multiple_patterns_any_match_passes(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@company.com", "*@partner.org"])
        assert policy.validate(["alice@company.com"]) is None
        assert policy.validate(["bob@partner.org"]) is None

    def test_multiple_patterns_no_match_blocked(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@company.com", "*@partner.org"])
        error = policy.validate(["outsider@gmail.com"])
        assert error is not None


# ---------------------------------------------------------------------------
# RecipientPolicy.validate — specific addresses
# ---------------------------------------------------------------------------


class TestRecipientPolicySpecificAddresses:
    """Exact email address patterns must only match that address."""

    def test_exact_match_passes(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["alice@example.com"])
        assert policy.validate(["alice@example.com"]) is None

    def test_different_user_blocked(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["alice@example.com"])
        error = policy.validate(["bob@example.com"])
        assert error is not None

    def test_multiple_specific_addresses(self) -> None:
        policy = RecipientPolicy(
            allowed_patterns=["alice@example.com", "bob@example.com"]
        )
        assert policy.validate(["alice@example.com"]) is None
        assert policy.validate(["bob@example.com"]) is None
        assert policy.validate(["charlie@example.com"]) is not None


# ---------------------------------------------------------------------------
# RecipientPolicy.validate — case insensitivity
# ---------------------------------------------------------------------------


class TestRecipientPolicyCaseInsensitivity:
    """Matching must be case-insensitive on both pattern and address."""

    def test_uppercase_address_matches_lowercase_pattern(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["alice@example.com"])
        assert policy.validate(["ALICE@EXAMPLE.COM"]) is None

    def test_mixed_case_address_matches(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["alice@example.com"])
        assert policy.validate(["Alice@Example.Com"]) is None

    def test_uppercase_pattern_stored_lowercase(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["ALICE@EXAMPLE.COM"])
        assert policy.validate(["alice@example.com"]) is None

    def test_wildcard_pattern_case_insensitive(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@COMPANY.COM"])
        assert policy.validate(["user@company.com"]) is None


# ---------------------------------------------------------------------------
# RecipientPolicy.validate — mixed allowed/blocked in a batch
# ---------------------------------------------------------------------------


class TestRecipientPolicyMixedBatch:
    """When a batch has a mix of allowed and blocked, the whole batch is rejected."""

    def test_one_blocked_in_batch_rejects_all(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@example.com"])
        error = policy.validate(["alice@example.com", "outsider@gmail.com"])
        assert error is not None

    def test_error_names_the_blocked_address(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@example.com"])
        error = policy.validate(["alice@example.com", "outsider@gmail.com"])
        assert "outsider@gmail.com" in error

    def test_all_allowed_passes_with_no_error(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@example.com"])
        error = policy.validate(["alice@example.com", "bob@example.com"])
        assert error is None

    def test_multiple_blocked_addresses_all_named(self) -> None:
        policy = RecipientPolicy(allowed_patterns=["*@company.com"])
        error = policy.validate(
            ["alice@company.com", "outsider@gmail.com", "hacker@evil.org"]
        )
        assert error is not None
        assert "outsider@gmail.com" in error
        assert "hacker@evil.org" in error


# ---------------------------------------------------------------------------
# RecipientPolicy — parametrize pattern matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern, address, should_pass",
    [
        # Exact matches
        ("alice@example.com", "alice@example.com", True),
        ("alice@example.com", "bob@example.com", False),
        # Domain wildcards
        ("*@example.com", "anyone@example.com", True),
        ("*@example.com", "anyone@other.com", False),
        # Full wildcard
        ("*", "random@whatever.io", True),
        # Case insensitivity
        ("ALICE@EXAMPLE.COM", "alice@example.com", True),
        ("alice@example.com", "ALICE@EXAMPLE.COM", True),
        # Subdomain patterns
        ("*@*.example.com", "user@mail.example.com", True),
        ("*@*.example.com", "user@example.com", False),
        # Prefix wildcard on user part
        ("admin*@example.com", "admin@example.com", True),
        ("admin*@example.com", "admintools@example.com", True),
        ("admin*@example.com", "user@example.com", False),
    ],
)
def test_recipient_policy_pattern_matching(
    pattern: str, address: str, should_pass: bool
) -> None:
    policy = RecipientPolicy(allowed_patterns=[pattern])
    error = policy.validate([address])
    if should_pass:
        assert error is None, f"Expected {address!r} to match {pattern!r}, but got: {error}"
    else:
        assert error is not None, f"Expected {address!r} to be blocked by {pattern!r}"
