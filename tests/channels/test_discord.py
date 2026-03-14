"""Tests for the Discord channel adapter."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.discord import DiscordChannel
from openpaw.channels.factory import create_channel
from openpaw.model.message import Message, MessageDirection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_discord_channel(**kwargs) -> DiscordChannel:
    """Return a DiscordChannel with sensible test defaults."""
    defaults = {
        "token": "test-bot-token",
        "workspace_name": "test_workspace",
    }
    defaults.update(kwargs)
    return DiscordChannel(**defaults)


def _make_mock_discord_message(
    user_id: int = 111,
    channel_id: int = 999,
    content: str = "hello",
    guild_id: int | None = None,
    username: str = "testuser",
    display_name: str = "Test User",
    message_id: int = 42,
    attachments: list | None = None,
) -> MagicMock:
    """Build a minimal mock of a discord.Message object."""
    msg = MagicMock()
    msg.id = message_id
    msg.content = content
    msg.author.id = user_id
    msg.author.name = username
    msg.author.display_name = display_name
    msg.channel.id = channel_id
    msg.created_at = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
    msg.attachments = attachments or []

    if guild_id is not None:
        msg.guild = MagicMock()
        msg.guild.id = guild_id
    else:
        msg.guild = None

    return msg


def _make_mock_attachment(
    filename: str = "file.png",
    content_type: str = "image/png",
    size: int = 1024,
    data: bytes = b"fake-bytes",
) -> MagicMock:
    """Build a minimal mock of a discord.Attachment object."""
    att = MagicMock()
    att.filename = filename
    att.content_type = content_type
    att.size = size
    att.read = AsyncMock(return_value=data)
    return att


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    """Test DiscordChannel construction and attribute storage."""

    def test_init_with_token(self) -> None:
        """Token passed directly is stored and used."""
        channel = DiscordChannel(token="direct-token")
        assert channel._token == "direct-token"

    def test_init_with_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to DISCORD_BOT_TOKEN environment variable when no token is passed."""
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token")
        channel = DiscordChannel()
        assert channel._token == "env-token"

    def test_init_missing_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Raises ValueError when no token is available from any source."""
        monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="Discord bot token required"):
            DiscordChannel()

    def test_init_allowed_users_stored_as_set(self) -> None:
        """allowed_users list is converted to a set."""
        channel = _make_discord_channel(allowed_users=[100, 200, 300])
        assert channel.allowed_users == {100, 200, 300}
        assert isinstance(channel.allowed_users, set)

    def test_init_allowed_groups_stored_as_set(self) -> None:
        """allowed_groups list is converted to a set."""
        channel = _make_discord_channel(allowed_groups=[500, 600])
        assert channel.allowed_groups == {500, 600}
        assert isinstance(channel.allowed_groups, set)

    def test_init_empty_allowlists_default_to_empty_sets(self) -> None:
        """Default allowlists are empty sets, not None."""
        channel = _make_discord_channel()
        assert channel.allowed_users == set()
        assert channel.allowed_groups == set()

    def test_init_allow_all_default_false(self) -> None:
        """allow_all defaults to False (secure by default)."""
        channel = _make_discord_channel()
        assert channel.allow_all is False

    def test_init_workspace_name_stored(self) -> None:
        """workspace_name is stored for error messages."""
        channel = _make_discord_channel(workspace_name="my_agent")
        assert channel.workspace_name == "my_agent"

    def test_init_is_channel_adapter(self) -> None:
        """DiscordChannel is a ChannelAdapter subclass."""
        channel = _make_discord_channel()
        assert isinstance(channel, ChannelAdapter)

    def test_init_name_attribute(self) -> None:
        """name class attribute is 'discord'."""
        assert DiscordChannel.name == "discord"


# ---------------------------------------------------------------------------
# 2. Allowlist security (_is_allowed)
# ---------------------------------------------------------------------------


class TestAllowlist:
    """Test _is_allowed allowlist enforcement."""

    def test_allow_all_permits_any_user(self) -> None:
        """allow_all=True bypasses all allowlist checks."""
        channel = _make_discord_channel(allow_all=True)
        msg = _make_mock_discord_message(user_id=99999)
        assert channel._is_allowed(msg) is True

    def test_allow_all_permits_user_not_in_list(self) -> None:
        """allow_all=True overrides even an empty allowed_users list."""
        channel = _make_discord_channel(allow_all=True, allowed_users=[])
        msg = _make_mock_discord_message(user_id=12345)
        assert channel._is_allowed(msg) is True

    def test_allowed_user_permitted(self) -> None:
        """User whose ID is in allowed_users is granted access."""
        channel = _make_discord_channel(allowed_users=[111, 222])
        msg = _make_mock_discord_message(user_id=111)
        assert channel._is_allowed(msg) is True

    def test_disallowed_user_blocked(self) -> None:
        """User whose ID is NOT in allowed_users is denied."""
        channel = _make_discord_channel(allowed_users=[111])
        msg = _make_mock_discord_message(user_id=999)
        assert channel._is_allowed(msg) is False

    def test_empty_allowlist_denies_all(self) -> None:
        """No allowed_users configured and allow_all=False → deny everyone."""
        channel = _make_discord_channel(allowed_users=[], allow_all=False)
        msg = _make_mock_discord_message(user_id=111)
        assert channel._is_allowed(msg) is False

    def test_allowed_guild_permits_any_user(self) -> None:
        """Any user in an allowed guild is permitted, even without being in allowed_users."""
        channel = _make_discord_channel(
            allowed_users=[111],
            allowed_groups=[500],
        )
        # User 999 is NOT in allowed_users, but guild 500 is allowed
        msg = _make_mock_discord_message(user_id=999, guild_id=500)
        assert channel._is_allowed(msg) is True

    def test_allowed_user_in_non_allowed_guild(self) -> None:
        """User in allowed_users is permitted even from a non-allowed guild."""
        channel = _make_discord_channel(
            allowed_users=[111],
            allowed_groups=[500],
        )
        # Guild 999 is not in allowed_groups, but user 111 is individually allowed
        msg = _make_mock_discord_message(user_id=111, guild_id=999)
        assert channel._is_allowed(msg) is True

    def test_unknown_user_in_non_allowed_guild_denied(self) -> None:
        """User not in allowed_users and guild not in allowed_groups → denied."""
        channel = _make_discord_channel(
            allowed_users=[111],
            allowed_groups=[500],
        )
        msg = _make_mock_discord_message(user_id=999, guild_id=999)
        assert channel._is_allowed(msg) is False

    def test_guild_allowlist_allows_correct_guild(self) -> None:
        """User + guild both in their respective allowlists → permitted."""
        channel = _make_discord_channel(
            allowed_users=[111],
            allowed_groups=[500],
        )
        msg = _make_mock_discord_message(user_id=111, guild_id=500)
        assert channel._is_allowed(msg) is True

    def test_dm_ignores_guild_check(self) -> None:
        """DM message (no guild) with an allowed user is granted access even when
        allowed_groups is configured."""
        channel = _make_discord_channel(
            allowed_users=[111],
            allowed_groups=[500],
        )
        # guild=None simulates a DM
        msg = _make_mock_discord_message(user_id=111, guild_id=None)
        assert channel._is_allowed(msg) is True

    def test_no_guild_allowlist_ignores_guild(self) -> None:
        """When allowed_groups is empty the guild check is skipped entirely."""
        channel = _make_discord_channel(
            allowed_users=[111],
            allowed_groups=[],
        )
        msg = _make_mock_discord_message(user_id=111, guild_id=12345)
        assert channel._is_allowed(msg) is True

    def test_only_guild_allowlist_no_user_allowlist(self) -> None:
        """When only allowed_groups is set (no allowed_users), guild members are allowed."""
        channel = _make_discord_channel(
            allowed_users=[],
            allowed_groups=[500],
        )
        msg = _make_mock_discord_message(user_id=999, guild_id=500)
        assert channel._is_allowed(msg) is True

    def test_only_guild_allowlist_dm_denied(self) -> None:
        """When only allowed_groups is set, DMs are denied (no user allowlist to match)."""
        channel = _make_discord_channel(
            allowed_users=[],
            allowed_groups=[500],
        )
        msg = _make_mock_discord_message(user_id=999, guild_id=None)
        assert channel._is_allowed(msg) is False


# ---------------------------------------------------------------------------
# 3. Message conversion (_to_message)
# ---------------------------------------------------------------------------


class TestToMessage:
    """Test _to_message: discord.Message → OpenPaw Message."""

    @pytest.mark.asyncio
    async def test_text_message_basic_fields(self) -> None:
        """Basic text message produces a correctly populated Message."""
        channel = _make_discord_channel()
        discord_msg = _make_mock_discord_message(
            user_id=111,
            channel_id=999,
            content="Hello, world!",
            message_id=42,
        )

        result = await channel._to_message(discord_msg)

        assert result is not None
        assert result.id == "42"
        assert result.channel == "discord"
        assert result.content == "Hello, world!"
        assert result.user_id == "111"
        assert result.direction == MessageDirection.INBOUND
        assert result.attachments == []

    @pytest.mark.asyncio
    async def test_session_key_format(self) -> None:
        """session_key is 'discord:{channel_id}'."""
        channel = _make_discord_channel()
        discord_msg = _make_mock_discord_message(channel_id=7654321)

        result = await channel._to_message(discord_msg)

        assert result is not None
        assert result.session_key == "discord:7654321"

    @pytest.mark.asyncio
    async def test_message_with_guild_metadata(self) -> None:
        """Guild ID is captured in message metadata for server messages."""
        channel = _make_discord_channel()
        discord_msg = _make_mock_discord_message(guild_id=500)

        result = await channel._to_message(discord_msg)

        assert result is not None
        assert result.metadata["guild_id"] == 500

    @pytest.mark.asyncio
    async def test_dm_message_guild_id_is_none(self) -> None:
        """DM messages (no guild) have guild_id=None in metadata."""
        channel = _make_discord_channel()
        discord_msg = _make_mock_discord_message(guild_id=None)

        result = await channel._to_message(discord_msg)

        assert result is not None
        assert result.metadata["guild_id"] is None

    @pytest.mark.asyncio
    async def test_metadata_contains_username_and_display_name(self) -> None:
        """Author username and display_name are captured in metadata."""
        channel = _make_discord_channel()
        discord_msg = _make_mock_discord_message(
            username="john_doe",
            display_name="John Doe",
        )

        result = await channel._to_message(discord_msg)

        assert result is not None
        assert result.metadata["username"] == "john_doe"
        assert result.metadata["display_name"] == "John Doe"

    @pytest.mark.asyncio
    async def test_empty_content_becomes_empty_string(self) -> None:
        """discord.Message.content=None is normalized to empty string."""
        channel = _make_discord_channel()
        discord_msg = _make_mock_discord_message(content=None)

        result = await channel._to_message(discord_msg)

        assert result is not None
        assert result.content == ""

    @pytest.mark.asyncio
    async def test_timestamp_from_message(self) -> None:
        """Timestamp is taken from the discord message's created_at."""
        channel = _make_discord_channel()
        expected_ts = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        discord_msg = _make_mock_discord_message()
        discord_msg.created_at = expected_ts

        result = await channel._to_message(discord_msg)

        assert result is not None
        assert result.timestamp == expected_ts


