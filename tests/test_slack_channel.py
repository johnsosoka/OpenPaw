"""Tests for Slack channel adapter."""

from datetime import datetime
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from openpaw.channels.slack import SlackChannel
from openpaw.domain.message import MessageDirection


# Construction tests


def test_slack_channel_construction_defaults() -> None:
    """Test that SlackChannel initializes with correct default values."""
    channel = SlackChannel(
        bot_token="xoxb-test-token",
        app_token="xapp-test-token",
        workspace_name="test_workspace",
    )

    assert channel.bot_token == "xoxb-test-token"
    assert channel.app_token == "xapp-test-token"
    assert channel.signing_secret is None
    assert channel.allowed_users == set()
    assert channel.allowed_channels == set()
    assert channel.allow_all is False
    assert channel.workspace_name == "test_workspace"
    assert channel._app is None
    assert channel._handler is None
    assert channel._bot_user_id is None


def test_slack_channel_construction_all_parameters() -> None:
    """Test that all constructor parameters are passed correctly."""
    channel = SlackChannel(
        bot_token="xoxb-token",
        app_token="xapp-token",
        signing_secret="secret123",
        allowed_users=["U123", "U456"],
        allowed_channels=["C789", "C012"],
        allow_all=True,
        workspace_name="my_workspace",
    )

    assert channel.bot_token == "xoxb-token"
    assert channel.app_token == "xapp-token"
    assert channel.signing_secret == "secret123"
    assert channel.allowed_users == {"U123", "U456"}
    assert channel.allowed_channels == {"C789", "C012"}
    assert channel.allow_all is True
    assert channel.workspace_name == "my_workspace"


def test_slack_channel_name_attribute() -> None:
    """Test that channel.name is set correctly."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    assert channel.name == "slack"


# Access control tests


def test_is_allowed_allow_all_mode() -> None:
    """Test that allow_all=True allows any user."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allow_all=True,
    )

    # Any user, any channel should be allowed
    assert channel._is_allowed("U123", "C456") is True
    assert channel._is_allowed("U999", "C999") is True
    assert channel._is_allowed("UABC", "DXYZ") is True


def test_is_allowed_user_in_allowlist() -> None:
    """Test that user in allowed_users is allowed."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123", "U456"],
    )

    assert channel._is_allowed("U123", "C789") is True
    assert channel._is_allowed("U456", "C789") is True


def test_is_allowed_user_not_in_allowlist() -> None:
    """Test that user NOT in allowed_users is denied."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123", "U456"],
    )

    assert channel._is_allowed("U999", "C789") is False
    assert channel._is_allowed("UABC", "C789") is False


def test_is_allowed_empty_allowlists_denies_all() -> None:
    """Test that empty allowlists with allow_all=False denies all users."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allow_all=False,
    )

    # No allowlists configured = deny all
    assert channel._is_allowed("U123", "C456") is False
    assert channel._is_allowed("U999", "D123") is False


def test_is_allowed_channel_restriction_in_channel() -> None:
    """Test that channel restriction works for channels."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
        allowed_channels=["C456"],
    )

    # User allowed, channel allowed
    assert channel._is_allowed("U123", "C456") is True

    # User allowed, channel not allowed
    assert channel._is_allowed("U123", "C999") is False


def test_is_allowed_channel_restriction_in_dm() -> None:
    """Test that DMs bypass channel allowlist."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
        allowed_channels=["C456"],
    )

    # DM (starts with "D") bypasses channel allowlist
    assert channel._is_allowed("U123", "D789") is True


# Mention activation tests


@pytest.mark.asyncio
async def test_dm_messages_always_processed() -> None:
    """Test that DM messages (channel starts with 'D') are always processed."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )
    channel._bot_user_id = "UBOT"

    callback_invoked = False

    async def mock_callback(msg):
        nonlocal callback_invoked
        callback_invoked = True

    channel.on_message(mock_callback)

    event = {
        "channel": "D456",  # DM channel
        "user": "U123",
        "text": "Hello bot",
        "ts": "1234567890.123456",
    }

    await channel._handle_message_event(event, None)

    # Should process without requiring @mention
    assert callback_invoked is True


