"""Simple Pydantic schema validation tests for email models."""

import pytest
from pydantic import ValidationError

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


class TestSendEmailInput:
    def test_minimal_fields(self) -> None:
        data = {"to": ["a@b.com"], "subject": "Hi", "body": "Hello."}
        inp = SendEmailInput(**data)
        assert inp.to == ["a@b.com"]
        assert inp.subject == "Hi"
        assert inp.body == "Hello."
        assert inp.cc is None
        assert inp.bcc is None
        assert inp.attachment_paths is None

    def test_with_cc_bcc_and_attachments(self) -> None:
        data = {
            "to": ["a@b.com"],
            "subject": "S",
            "body": "B",
            "cc": ["cc@b.com"],
            "bcc": ["bcc@b.com"],
            "attachment_paths": ["file.txt"],
        }
        inp = SendEmailInput(**data)
        assert inp.cc == ["cc@b.com"]
        assert inp.bcc == ["bcc@b.com"]
        assert inp.attachment_paths == ["file.txt"]

    def test_to_is_required(self) -> None:
        with pytest.raises(ValidationError):
            SendEmailInput(subject="S", body="B")

    def test_subject_is_required(self) -> None:
        with pytest.raises(ValidationError):
            SendEmailInput(to=["a@b.com"], body="B")

    def test_body_is_required(self) -> None:
        with pytest.raises(ValidationError):
            SendEmailInput(to=["a@b.com"], subject="S")


class TestCheckEmailInput:
    def test_defaults(self) -> None:
        inp = CheckEmailInput()
        assert inp.max_results == 10
        assert inp.label == "INBOX"

    def test_custom_values(self) -> None:
        inp = CheckEmailInput(max_results=20, label="SENT")
        assert inp.max_results == 20
        assert inp.label == "SENT"

    def test_max_results_capped_at_50(self) -> None:
        with pytest.raises(ValidationError):
            CheckEmailInput(max_results=51)

    def test_max_results_minimum(self) -> None:
        with pytest.raises(ValidationError):
            CheckEmailInput(max_results=0)


class TestGetEmailInput:
    def test_message_id_required(self) -> None:
        with pytest.raises(ValidationError):
            GetEmailInput()

    def test_valid(self) -> None:
        inp = GetEmailInput(message_id="msg123")
        assert inp.message_id == "msg123"


class TestSearchEmailInput:
    def test_query_required(self) -> None:
        with pytest.raises(ValidationError):
            SearchEmailInput()

    def test_defaults(self) -> None:
        inp = SearchEmailInput(query="from:alice")
        assert inp.max_results == 10

    def test_max_results_bounds(self) -> None:
        with pytest.raises(ValidationError):
            SearchEmailInput(query="test", max_results=0)
        with pytest.raises(ValidationError):
            SearchEmailInput(query="test", max_results=51)


class TestReplyEmailInput:
    def test_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            ReplyEmailInput()
        with pytest.raises(ValidationError):
            ReplyEmailInput(message_id="msg1")
        with pytest.raises(ValidationError):
            ReplyEmailInput(body="reply")

    def test_full(self) -> None:
        inp = ReplyEmailInput(message_id="msg1", body="Reply", attachment_paths=["file.txt"])
        assert inp.message_id == "msg1"
        assert inp.body == "Reply"
        assert inp.attachment_paths == ["file.txt"]


class TestDownloadAttachmentInput:
    def test_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            DownloadAttachmentInput()
        with pytest.raises(ValidationError):
            DownloadAttachmentInput(message_id="msg1")
        with pytest.raises(ValidationError):
            DownloadAttachmentInput(message_id="msg1", attachment_id="att1")

    def test_full(self) -> None:
        inp = DownloadAttachmentInput(
            message_id="msg1", attachment_id="att1", filename="file.pdf", save_as="renamed.pdf"
        )
        assert inp.message_id == "msg1"
        assert inp.attachment_id == "att1"
        assert inp.filename == "file.pdf"
        assert inp.save_as == "renamed.pdf"

    def test_save_as_optional(self) -> None:
        inp = DownloadAttachmentInput(
            message_id="msg1", attachment_id="att1", filename="file.pdf"
        )
        assert inp.save_as is None


class TestMarkAsReadInput:
    def test_message_id_required(self) -> None:
        with pytest.raises(ValidationError):
            MarkAsReadInput()

    def test_valid(self) -> None:
        inp = MarkAsReadInput(message_id="msg1")
        assert inp.message_id == "msg1"


class TestMarkAsUnreadInput:
    def test_message_id_required(self) -> None:
        with pytest.raises(ValidationError):
            MarkAsUnreadInput()

    def test_valid(self) -> None:
        inp = MarkAsUnreadInput(message_id="msg1")
        assert inp.message_id == "msg1"
