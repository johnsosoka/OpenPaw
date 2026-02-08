"""Tests for Telegram document upload handling."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.base import MessageDirection
from openpaw.channels.telegram import TelegramChannel


@pytest.mark.asyncio
async def test_document_to_message_pdf() -> None:
    """Test that PDF upload creates correct Message with Attachment."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    # Mock the Update object
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 67890
    update.effective_chat.type = "private"
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message.message_id = 1
    update.message.caption = "Check this out"
    update.message.date = datetime(2025, 1, 1, 12, 0, 0)
    update.message.reply_to_message = None

    # Mock document and file download
    pdf_data = b"%PDF-1.4 mock pdf content"
    mock_file = AsyncMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(pdf_data))

    update.message.document.file_name = "report.pdf"
    update.message.document.mime_type = "application/pdf"
    update.message.document.file_size = 1024
    update.message.document.get_file = AsyncMock(return_value=mock_file)

    # Convert to message
    message = await channel._document_to_message(update)

    # Verify message properties
    assert message is not None
    assert message.id == "1"
    assert message.channel == "telegram"
    assert message.session_key == "telegram:67890"
    assert message.user_id == "12345"
    assert message.content == "Check this out"
    assert message.direction == MessageDirection.INBOUND
    assert message.timestamp == datetime(2025, 1, 1, 12, 0, 0)
    assert message.reply_to_id is None

    # Verify metadata
    assert message.metadata["chat_type"] == "private"
    assert message.metadata["username"] == "testuser"
    assert message.metadata["first_name"] == "Test"
    assert message.metadata["has_document"] is True

    # Verify attachment
    assert len(message.attachments) == 1
    attachment = message.attachments[0]
    assert attachment.type == "document"
    assert attachment.data == pdf_data
    assert attachment.filename == "report.pdf"
    assert attachment.mime_type == "application/pdf"
    assert attachment.metadata["file_size"] == 1024


@pytest.mark.asyncio
async def test_document_to_message_with_caption() -> None:
    """Test that document with caption sets content correctly."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 67890
    update.effective_chat.type = "private"
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message.message_id = 1
    update.message.caption = "Here is the document you requested"
    update.message.date = datetime(2025, 1, 1, 12, 0, 0)
    update.message.reply_to_message = None

    mock_file = AsyncMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"data"))

    update.message.document.file_name = "doc.txt"
    update.message.document.mime_type = "text/plain"
    update.message.document.file_size = 100
    update.message.document.get_file = AsyncMock(return_value=mock_file)

    message = await channel._document_to_message(update)

    assert message is not None
    assert message.content == "Here is the document you requested"


@pytest.mark.asyncio
async def test_document_to_message_no_caption() -> None:
    """Test that document without caption has empty content."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 67890
    update.effective_chat.type = "private"
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message.message_id = 1
    update.message.caption = None  # No caption
    update.message.date = datetime(2025, 1, 1, 12, 0, 0)
    update.message.reply_to_message = None

    mock_file = AsyncMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"data"))

    update.message.document.file_name = "file.bin"
    update.message.document.mime_type = "application/octet-stream"
    update.message.document.file_size = 50
    update.message.document.get_file = AsyncMock(return_value=mock_file)

    message = await channel._document_to_message(update)

    assert message is not None
    assert message.content == ""


@pytest.mark.asyncio
async def test_document_to_message_download_failure() -> None:
    """Test that download failure returns None."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 67890
    update.effective_chat.type = "private"
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message.message_id = 1
    update.message.caption = "This will fail"
    update.message.date = datetime(2025, 1, 1, 12, 0, 0)
    update.message.reply_to_message = None

    # Mock download failure
    mock_file = AsyncMock()
    mock_file.download_as_bytearray = AsyncMock(side_effect=Exception("Network error"))

    update.message.document.file_name = "fail.pdf"
    update.message.document.mime_type = "application/pdf"
    update.message.document.file_size = 500
    update.message.document.get_file = AsyncMock(return_value=mock_file)

    message = await channel._document_to_message(update)

    assert message is None


@pytest.mark.asyncio
async def test_document_to_message_no_document() -> None:
    """Test that missing document returns None."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 67890
    update.effective_chat.type = "private"
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message.message_id = 1
    update.message.caption = "No document attached"
    update.message.date = datetime(2025, 1, 1, 12, 0, 0)
    update.message.reply_to_message = None
    update.message.document = None  # No document

    message = await channel._document_to_message(update)

    assert message is None