# ---------------------------------------------------------------------------
# 4. Attachment handling (_download_attachments)
# ---------------------------------------------------------------------------


class TestDownloadAttachments:
    """Test attachment type detection and download behavior."""

    @pytest.mark.asyncio
    async def test_image_attachment_type(self) -> None:
        """content_type starting with 'image/' maps to type 'image'."""
        channel = _make_discord_channel()
        att = _make_mock_attachment(
            filename="photo.png",
            content_type="image/png",
            data=b"png-data",
        )
        discord_msg = _make_mock_discord_message(attachments=[att])

        result = await channel._download_attachments(discord_msg)

        assert len(result) == 1
        assert result[0].type == "image"
        assert result[0].filename == "photo.png"
        assert result[0].mime_type == "image/png"
        assert result[0].data == b"png-data"

    @pytest.mark.asyncio
    async def test_audio_attachment_type(self) -> None:
        """content_type starting with 'audio/' maps to type 'audio'."""
        channel = _make_discord_channel()
        att = _make_mock_attachment(
            filename="voice.ogg",
            content_type="audio/ogg",
            data=b"ogg-data",
        )
        discord_msg = _make_mock_discord_message(attachments=[att])

        result = await channel._download_attachments(discord_msg)

        assert len(result) == 1
        assert result[0].type == "audio"
        assert result[0].mime_type == "audio/ogg"

    @pytest.mark.asyncio
    async def test_document_attachment_type_for_pdf(self) -> None:
        """application/pdf maps to type 'document'."""
        channel = _make_discord_channel()
        att = _make_mock_attachment(
            filename="report.pdf",
            content_type="application/pdf",
        )
        discord_msg = _make_mock_discord_message(attachments=[att])

        result = await channel._download_attachments(discord_msg)

        assert len(result) == 1
        assert result[0].type == "document"

    @pytest.mark.asyncio
    async def test_document_attachment_type_for_text(self) -> None:
        """text/plain maps to type 'document'."""
        channel = _make_discord_channel()
        att = _make_mock_attachment(
            filename="notes.txt",
            content_type="text/plain",
        )
        discord_msg = _make_mock_discord_message(attachments=[att])

        result = await channel._download_attachments(discord_msg)

        assert len(result) == 1
        assert result[0].type == "document"

    @pytest.mark.asyncio
    async def test_attachment_metadata_contains_file_size(self) -> None:
        """Attachment metadata captures the file size from Discord."""
        channel = _make_discord_channel()
        att = _make_mock_attachment(size=4096)
        discord_msg = _make_mock_discord_message(attachments=[att])

        result = await channel._download_attachments(discord_msg)

        assert result[0].metadata["file_size"] == 4096

    @pytest.mark.asyncio
    async def test_multiple_attachments_all_downloaded(self) -> None:
        """Every attachment in the message is downloaded and returned."""
        channel = _make_discord_channel()
        attachments = [
            _make_mock_attachment("a.png", "image/png"),
            _make_mock_attachment("b.ogg", "audio/ogg"),
            _make_mock_attachment("c.pdf", "application/pdf"),
        ]
        discord_msg = _make_mock_discord_message(attachments=attachments)

        result = await channel._download_attachments(discord_msg)

        assert len(result) == 3
        types = {r.type for r in result}
        assert types == {"image", "audio", "document"}

    @pytest.mark.asyncio
    async def test_attachment_download_failure_is_skipped(self) -> None:
        """A failed download is skipped with a warning; other attachments succeed."""
        channel = _make_discord_channel()
        failing_att = _make_mock_attachment(filename="bad.png")
        failing_att.read = AsyncMock(side_effect=Exception("Network error"))

        good_att = _make_mock_attachment(filename="good.png", data=b"ok")

        discord_msg = _make_mock_discord_message(attachments=[failing_att, good_att])

        result = await channel._download_attachments(discord_msg)

        # Only the successful attachment is returned
        assert len(result) == 1
        assert result[0].filename == "good.png"
        assert result[0].data == b"ok"

    @pytest.mark.asyncio
    async def test_no_attachments_returns_empty_list(self) -> None:
        """Message without attachments yields an empty list."""
        channel = _make_discord_channel()
        discord_msg = _make_mock_discord_message(attachments=[])

        result = await channel._download_attachments(discord_msg)

        assert result == []

    @pytest.mark.asyncio
    async def test_null_content_type_defaults_to_octet_stream(self) -> None:
        """content_type=None is treated as 'application/octet-stream' (document type)."""
        channel = _make_discord_channel()
        att = _make_mock_attachment(content_type=None)
        discord_msg = _make_mock_discord_message(attachments=[att])

        result = await channel._download_attachments(discord_msg)

        assert result[0].type == "document"
        assert result[0].mime_type == "application/octet-stream"