@pytest.mark.asyncio
async def test_channel_message_with_mention_processed() -> None:
    """Test that channel messages with @mention are processed."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )
    channel._bot_user_id = "UBOT"

    callback_invoked = False
    received_text = None

    async def mock_callback(msg):
        nonlocal callback_invoked, received_text
        callback_invoked = True
        received_text = msg.content

    channel.on_message(mock_callback)

    event = {
        "channel": "C456",  # Channel, not DM
        "user": "U123",
        "text": "<@UBOT> Hello there",
        "ts": "1234567890.123456",
    }

    await channel._handle_message_event(event, None)

    assert callback_invoked is True
    # Mention should be stripped from content
    assert received_text == "Hello there"


@pytest.mark.asyncio
async def test_channel_message_without_mention_dropped() -> None:
    """Test that channel messages without @mention are silently dropped."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )
    channel._bot_user_id = "UBOT"

    callback_invoked = False

    async def mock_callback(msg):
        nonlocal callback_invoked
        callback_invoked = True

    channel.on_message(mock_callback)

    event = {
        "channel": "C456",  # Channel, not DM
        "user": "U123",
        "text": "Hello there",  # No mention
        "ts": "1234567890.123456",
    }

    await channel._handle_message_event(event, None)

    # Should be dropped silently
    assert callback_invoked is False


@pytest.mark.asyncio
async def test_mention_text_stripped() -> None:
    """Test that <@BOT_ID> mention text is stripped from content."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )
    channel._bot_user_id = "UBOT"

    received_text = None

    async def mock_callback(msg):
        nonlocal received_text
        received_text = msg.content

    channel.on_message(mock_callback)

    event = {
        "channel": "C456",
        "user": "U123",
        "text": "Hey <@UBOT> can you help?",
        "ts": "1234567890.123456",
    }

    await channel._handle_message_event(event, None)

    assert received_text == "Hey  can you help?"


@pytest.mark.asyncio
async def test_mention_multiple_occurrences_all_stripped() -> None:
    """Test that multiple mentions are all stripped."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )
    channel._bot_user_id = "UBOT"

    received_text = None

    async def mock_callback(msg):
        nonlocal received_text
        received_text = msg.content

    channel.on_message(mock_callback)

    event = {
        "channel": "C456",
        "user": "U123",
        "text": "<@UBOT> hello <@UBOT> world",
        "ts": "1234567890.123456",
    }

    await channel._handle_message_event(event, None)

    assert received_text == "hello  world"


# Message conversion tests


@pytest.mark.asyncio
async def test_event_to_message_session_key() -> None:
    """Test that session_key has correct format 'slack:channel_id'."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )

    event = {
        "channel": "C456",
        "user": "U123",
        "text": "Hello",
        "ts": "1234567890.123456",
    }

    message = await channel._event_to_message(event, "Hello")

    assert message is not None
    assert message.session_key == "slack:C456"


@pytest.mark.asyncio
async def test_event_to_message_metadata_populated() -> None:
    """Test that metadata contains chat_type, username, first_name."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )
    channel._app = AsyncMock()
    channel._app.client.users_info = AsyncMock(
        return_value={
            "user": {
                "profile": {
                    "display_name": "Test User",
                    "real_name": "Test User Real",
                }
            }
        }
    )

    event = {
        "channel": "D456",  # DM
        "user": "U123",
        "text": "Hello",
        "ts": "1234567890.123456",
    }

    message = await channel._event_to_message(event, "Hello")

    assert message is not None
    assert message.metadata["chat_type"] == "im"
    assert message.metadata["username"] == "U123"
    assert message.metadata["first_name"] == "Test User"


@pytest.mark.asyncio
async def test_event_to_message_chat_types() -> None:
    """Test that chat_type is correctly identified for DM, group, channel."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )

    # DM
    event_dm = {
        "channel": "D456",
        "user": "U123",
        "text": "Hello",
        "ts": "1234567890.123456",
    }
    message = await channel._event_to_message(event_dm, "Hello")
    assert message.metadata["chat_type"] == "im"

    # Group
    event_group = {
        "channel": "G789",
        "user": "U123",
        "text": "Hello",
        "ts": "1234567890.123456",
    }
    message = await channel._event_to_message(event_group, "Hello")
    assert message.metadata["chat_type"] == "group"

    # Channel
    event_channel = {
        "channel": "C012",
        "user": "U123",
        "text": "Hello",
        "ts": "1234567890.123456",
    }
    message = await channel._event_to_message(event_channel, "Hello")
    assert message.metadata["chat_type"] == "channel"


@pytest.mark.asyncio
async def test_event_to_message_user_id_is_string() -> None:
    """Test that user_id is converted to string."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )

    event = {
        "channel": "C456",
        "user": "U123",
        "text": "Hello",
        "ts": "1234567890.123456",
    }

    message = await channel._event_to_message(event, "Hello")

    assert message is not None
    assert isinstance(message.user_id, str)
    assert message.user_id == "U123"


