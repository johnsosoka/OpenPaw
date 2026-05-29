"""Tests for GmailLabelManager — mark as read/unread."""

import pytest
from unittest.mock import MagicMock


class TestGmailProviderMarkAsRead:
    """Tests for GmailProvider.mark_as_read()."""

    @pytest.mark.asyncio
    async def test_mark_as_read_calls_modify_with_remove_unread(self, provider) -> None:
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
    async def test_mark_as_read_raises_on_api_error(self, provider) -> None:
        provider._service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = Exception(
            "API down"
        )
        with pytest.raises(RuntimeError):
            await provider.mark_as_read("msg_001")


class TestGmailProviderMarkAsUnread:
    """Tests for GmailProvider.mark_as_unread()."""

    @pytest.mark.asyncio
    async def test_mark_as_unread_calls_modify_with_add_unread(self, provider) -> None:
        modify_mock = MagicMock()
        modify_mock.execute = MagicMock(return_value={})
        provider._service.users.return_value.messages.return_value.modify.return_value = (
            modify_mock
        )

        await provider.mark_as_unread("msg_002")

        call_kwargs = provider._service.users.return_value.messages.return_value.modify.call_args[1]
        assert "UNREAD" in call_kwargs["body"]["addLabelIds"]

    @pytest.mark.asyncio
    async def test_mark_as_unread_raises_on_api_error(self, provider) -> None:
        provider._service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = Exception(
            "Network error"
        )
        with pytest.raises(RuntimeError):
            await provider.mark_as_unread("msg_002")