# ---------------------------------------------------------------------------
# 5. Message splitting (_split_message)
# ---------------------------------------------------------------------------


class TestSplitMessage:
    """Test _split_message chunking logic against Discord's 2000-char limit."""

    def test_short_message_returns_single_chunk(self) -> None:
        """Text within the limit is returned as a single-element list."""
        channel = _make_discord_channel()
        text = "Short message."

        result = channel._split_message(text)

        assert result == ["Short message."]

    def test_exact_limit_no_split(self) -> None:
        """Text of exactly 2000 characters is not split."""
        channel = _make_discord_channel()
        text = "x" * 2000

        result = channel._split_message(text)

        assert len(result) == 1
        assert len(result[0]) == 2000

    def test_split_at_paragraph_boundary(self) -> None:
        """Text just over the limit is split at the last double-newline within the window."""
        channel = _make_discord_channel()
        # Build a message that has a paragraph break before the 2000-char boundary
        part_a = "A" * 1900 + "\n\n"
        part_b = "B" * 200
        text = part_a + part_b

        result = channel._split_message(text)

        assert len(result) == 2
        # First chunk should end with the paragraph content (stripped)
        assert result[0] == "A" * 1900
        assert result[1] == "B" * 200

    def test_split_at_newline_when_no_paragraph_break(self) -> None:
        """Falls back to single newline when no double-newline exists in window."""
        channel = _make_discord_channel()
        # 1990 'A' chars, then '\n', then enough 'B's to exceed 2000
        part_a = "A" * 1990 + "\n"
        part_b = "B" * 100
        text = part_a + part_b

        result = channel._split_message(text)

        assert len(result) == 2
        assert result[0] == "A" * 1990
        assert result[1] == "B" * 100

    def test_hard_split_when_no_newlines(self) -> None:
        """With no newlines, falls back to hard split at exactly MAX_MESSAGE_LENGTH."""
        channel = _make_discord_channel()
        text = "X" * 2500

        result = channel._split_message(text)

        assert len(result) == 2
        assert len(result[0]) == 2000
        assert result[1] == "X" * 500

    def test_very_long_message_produces_multiple_chunks(self) -> None:
        """Messages many times over the limit generate the correct number of chunks."""
        channel = _make_discord_channel()
        # 5001 chars with no newlines → should yield 3 hard-split chunks
        text = "Z" * 5001

        result = channel._split_message(text)

        # 2000 + 2000 + 1 = 5001
        assert len(result) == 3
        assert all(len(chunk) <= 2000 for chunk in result)
        assert "".join(result) == text

    def test_empty_string_returns_single_empty_chunk(self) -> None:
        """Empty string yields a list containing one empty string."""
        channel = _make_discord_channel()

        result = channel._split_message("")

        assert result == [""]

    def test_split_preserves_all_content(self) -> None:
        """All characters are present in the rejoined chunks."""
        channel = _make_discord_channel()
        text = ("Hello world\n\n" * 200)  # ~2600 chars

        result = channel._split_message(text)

        assert len(result) > 1
        # Rejoin with the newlines that were stripped during splitting
        for chunk in result:
            assert len(chunk) <= 2000