@pytest.mark.asyncio
async def test_event_to_message_direction_inbound() -> None:
    """Test that direction is INBOUND."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )

    event = {
        "channel": "C456",
        "user": "U123",
        "text": "Hello",
        "ts": "1234567890.123456",
    }

    message = await channel._event_to_message(event, "Hello")

    assert message is not None
    assert message.direction == MessageDirection.INBOUND


@pytest.mark.asyncio
async def test_event_to_message_timestamp_parsed() -> None:
    """Test that timestamp is parsed from Slack ts field."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )

    event = {
        "channel": "C456",
        "user": "U123",
        "text": "Hello",
        "ts": "1704110400.000000",  # 2024-01-01 12:00:00 UTC
    }

    message = await channel._event_to_message(event, "Hello")

    assert message is not None
    assert message.timestamp == datetime.fromtimestamp(1704110400.0)


@pytest.mark.asyncio
async def test_event_to_message_invalid_timestamp_fallback() -> None:
    """Test that invalid timestamp falls back to datetime.now()."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )

    event = {
        "channel": "C456",
        "user": "U123",
        "text": "Hello",
        "ts": "invalid",
    }

    with patch("openpaw.channels.slack.datetime") as mock_datetime:
        mock_now = datetime(2025, 1, 1, 12, 0, 0)
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromtimestamp.side_effect = ValueError("Invalid timestamp")

        message = await channel._event_to_message(event, "Hello")

    assert message is not None
    assert message.timestamp == mock_now


# send_message tests


@pytest.mark.asyncio
async def test_send_message_extracts_channel_id() -> None:
    """Test that send_message extracts channel_id from session_key."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.chat_postMessage = AsyncMock(return_value={"ts": "1234567890.123456"})
    channel._bot_user_id = "UBOT"

    await channel.send_message("slack:C456", "Test message")

    # Verify chat_postMessage was called with correct channel
    channel._app.client.chat_postMessage.assert_called_once_with(
        channel="C456",
        text="Test message",
    )


@pytest.mark.asyncio
async def test_send_message_splitting_long_message() -> None:
    """Test that messages exceeding ~4000 chars are split."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.chat_postMessage = AsyncMock(return_value={"ts": "1234567890.123456"})
    channel._bot_user_id = "UBOT"

    # Create a message longer than MAX_MESSAGE_LENGTH
    long_message = "A" * 5000

    await channel.send_message("slack:C456", long_message)

    # Should have been called multiple times for chunks
    assert channel._app.client.chat_postMessage.call_count > 1


@pytest.mark.asyncio
async def test_send_message_returns_correct_message() -> None:
    """Test that send_message returns Message with correct fields."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.chat_postMessage = AsyncMock(return_value={"ts": "1234567890.123456"})
    channel._bot_user_id = "UBOT"

    result = await channel.send_message("slack:C456", "Test message")

    assert result.id == "1234567890.123456"
    assert result.channel == "slack"
    assert result.session_key == "slack:C456"
    assert result.user_id == "UBOT"
    assert result.content == "Test message"
    assert result.direction == MessageDirection.OUTBOUND


@pytest.mark.asyncio
async def test_send_message_not_started_raises_error() -> None:
    """Test that send_message raises error if channel not started."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    with pytest.raises(RuntimeError, match="Slack channel not started"):
        await channel.send_message("slack:C456", "Test")


@pytest.mark.asyncio
async def test_split_message_short_message() -> None:
    """Test that short messages are not split."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    chunks = channel._split_message("Short message")

    assert len(chunks) == 1
    assert chunks[0] == "Short message"


