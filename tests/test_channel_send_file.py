"""Tests for channel send_file functionality."""

from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.base import ChannelAdapter, Message, MessageDirection
from openpaw.channels.telegram import TelegramChannel


class DummyChannel(ChannelAdapter):
    """Dummy channel for testing base class behavior."""

    name = "dummy"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        return Message(
            id="1",
            channel=self.name,
            session_key=session_key,
            user_id="1",
            content=content,
            direction=MessageDirection.OUTBOUND,
        )

    def on_message(self, callback: Any) -> None:
        pass


@pytest.mark.asyncio
async def test_base_channel_send_file_not_implemented() -> None:
    """Test that base ChannelAdapter.send_file() raises NotImplementedError."""
    channel = DummyChannel()

    with pytest.raises(NotImplementedError, match="Channel 'DummyChannel' does not support file sending"):
        await channel.send_file(
            session_key="dummy:123",
            file_data=b"test data",
            filename="test.txt",
        )


@pytest.mark.asyncio
async def test_telegram_send_file_success() -> None:
    """Test successful file sending via Telegram."""
    # Create channel
    channel = TelegramChannel(
        token="test_token",
        allowed_users=[123],
        workspace_name="test_workspace",
    )

    # Mock the application and bot
    mock_bot = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    # Test file data
    file_data = b"test file content"
    filename = "document.txt"
    caption = "Test document"

    # Send file
    await channel.send_file(
        session_key="telegram:123456",
        file_data=file_data,
        filename=filename,
        caption=caption,
    )

    # Verify send_document was called
    assert mock_bot.send_document.called
    call_kwargs = mock_bot.send_document.call_args.kwargs

    assert call_kwargs["chat_id"] == 123456
    assert call_kwargs["caption"] == caption
    assert call_kwargs["filename"] == filename

    # Verify document is a BytesIO object with correct content
    document = call_kwargs["document"]
    assert isinstance(document, BytesIO)
    assert document.name == filename
    assert document.getvalue() == file_data


@pytest.mark.asyncio
async def test_telegram_send_file_without_caption() -> None:
    """Test file sending without caption."""
    channel = TelegramChannel(
        token="test_token",
        allowed_users=[123],
        workspace_name="test_workspace",
    )

    mock_bot = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    file_data = b"content without caption"
    filename = "nocaption.txt"

    await channel.send_file(
        session_key="telegram:789",
        file_data=file_data,
        filename=filename,
        caption=None,
    )

    call_kwargs = mock_bot.send_document.call_args.kwargs
    assert call_kwargs["caption"] is None
    assert call_kwargs["chat_id"] == 789


@pytest.mark.asyncio
async def test_telegram_send_file_not_started() -> None:
    """Test that sending file before channel start raises RuntimeError."""
    channel = TelegramChannel(
        token="test_token",
        allowed_users=[123],
        workspace_name="test_workspace",
    )

    # _app is None (not started)
    assert channel._app is None

    with pytest.raises(RuntimeError, match="Telegram channel not started"):
        await channel.send_file(
            session_key="telegram:123",
            file_data=b"test",
            filename="test.txt",
        )


@pytest.mark.asyncio
async def test_telegram_send_file_exceeds_size_limit() -> None:
    """Test that files exceeding 50MB limit raise ValueError."""
    channel = TelegramChannel(
        token="test_token",
        allowed_users=[123],
        workspace_name="test_workspace",
    )

    mock_app = MagicMock()
    mock_app.bot = AsyncMock()
    channel._app = mock_app

    # Create file larger than 50MB
    file_data = b"x" * (51 * 1024 * 1024)  # 51 MB

    with pytest.raises(ValueError, match="File size .* exceeds Telegram's 50 MB limit"):
        await channel.send_file(
            session_key="telegram:123",
            file_data=file_data,
            filename="huge.bin",
        )

    # Verify send_document was NOT called
    assert not mock_app.bot.send_document.called


@pytest.mark.asyncio
async def test_telegram_send_file_exactly_at_limit() -> None:
    """Test that file exactly at 50MB limit is accepted."""
    channel = TelegramChannel(
        token="test_token",
        allowed_users=[123],
        workspace_name="test_workspace",
    )

    mock_bot = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    # Create file exactly 50MB
    file_data = b"x" * (50 * 1024 * 1024)

    # Should not raise
    await channel.send_file(
        session_key="telegram:123",
        file_data=file_data,
        filename="exactly_50mb.bin",
    )

    # Verify it was sent
    assert mock_bot.send_document.called


@pytest.mark.asyncio
async def test_telegram_send_file_empty_file() -> None:
    """Test sending empty file."""
    channel = TelegramChannel(
        token="test_token",
        allowed_users=[123],
        workspace_name="test_workspace",
    )

    mock_bot = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    # Empty file
    file_data = b""

    await channel.send_file(
        session_key="telegram:456",
        file_data=file_data,
        filename="empty.txt",
    )

    # Verify send_document was called with empty data
    assert mock_bot.send_document.called
    call_kwargs = mock_bot.send_document.call_args.kwargs
    document = call_kwargs["document"]
    assert document.getvalue() == b""


@pytest.mark.asyncio
async def test_telegram_send_file_with_mime_type() -> None:
    """Test that mime_type parameter is accepted (even if unused by Telegram API)."""
    channel = TelegramChannel(
        token="test_token",
        allowed_users=[123],
        workspace_name="test_workspace",
    )

    mock_bot = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    # Send with mime_type
    await channel.send_file(
        session_key="telegram:123",
        file_data=b"pdf content",
        filename="document.pdf",
        mime_type="application/pdf",
    )

    # Should not raise, mime_type is accepted as parameter
    assert mock_bot.send_document.called


@pytest.mark.asyncio
async def test_telegram_send_file_api_error() -> None:
    """Test handling of Telegram API errors during send."""
    channel = TelegramChannel(
        token="test_token",
        allowed_users=[123],
        workspace_name="test_workspace",
    )

    # Mock bot that raises an exception
    mock_bot = AsyncMock()
    mock_bot.send_document.side_effect = Exception("Telegram API error")
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    with pytest.raises(RuntimeError, match="Failed to send file: Telegram API error"):
        await channel.send_file(
            session_key="telegram:123",
            file_data=b"test",
            filename="test.txt",
        )


@pytest.mark.asyncio
async def test_telegram_send_file_parses_session_key() -> None:
    """Test that session key is correctly parsed to extract chat_id."""
    channel = TelegramChannel(
        token="test_token",
        allowed_users=[123],
        workspace_name="test_workspace",
    )

    mock_bot = AsyncMock()
    mock_app = MagicMock()
    mock_app.bot = mock_bot
    channel._app = mock_app

    # Test different chat IDs
    test_cases = [
        ("telegram:12345", 12345),
        ("telegram:999888777", 999888777),
        ("telegram:-100123456789", -100123456789),  # Group chat ID
    ]

    for session_key, expected_chat_id in test_cases:
        mock_bot.reset_mock()

        await channel.send_file(
            session_key=session_key,
            file_data=b"test",
            filename="test.txt",
        )

        call_kwargs = mock_bot.send_document.call_args.kwargs
        assert call_kwargs["chat_id"] == expected_chat_id


def test_telegram_max_file_size_constant() -> None:
    """Test that MAX_FILE_SIZE constant is correctly set."""
    assert TelegramChannel.MAX_FILE_SIZE == 50 * 1024 * 1024
    assert TelegramChannel.MAX_FILE_SIZE == 52428800  # Exactly 50 MB in bytes