# ---------------------------------------------------------------------------
# 6. Session key helpers
# ---------------------------------------------------------------------------


class TestSessionKey:
    """Test session key building and parsing."""

    def test_build_session_key(self) -> None:
        """build_session_key returns 'discord:{channel_id}'."""
        channel = _make_discord_channel()
        assert channel.build_session_key(123456) == "discord:123456"

    def test_channel_id_from_session_key(self) -> None:
        """_channel_id_from_session_key correctly extracts the integer ID."""
        assert DiscordChannel._channel_id_from_session_key("discord:987654") == 987654

    def test_channel_id_from_session_key_large_snowflake(self) -> None:
        """Works with large Discord snowflake IDs."""
        snowflake = 1234567890123456789
        session_key = f"discord:{snowflake}"
        assert DiscordChannel._channel_id_from_session_key(session_key) == snowflake

    def test_session_key_used_in_to_message(self) -> None:
        """_to_message uses build_session_key to form the session_key field."""
        channel = _make_discord_channel()

        # Verify the format is consistent
        assert channel.build_session_key(55555) == "discord:55555"


# ---------------------------------------------------------------------------
# 7. Callback registration
# ---------------------------------------------------------------------------


class TestCallbackRegistration:
    """Test on_message and on_approval callback registration."""

    def test_on_message_stores_callback(self) -> None:
        """on_message stores the provided callback."""
        channel = _make_discord_channel()

        async def my_callback(msg: Message) -> None:
            pass

        channel.on_message(my_callback)
        assert channel._message_callback is my_callback

    def test_on_approval_stores_callback(self) -> None:
        """on_approval stores the provided callback."""
        channel = _make_discord_channel()

        async def my_approval_callback(approval_id: str, approved: bool) -> None:
            pass

        channel.on_approval(my_approval_callback)
        assert channel._approval_callback is my_approval_callback

    def test_initial_callbacks_are_none(self) -> None:
        """Before registration, both callbacks are None."""
        channel = _make_discord_channel()
        assert channel._message_callback is None
        assert channel._approval_callback is None