@pytest.mark.asyncio
async def test_split_message_paragraph_boundary() -> None:
    """Test that long messages split at paragraph boundaries."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    # Create message with paragraph break within limit range
    part1 = "A" * 3900
    part2 = "B" * 100
    long_message = part1 + "\n\n" + part2

    chunks = channel._split_message(long_message)

    assert len(chunks) == 2
    assert chunks[0] == part1
    assert chunks[1].startswith("B")


# send_file tests


@pytest.mark.asyncio
async def test_send_file_calls_files_upload_v2() -> None:
    """Test that send_file calls files_upload_v2 with correct parameters."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.files_upload_v2 = AsyncMock()

    file_data = b"test file content"
    await channel.send_file(
        "slack:C456",
        file_data,
        "test.txt",
        mime_type="text/plain",
        caption="Test caption",
    )

    channel._app.client.files_upload_v2.assert_called_once_with(
        channel="C456",
        content=file_data,
        filename="test.txt",
        initial_comment="Test caption",
    )


@pytest.mark.asyncio
async def test_send_file_without_caption() -> None:
    """Test that send_file works without caption."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.files_upload_v2 = AsyncMock()

    file_data = b"content"
    await channel.send_file("slack:C456", file_data, "file.bin")

    channel._app.client.files_upload_v2.assert_called_once_with(
        channel="C456",
        content=file_data,
        filename="file.bin",
        initial_comment=None,
    )


@pytest.mark.asyncio
async def test_send_file_not_started_raises_error() -> None:
    """Test that send_file raises error if channel not started."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    with pytest.raises(RuntimeError, match="Slack channel not started"):
        await channel.send_file("slack:C456", b"data", "file.txt")


@pytest.mark.asyncio
async def test_send_file_upload_failure_raises() -> None:
    """Test that send_file raises RuntimeError on upload failure."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.files_upload_v2 = AsyncMock(side_effect=Exception("Upload failed"))

    with pytest.raises(RuntimeError, match="Failed to send file"):
        await channel.send_file("slack:C456", b"data", "file.txt")


# Approval request tests


@pytest.mark.asyncio
async def test_send_approval_request_block_kit_structure() -> None:
    """Test that approval request generates correct Block Kit structure."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.chat_postMessage = AsyncMock()

    await channel.send_approval_request(
        "slack:C456",
        "approval_123",
        "delete_file",
        {"path": "/tmp/file.txt"},
        show_args=True,
    )

    call_args = channel._app.client.chat_postMessage.call_args

    # Check blocks structure
    blocks = call_args.kwargs["blocks"]
    assert len(blocks) == 2

    # Section with text
    assert blocks[0]["type"] == "section"
    assert "delete_file" in blocks[0]["text"]["text"]
    assert "/tmp/file.txt" in blocks[0]["text"]["text"]

    # Actions with buttons
    assert blocks[1]["type"] == "actions"
    assert len(blocks[1]["elements"]) == 2

    # Approve button
    approve_button = blocks[1]["elements"][0]
    assert approve_button["type"] == "button"
    assert approve_button["action_id"] == "approve:approval_123"
    assert approve_button["value"] == "approval_123"
    assert approve_button["style"] == "primary"

    # Deny button
    deny_button = blocks[1]["elements"][1]
    assert deny_button["type"] == "button"
    assert deny_button["action_id"] == "deny:approval_123"
    assert deny_button["value"] == "approval_123"
    assert deny_button["style"] == "danger"


@pytest.mark.asyncio
async def test_send_approval_request_without_args() -> None:
    """Test that approval request without show_args hides arguments."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.chat_postMessage = AsyncMock()

    await channel.send_approval_request(
        "slack:C456",
        "approval_123",
        "sensitive_operation",
        {"secret": "value"},
        show_args=False,
    )

    call_args = channel._app.client.chat_postMessage.call_args
    blocks = call_args.kwargs["blocks"]

    # Args should not be in text
    assert "Args:" not in blocks[0]["text"]["text"]
    assert "secret" not in blocks[0]["text"]["text"]


@pytest.mark.asyncio
async def test_send_approval_request_truncates_long_args() -> None:
    """Test that long arguments are truncated to 500 chars."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.chat_postMessage = AsyncMock()

    long_args = {"data": "A" * 600}

    await channel.send_approval_request(
        "slack:C456",
        "approval_123",
        "process_data",
        long_args,
        show_args=True,
    )

    call_args = channel._app.client.chat_postMessage.call_args
    blocks = call_args.kwargs["blocks"]

    # Should contain truncation marker
    assert "..." in blocks[0]["text"]["text"]


