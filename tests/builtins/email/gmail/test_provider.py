"""Tests for GmailProvider integration — send, list, get, search."""

import pytest
from unittest.mock import MagicMock

from .conftest import _b64, _make_raw_message


class TestGmailProviderSend:
    """Tests for GmailProvider.send() with a mocked Gmail service."""

    @pytest.mark.asyncio
    async def test_successful_send_returns_message_id(self, provider) -> None:
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
    async def test_api_error_returns_error_string(self, provider) -> None:
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
        self, provider
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
    async def test_get_message_returns_email_message(self, provider) -> None:
        provider._service.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            self._make_full_raw()
        )

        msg = await provider.get_message("msg_full")

        assert msg.id == "msg_full"
        assert msg.subject == "Full Message"
        assert "Full body content." in msg.body

    @pytest.mark.asyncio
    async def test_get_message_raises_on_api_failure(self, provider) -> None:
        provider._service.users.return_value.messages.return_value.get.return_value.execute.side_effect = Exception(
            "Not found"
        )
        with pytest.raises(RuntimeError):
            await provider.get_message("nonexistent")


class TestGmailProviderListMessages:
    """Tests for GmailProvider.list_messages()."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_messages(self, provider) -> None:
        provider._service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }

        result = await provider.list_messages()
        assert result == []

    @pytest.mark.asyncio
    async def test_caps_max_results_at_100(self, provider) -> None:
        list_mock = MagicMock()
        list_mock.execute.return_value = {"messages": []}
        provider._service.users.return_value.messages.return_value.list.return_value = list_mock

        await provider.list_messages(max_results=200)

        call_kwargs = provider._service.users.return_value.messages.return_value.list.call_args[1]
        assert call_kwargs["maxResults"] <= 100

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_api_error(self, provider) -> None:
        provider._service.users.return_value.messages.return_value.list.return_value.execute.side_effect = Exception(
            "Service unavailable"
        )

        result = await provider.list_messages()
        assert result == []