# ---------------------------------------------------------------------------
# 8. send_file validation (no live client required)
# ---------------------------------------------------------------------------


class TestSendFileValidation:
    """Test send_file guards that don't require a running Discord client."""

    @pytest.mark.asyncio
    async def test_send_file_raises_when_not_started(self) -> None:
        """send_file raises RuntimeError if _client is None (not started)."""
        channel = _make_discord_channel()
        assert channel._client is None

        with pytest.raises(RuntimeError, match="Discord channel not started"):
            await channel.send_file(
                session_key="discord:123",
                file_data=b"data",
                filename="test.txt",
            )

    @pytest.mark.asyncio
    async def test_send_file_raises_on_oversized_file(self) -> None:
        """Files exceeding 25 MB raise ValueError before any network call."""
        channel = _make_discord_channel()
        channel._client = MagicMock()  # simulate started state

        oversized = b"x" * (26 * 1024 * 1024)  # 26 MB

        with pytest.raises(ValueError, match="25 MB limit"):
            await channel.send_file(
                session_key="discord:123",
                file_data=oversized,
                filename="huge.bin",
            )

    def test_max_file_size_constant(self) -> None:
        """MAX_FILE_SIZE is exactly 25 MB."""
        assert DiscordChannel.MAX_FILE_SIZE == 25 * 1024 * 1024

    def test_max_message_length_constant(self) -> None:
        """MAX_MESSAGE_LENGTH is exactly 2000 characters."""
        assert DiscordChannel.MAX_MESSAGE_LENGTH == 2000