@pytest.mark.asyncio
async def test_handle_approval_action_approve() -> None:
    """Test that approval action handler processes approve correctly."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.chat_update = AsyncMock()

    approval_invoked = False
    received_approval_id = None
    received_approved = None

    async def mock_approval_callback(approval_id, approved):
        nonlocal approval_invoked, received_approval_id, received_approved
        approval_invoked = True
        received_approval_id = approval_id
        received_approved = approved

    channel.on_approval(mock_approval_callback)

    ack = AsyncMock()
    body = {
        "actions": [
            {
                "action_id": "approve:approval_123",
            }
        ],
        "channel": {"id": "C456"},
        "message": {
            "ts": "1234567890.123456",
            "text": "Approval Required",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "Tool: delete_file"}},
                {"type": "actions", "elements": []},
            ],
        },
    }

    await channel._handle_approval_action(ack, body)

    ack.assert_called_once()
    assert approval_invoked is True
    assert received_approval_id == "approval_123"
    assert received_approved is True

    # Verify message was updated with result
    channel._app.client.chat_update.assert_called_once()
    update_call = channel._app.client.chat_update.call_args
    updated_blocks = update_call.kwargs["blocks"]
    assert "✅ Approved" in updated_blocks[-1]["text"]["text"]


@pytest.mark.asyncio
async def test_handle_approval_action_deny() -> None:
    """Test that approval action handler processes deny correctly."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.chat_update = AsyncMock()

    received_approved = None

    async def mock_approval_callback(approval_id, approved):
        nonlocal received_approved
        received_approved = approved

    channel.on_approval(mock_approval_callback)

    ack = AsyncMock()
    body = {
        "actions": [
            {
                "action_id": "deny:approval_456",
            }
        ],
        "channel": {"id": "C456"},
        "message": {
            "ts": "1234567890.123456",
            "text": "Approval Required",
            "blocks": [
                {"type": "section", "text": {"type": "mrkdwn", "text": "Tool: delete_file"}},
                {"type": "actions", "elements": []},
            ],
        },
    }

    await channel._handle_approval_action(ack, body)

    assert received_approved is False

    # Verify message was updated with denial
    update_call = channel._app.client.chat_update.call_args
    updated_blocks = update_call.kwargs["blocks"]
    assert "❌ Denied" in updated_blocks[-1]["text"]["text"]


# Inbound file handling tests


@pytest.mark.asyncio
async def test_download_file_success() -> None:
    """Test successful file download creates Attachment."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    file_data_dict = {
        "id": "F123",
        "name": "document.pdf",
        "mimetype": "application/pdf",
        "url_private_download": "https://files.slack.com/file.pdf",
    }

    file_bytes = b"%PDF-1.4 test content"

    with patch("openpaw.channels.slack.aiohttp.ClientSession") as mock_session_class:
        # Create response mock
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=file_bytes)

        # Create context manager for response
        mock_response_context = AsyncMock()
        mock_response_context.__aenter__.return_value = mock_response
        mock_response_context.__aexit__.return_value = None

        # Create session mock with get() returning context manager
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response_context

        # Create context manager for session
        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        mock_session_context.__aexit__.return_value = None

        # Session class returns session context manager
        mock_session_class.return_value = mock_session_context

        attachment = await channel._download_file(file_data_dict)

    assert attachment is not None
    assert attachment.type == "document"
    assert attachment.data == file_bytes
    assert attachment.filename == "document.pdf"
    assert attachment.mime_type == "application/pdf"
    assert attachment.metadata["file_id"] == "F123"
    assert attachment.metadata["file_size"] == len(file_bytes)


@pytest.mark.asyncio
async def test_download_file_mime_type_image() -> None:
    """Test that image MIME type maps to 'image' attachment type."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    file_data_dict = {
        "id": "F456",
        "name": "photo.jpg",
        "mimetype": "image/jpeg",
        "url_private": "https://files.slack.com/photo.jpg",
    }

    file_bytes = b"\xff\xd8\xff test image"

    with patch("openpaw.channels.slack.aiohttp.ClientSession") as mock_session_class:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=file_bytes)

        mock_response_context = AsyncMock()
        mock_response_context.__aenter__.return_value = mock_response
        mock_response_context.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response_context

        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        mock_session_context.__aexit__.return_value = None

        mock_session_class.return_value = mock_session_context

        attachment = await channel._download_file(file_data_dict)

    assert attachment.type == "image"
    assert attachment.mime_type == "image/jpeg"