@pytest.mark.asyncio
async def test_document_to_message_no_mime_type() -> None:
    """Test that missing mime_type defaults to application/octet-stream."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 67890
    update.effective_chat.type = "private"
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message.message_id = 1
    update.message.caption = None
    update.message.date = datetime(2025, 1, 1, 12, 0, 0)
    update.message.reply_to_message = None

    mock_file = AsyncMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"unknown"))

    update.message.document.file_name = "unknown.xyz"
    update.message.document.mime_type = None  # No MIME type
    update.message.document.file_size = 10
    update.message.document.get_file = AsyncMock(return_value=mock_file)

    message = await channel._document_to_message(update)

    assert message is not None
    attachment = message.attachments[0]
    assert attachment.mime_type == "application/octet-stream"


@pytest.mark.asyncio
async def test_handle_document_unauthorized() -> None:
    """Test that unauthorized user gets rejection response."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],  # Only user 12345 allowed
        workspace_name="test",
    )

    # Unauthorized user
    update = MagicMock()
    update.effective_user.id = 99999  # Different user
    update.effective_chat.id = 67890
    update.effective_chat.type = "private"
    update.effective_user.username = "unauthorized"
    update.effective_user.first_name = "Unauthorized"
    update.message.message_id = 1
    update.message.reply_text = AsyncMock()

    context = MagicMock()

    # Should call unauthorized response
    await channel._handle_document(update, context)

    # Verify reply_text was called with rejection message
    assert update.message.reply_text.called
    call_args = update.message.reply_text.call_args
    assert "access denied" in call_args[0][0].lower()


@pytest.mark.asyncio
async def test_handle_document_invokes_callback() -> None:
    """Test full flow: handler creates message and invokes callback."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    # Mock callback
    callback_invoked = False
    received_message = None

    async def mock_callback(msg):
        nonlocal callback_invoked, received_message
        callback_invoked = True
        received_message = msg

    channel.on_message(mock_callback)

    # Create update with document
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 67890
    update.effective_chat.type = "private"
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message.message_id = 1
    update.message.caption = "Document caption"
    update.message.date = datetime(2025, 1, 1, 12, 0, 0)
    update.message.reply_to_message = None

    doc_data = b"document content here"
    mock_file = AsyncMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(doc_data))

    update.message.document.file_name = "test.pdf"
    update.message.document.mime_type = "application/pdf"
    update.message.document.file_size = len(doc_data)
    update.message.document.get_file = AsyncMock(return_value=mock_file)

    context = MagicMock()

    # Handle document
    await channel._handle_document(update, context)

    # Verify callback was invoked
    assert callback_invoked
    assert received_message is not None
    assert received_message.content == "Document caption"
    assert len(received_message.attachments) == 1
    assert received_message.attachments[0].filename == "test.pdf"
    assert received_message.attachments[0].data == doc_data


@pytest.mark.asyncio
async def test_document_to_message_with_reply() -> None:
    """Test that reply_to_id is set correctly when replying to another message."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat.id = 67890
    update.effective_chat.type = "private"
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message.message_id = 2
    update.message.caption = "Reply with document"
    update.message.date = datetime(2025, 1, 1, 12, 0, 0)

    # Mock reply_to_message
    reply_message = MagicMock()
    reply_message.message_id = 1
    update.message.reply_to_message = reply_message

    mock_file = AsyncMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"data"))

    update.message.document.file_name = "reply.pdf"
    update.message.document.mime_type = "application/pdf"
    update.message.document.file_size = 100
    update.message.document.get_file = AsyncMock(return_value=mock_file)

    message = await channel._document_to_message(update)

    assert message is not None
    assert message.reply_to_id == "1"


@pytest.mark.asyncio
async def test_document_to_message_various_file_types() -> None:
    """Test handling various document types (DOCX, images, etc.)."""
    channel = TelegramChannel(
        token="test-token",
        allowed_users=[12345],
        workspace_name="test",
    )

    test_cases = [
        ("document.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("image.png", "image/png"),
        ("data.json", "application/json"),
        ("archive.zip", "application/zip"),
    ]

    for filename, mime_type in test_cases:
        update = MagicMock()
        update.effective_user.id = 12345
        update.effective_chat.id = 67890
        update.effective_chat.type = "private"
        update.effective_user.username = "testuser"
        update.effective_user.first_name = "Test"
        update.message.message_id = 1
        update.message.caption = None
        update.message.date = datetime(2025, 1, 1, 12, 0, 0)
        update.message.reply_to_message = None

        mock_file = AsyncMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"test"))

        update.message.document.file_name = filename
        update.message.document.mime_type = mime_type
        update.message.document.file_size = 100
        update.message.document.get_file = AsyncMock(return_value=mock_file)

        message = await channel._document_to_message(update)

        assert message is not None
        attachment = message.attachments[0]
        assert attachment.filename == filename
        assert attachment.mime_type == mime_type