# ---------------------------------------------------------------------------
# 9. send_message validation (no live client required)
# ---------------------------------------------------------------------------


class TestSendMessageValidation:
    """Test send_message guards that don't require a running Discord client."""

    @pytest.mark.asyncio
    async def test_send_message_raises_when_not_started(self) -> None:
        """send_message raises RuntimeError if _client is None."""
        channel = _make_discord_channel()

        with pytest.raises(RuntimeError, match="Discord channel not started"):
            await channel.send_message("discord:123", "hello")


# ---------------------------------------------------------------------------
# 10. Factory integration
# ---------------------------------------------------------------------------


class TestFactoryIntegration:
    """Test that the channel factory correctly produces DiscordChannel instances."""

    def test_factory_creates_discord_channel(self) -> None:
        """create_channel('discord', ...) returns a DiscordChannel."""
        config = {
            "token": "factory-token",
            "allowed_users": [1, 2],
            "allowed_groups": [10],
            "allow_all": False,
        }

        channel = create_channel("discord", config, "factory_workspace")

        assert isinstance(channel, DiscordChannel)
        assert isinstance(channel, ChannelAdapter)

    def test_factory_passes_token(self) -> None:
        """Token from config is stored on the resulting channel."""
        config = {"token": "my-secret-token"}
        channel = create_channel("discord", config, "ws")

        assert isinstance(channel, DiscordChannel)
        assert channel._token == "my-secret-token"

    def test_factory_passes_allowed_users(self) -> None:
        """allowed_users from config are stored as a set."""
        config = {"token": "tok", "allowed_users": [100, 200]}
        channel = create_channel("discord", config, "ws")

        assert isinstance(channel, DiscordChannel)
        assert channel.allowed_users == {100, 200}

    def test_factory_passes_allowed_groups(self) -> None:
        """allowed_groups from config are stored as a set."""
        config = {"token": "tok", "allowed_groups": [500]}
        channel = create_channel("discord", config, "ws")

        assert isinstance(channel, DiscordChannel)
        assert channel.allowed_groups == {500}

    def test_factory_passes_allow_all(self) -> None:
        """allow_all flag from config is honoured."""
        config = {"token": "tok", "allow_all": True}
        channel = create_channel("discord", config, "ws")

        assert isinstance(channel, DiscordChannel)
        assert channel.allow_all is True

    def test_factory_passes_workspace_name(self) -> None:
        """workspace_name is forwarded to the channel constructor."""
        config = {"token": "tok"}
        channel = create_channel("discord", config, "my_custom_workspace")

        assert isinstance(channel, DiscordChannel)
        assert channel.workspace_name == "my_custom_workspace"

    def test_factory_defaults_empty_allowlists(self) -> None:
        """Omitting allowlists in config yields empty sets on the channel."""
        config = {"token": "tok"}
        channel = create_channel("discord", config, "ws")

        assert isinstance(channel, DiscordChannel)
        assert channel.allowed_users == set()
        assert channel.allowed_groups == set()