@pytest.mark.asyncio
async def test_download_file_mime_type_audio() -> None:
    """Test that audio MIME type maps to 'audio' attachment type."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    file_data_dict = {
        "id": "F789",
        "name": "sound.mp3",
        "mimetype": "audio/mpeg",
        "url_private": "https://files.slack.com/sound.mp3",
    }

    with patch("openpaw.channels.slack.aiohttp.ClientSession") as mock_session_class:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"audio data")

        mock_response_context = AsyncMock()
        mock_response_context.__aenter__.return_value = mock_response
        mock_response_context.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response_context

        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        mock_session_context.__aexit__.return_value = None

        mock_session_class.return_value = mock_session_context

        attachment = await channel._download_file(file_data_dict)

    assert attachment.type == "audio"


@pytest.mark.asyncio
async def test_download_file_mime_type_video() -> None:
    """Test that video MIME type maps to 'video' attachment type."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    file_data_dict = {
        "id": "F012",
        "name": "clip.mp4",
        "mimetype": "video/mp4",
        "url_private": "https://files.slack.com/clip.mp4",
    }

    with patch("openpaw.channels.slack.aiohttp.ClientSession") as mock_session_class:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"video data")

        mock_response_context = AsyncMock()
        mock_response_context.__aenter__.return_value = mock_response
        mock_response_context.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response_context

        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        mock_session_context.__aexit__.return_value = None

        mock_session_class.return_value = mock_session_context

        attachment = await channel._download_file(file_data_dict)

    assert attachment.type == "video"


@pytest.mark.asyncio
async def test_download_file_no_url() -> None:
    """Test that missing download URL returns None."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    file_data_dict = {
        "id": "F999",
        "name": "file.txt",
    }

    attachment = await channel._download_file(file_data_dict)

    assert attachment is None


@pytest.mark.asyncio
async def test_download_file_http_error() -> None:
    """Test that HTTP error returns None."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    file_data_dict = {
        "id": "F888",
        "name": "file.txt",
        "url_private": "https://files.slack.com/file.txt",
    }

    with patch("openpaw.channels.slack.aiohttp.ClientSession") as mock_session_class:
        mock_response = MagicMock()
        mock_response.status = 404

        mock_response_context = AsyncMock()
        mock_response_context.__aenter__.return_value = mock_response
        mock_response_context.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response_context

        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        mock_session_context.__aexit__.return_value = None

        mock_session_class.return_value = mock_session_context

        attachment = await channel._download_file(file_data_dict)

    assert attachment is None


@pytest.mark.asyncio
async def test_download_file_uses_bot_token_auth() -> None:
    """Test that download uses bot token for authorization."""
    channel = SlackChannel(
        bot_token="xoxb-secret-token",
        app_token="xapp-test",
    )

    file_data_dict = {
        "id": "F123",
        "name": "file.txt",
        "url_private": "https://files.slack.com/file.txt",
    }

    with patch("openpaw.channels.slack.aiohttp.ClientSession") as mock_session_class:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"data")

        mock_response_context = AsyncMock()
        mock_response_context.__aenter__.return_value = mock_response
        mock_response_context.__aexit__.return_value = None

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response_context

        mock_session_context = AsyncMock()
        mock_session_context.__aenter__.return_value = mock_session
        mock_session_context.__aexit__.return_value = None

        mock_session_class.return_value = mock_session_context

        await channel._download_file(file_data_dict)

        # Verify Authorization header was set
        mock_session.get.assert_called_once_with(
            "https://files.slack.com/file.txt",
            headers={"Authorization": "Bearer xoxb-secret-token"},
        )


# User info caching tests


@pytest.mark.asyncio
async def test_get_user_display_name_api_call() -> None:
    """Test that first lookup calls Slack API."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.users_info = AsyncMock(
        return_value={
            "user": {
                "profile": {
                    "display_name": "John Doe",
                    "real_name": "John Doe Real",
                }
            }
        }
    )

    display_name = await channel._get_user_display_name("U123")

    assert display_name == "John Doe"
    channel._app.client.users_info.assert_called_once_with(user="U123")


@pytest.mark.asyncio
async def test_get_user_display_name_cache_hit() -> None:
    """Test that second lookup uses cache."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.users_info = AsyncMock(
        return_value={
            "user": {
                "profile": {
                    "display_name": "Jane Smith",
                    "real_name": "Jane Smith Real",
                }
            }
        }
    )

    # First call
    await channel._get_user_display_name("U456")

    # Second call (should use cache)
    display_name = await channel._get_user_display_name("U456")

    assert display_name == "Jane Smith"
    # API should only be called once
    assert channel._app.client.users_info.call_count == 1


@pytest.mark.asyncio
async def test_get_user_display_name_fallback_to_real_name() -> None:
    """Test that real_name is used when display_name is empty."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.users_info = AsyncMock(
        return_value={
            "user": {
                "profile": {
                    "display_name": "",
                    "real_name": "Real Name",
                }
            }
        }
    )

    display_name = await channel._get_user_display_name("U789")

    assert display_name == "Real Name"


@pytest.mark.asyncio
async def test_get_user_display_name_fallback_to_user_id() -> None:
    """Test that user_id is used when API fails."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    channel._app = AsyncMock()
    channel._app.client.users_info = AsyncMock(side_effect=Exception("API error"))

    display_name = await channel._get_user_display_name("U999")

    # Should fall back to user_id
    assert display_name == "U999"


@pytest.mark.asyncio
async def test_get_user_display_name_no_app() -> None:
    """Test that user_id is returned when app is not initialized."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )
    # _app is None (not started)

    display_name = await channel._get_user_display_name("U111")

    assert display_name == "U111"


# Additional edge case tests


@pytest.mark.asyncio
async def test_handle_message_event_ignores_bot_messages() -> None:
    """Test that bot's own messages are ignored."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )
    channel._bot_user_id = "UBOT"

    callback_invoked = False

    async def mock_callback(msg):
        nonlocal callback_invoked
        callback_invoked = True

    channel.on_message(mock_callback)

    event = {
        "channel": "D456",
        "user": "UBOT",  # Bot's own message
        "text": "Hello",
        "ts": "1234567890.123456",
    }

    await channel._handle_message_event(event, None)

    assert callback_invoked is False


@pytest.mark.asyncio
async def test_handle_message_event_ignores_subtypes() -> None:
    """Test that message subtypes (except file_share) are ignored."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )

    callback_invoked = False

    async def mock_callback(msg):
        nonlocal callback_invoked
        callback_invoked = True

    channel.on_message(mock_callback)

    event = {
        "channel": "D456",
        "user": "U123",
        "text": "Hello",
        "ts": "1234567890.123456",
        "subtype": "message_changed",  # Edit subtype
    }

    await channel._handle_message_event(event, None)

    # Should be ignored
    assert callback_invoked is False


@pytest.mark.asyncio
async def test_handle_message_event_processes_file_share() -> None:
    """Test that file_share subtype is processed."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )
    channel._bot_user_id = "UBOT"

    callback_invoked = False

    async def mock_callback(msg):
        nonlocal callback_invoked
        callback_invoked = True

    channel.on_message(mock_callback)

    event = {
        "channel": "D456",
        "user": "U123",
        "text": "",
        "ts": "1234567890.123456",
        "subtype": "file_share",
        "files": [],
    }

    await channel._handle_message_event(event, None)

    # Should be processed
    assert callback_invoked is True


@pytest.mark.asyncio
async def test_build_session_key() -> None:
    """Test build_session_key format."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    session_key = channel.build_session_key("C123")
    assert session_key == "slack:C123"

    session_key = channel.build_session_key("D456", "extra")
    assert session_key == "slack:D456:extra"


@pytest.mark.asyncio
async def test_register_commands_no_op() -> None:
    """Test that register_commands is a no-op."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
    )

    # Should not raise
    await channel.register_commands([])


@pytest.mark.asyncio
async def test_event_to_message_with_files() -> None:
    """Test that files in event are downloaded as attachments."""
    channel = SlackChannel(
        bot_token="xoxb-test",
        app_token="xapp-test",
        allowed_users=["U123"],
    )

    file_bytes = b"file content"

    with patch.object(channel, "_download_file", return_value=AsyncMock()) as mock_download:
        mock_download.return_value = MagicMock(
            type="document",
            data=file_bytes,
            filename="test.pdf",
            mime_type="application/pdf",
        )

        event = {
            "channel": "C456",
            "user": "U123",
            "text": "File attached",
            "ts": "1234567890.123456",
            "files": [
                {
                    "id": "F123",
                    "name": "test.pdf",
                    "mimetype": "application/pdf",
                    "url_private": "https://files.slack.com/test.pdf",
                }
            ],
        }

        message = await channel._event_to_message(event, "File attached")

        assert message is not None
        assert len(message.attachments) == 1
        mock_download.assert_called_once()