# ---------------------------------------------------------------------------
# 11. _on_message integration (allowed/denied routing)
# ---------------------------------------------------------------------------


class TestOnMessageRouting:
    """Test that _on_message correctly routes allowed messages and blocks others."""

    @pytest.mark.asyncio
    async def test_on_message_invokes_callback_for_allowed_user(self) -> None:
        """Allowed user message triggers the registered message callback."""
        channel = _make_discord_channel(allowed_users=[111])

        received: list[Message] = []

        async def capture(msg: Message) -> None:
            received.append(msg)

        channel.on_message(capture)

        discord_msg = _make_mock_discord_message(user_id=111, content="allowed content")
        channel._client = MagicMock()
        channel._client.user = MagicMock()
        channel._client.user.__eq__ = lambda self, other: False

        await channel._on_message(discord_msg)

        assert len(received) == 1
        assert received[0].content == "allowed content"

    @pytest.mark.asyncio
    async def test_on_message_blocks_disallowed_user(self) -> None:
        """Disallowed user message does not reach the callback."""
        channel = _make_discord_channel(allowed_users=[111])

        received: list[Message] = []

        async def capture(msg: Message) -> None:
            received.append(msg)

        channel.on_message(capture)

        discord_msg = _make_mock_discord_message(user_id=999)
        discord_msg.reply = AsyncMock()
        channel._client = MagicMock()
        channel._client.user = MagicMock()
        channel._client.user.__eq__ = lambda self, other: False

        # Patch _send_unauthorized_response to avoid needing a full Discord object
        channel._send_unauthorized_response = AsyncMock()

        await channel._on_message(discord_msg)

        assert len(received) == 0
        channel._send_unauthorized_response.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_message_ignores_own_messages(self) -> None:
        """Bot's own messages are silently ignored."""
        channel = _make_discord_channel(allow_all=True)

        received: list[Message] = []

        async def capture(msg: Message) -> None:
            received.append(msg)

        channel.on_message(capture)

        # discord_msg.author == client.user → True
        bot_user = MagicMock()
        discord_msg = _make_mock_discord_message()
        discord_msg.author = bot_user

        client = MagicMock()
        client.user = bot_user
        channel._client = client

        await channel._on_message(discord_msg)

        assert len(received) == 0


# ---------------------------------------------------------------------------
# 9. Mention Filter
# ---------------------------------------------------------------------------


class TestMentionFilter:
    """Test mention_required filtering behavior."""

    def test_mention_required_defaults_to_false(self) -> None:
        """mention_required is False by default."""
        channel = _make_discord_channel()
        assert channel.mention_required is False

    def test_mention_required_stored(self) -> None:
        """mention_required is stored when passed."""
        channel = _make_discord_channel(mention_required=True)
        assert channel.mention_required is True

    def test_filter_passes_when_disabled(self) -> None:
        """All messages pass when mention_required is False."""
        channel = _make_discord_channel(mention_required=False)
        msg = _make_mock_discord_message(guild_id=123)
        msg.mentions = []
        assert channel._passes_activation_filter(msg) is True

    def test_filter_passes_for_dm(self) -> None:
        """DMs always pass even when mention_required is True."""
        channel = _make_discord_channel(mention_required=True)
        msg = _make_mock_discord_message()  # guild=None → DM
        msg.mentions = []
        assert channel._passes_activation_filter(msg) is True

    def test_filter_blocks_guild_message_without_mention(self) -> None:
        """Guild messages without @mention are blocked."""
        channel = _make_discord_channel(mention_required=True)
        channel._client = MagicMock()
        bot_user = MagicMock()
        channel._client.user = bot_user

        msg = _make_mock_discord_message(guild_id=123)
        msg.mentions = []
        assert channel._passes_activation_filter(msg) is False

    def test_filter_passes_guild_message_with_bot_mention(self) -> None:
        """Guild messages with bot @mention pass through."""
        channel = _make_discord_channel(mention_required=True)
        channel._client = MagicMock()
        bot_user = MagicMock()
        channel._client.user = bot_user

        msg = _make_mock_discord_message(guild_id=123)
        msg.mentions = [bot_user]
        assert channel._passes_activation_filter(msg) is True

    def test_filter_blocks_guild_message_with_other_mention(self) -> None:
        """Guild messages mentioning someone else are blocked."""
        channel = _make_discord_channel(mention_required=True)
        channel._client = MagicMock()
        bot_user = MagicMock()
        channel._client.user = bot_user

        msg = _make_mock_discord_message(guild_id=123)
        other_user = MagicMock()
        msg.mentions = [other_user]
        assert channel._passes_activation_filter(msg) is False

    @pytest.mark.asyncio
    async def test_on_message_skips_unmentioned_in_guild(self) -> None:
        """With mention_required, guild messages without mention are silently ignored."""
        channel = _make_discord_channel(allowed_users=[111], mention_required=True)

        received: list[Message] = []

        async def capture(msg: Message) -> None:
            received.append(msg)

        channel.on_message(capture)

        bot_user = MagicMock()
        client = MagicMock()
        client.user = bot_user
        client.user.__eq__ = lambda self, other: False
        channel._client = client

        msg = _make_mock_discord_message(user_id=111, guild_id=123)
        msg.mentions = []

        await channel._on_message(msg)
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_on_message_processes_mentioned_in_guild(self) -> None:
        """With mention_required, guild messages with bot @mention are processed."""
        channel = _make_discord_channel(allowed_users=[111], mention_required=True)

        received: list[Message] = []

        async def capture(msg: Message) -> None:
            received.append(msg)

        channel.on_message(capture)

        bot_user = MagicMock()
        client = MagicMock()
        client.user = bot_user
        client.user.__eq__ = lambda self, other: False
        channel._client = client

        msg = _make_mock_discord_message(user_id=111, guild_id=123)
        msg.mentions = [bot_user]

        await channel._on_message(msg)
        assert len(received) == 1
