"""Tests for shared channel helpers.

Covers the extracted pure functions and SecurityMixin that are shared
across Discord, Telegram, and future channel adapters.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.helpers import (
    SecurityMixin,
    check_file_size,
    format_approval_message,
    format_unauthorized_response,
    map_mime_type_to_attachment_type,
    split_message,
)
from openpaw.model.message import Message

# ---------------------------------------------------------------------------
# split_message
# ---------------------------------------------------------------------------


class TestSplitMessage:
    """Test the shared split_message helper."""

    def test_short_message_returns_single_chunk(self) -> None:
        text = "Short message."
        result = split_message(text, 2000)
        assert result == ["Short message."]

    def test_exact_limit_no_split(self) -> None:
        text = "x" * 2000
        result = split_message(text, 2000)
        assert len(result) == 1
        assert len(result[0]) == 2000

    def test_split_at_paragraph_boundary(self) -> None:
        part_a = "A" * 1900 + "\n\n"
        part_b = "B" * 200
        text = part_a + part_b
        result = split_message(text, 2000)
        assert len(result) == 2
        assert result[0] == "A" * 1900
        assert result[1] == "B" * 200

    def test_split_at_newline_when_no_paragraph_break(self) -> None:
        part_a = "A" * 1990 + "\n"
        part_b = "B" * 100
        text = part_a + part_b
        result = split_message(text, 2000)
        assert len(result) == 2
        assert result[0] == "A" * 1990
        assert result[1] == "B" * 100

    def test_hard_split_when_no_newlines(self) -> None:
        text = "X" * 2500
        result = split_message(text, 2000)
        assert len(result) == 2
        assert len(result[0]) == 2000
        assert result[1] == "X" * 500

    def test_very_long_message_produces_multiple_chunks(self) -> None:
        text = "Z" * 5001
        result = split_message(text, 2000)
        assert len(result) == 3
        assert all(len(chunk) <= 2000 for chunk in result)
        assert "".join(result) == text

    def test_empty_string_returns_single_empty_chunk(self) -> None:
        result = split_message("", 2000)
        assert result == [""]

    def test_split_preserves_all_content(self) -> None:
        text = "Hello world\n\n" * 200
        result = split_message(text, 2000)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 2000

    def test_different_max_lengths(self) -> None:
        """Works with different max_length values (e.g., Telegram 4096)."""
        text = "A" * 5000
        result = split_message(text, 4096)
        assert len(result) == 2
        assert len(result[0]) == 4096
        assert len(result[1]) == 904


# ---------------------------------------------------------------------------
# format_approval_message
# ---------------------------------------------------------------------------


class TestFormatApprovalMessage:
    """Test the approval message formatter."""

    def test_basic_tool_name(self) -> None:
        result = format_approval_message("overwrite_file", {}, True)
        assert "overwrite_file" in result
        assert "Approval Required" in result

    def test_escapes_backticks(self) -> None:
        result = format_approval_message("`dangerous`", {}, True)
        assert "'dangerous'" in result
        assert "`dangerous`" not in result

    def test_shows_args_when_configured(self) -> None:
        result = format_approval_message("write_file", {"path": "/tmp/test"}, True)
        assert "path" in result
        assert "/tmp/test" in result

    def test_hides_args_when_show_args_false(self) -> None:
        result = format_approval_message("write_file", {"path": "/tmp/test"}, False)
        assert "path" not in result

    def test_truncates_long_args(self) -> None:
        long_args = {"data": "x" * 1000}
        result = format_approval_message("write_file", long_args, True)
        assert "..." in result

    def test_empty_args_no_args_section(self) -> None:
        result = format_approval_message("write_file", {}, True)
        assert "Args:" not in result


# ---------------------------------------------------------------------------
# format_unauthorized_response
# ---------------------------------------------------------------------------


class TestFormatUnauthorizedResponse:
    """Test the unauthorized response formatter."""

    def test_includes_user_id(self) -> None:
        result = format_unauthorized_response(12345, "test_ws")
        assert "12345" in result

    def test_includes_workspace_name(self) -> None:
        result = format_unauthorized_response(12345, "my_workspace")
        assert "my_workspace" in result

    def test_includes_group_id_when_provided(self) -> None:
        result = format_unauthorized_response(12345, "test_ws", group_id=999)
        assert "999" in result

    def test_omits_group_id_when_none(self) -> None:
        result = format_unauthorized_response(12345, "test_ws")
        assert "Group ID" not in result

    def test_includes_yaml_config_example(self) -> None:
        result = format_unauthorized_response(12345, "test_ws")
        assert "```yaml" in result
        assert "allowed_users:" in result
        assert "- 12345" in result

    def test_includes_access_denied_emoji(self) -> None:
        result = format_unauthorized_response(12345, "test_ws")
        assert "⛔" in result


# ---------------------------------------------------------------------------
# map_mime_type_to_attachment_type
# ---------------------------------------------------------------------------


class TestMapMimeTypeToAttachmentType:
    """Test MIME type to attachment category mapping."""

    def test_audio_mime_type(self) -> None:
        assert map_mime_type_to_attachment_type("audio/ogg") == "audio"
        assert map_mime_type_to_attachment_type("audio/mpeg") == "audio"

    def test_image_mime_type(self) -> None:
        assert map_mime_type_to_attachment_type("image/png") == "image"
        assert map_mime_type_to_attachment_type("image/jpeg") == "image"

    def test_document_mime_types(self) -> None:
        assert map_mime_type_to_attachment_type("application/pdf") == "document"
        assert map_mime_type_to_attachment_type("text/plain") == "document"
        assert map_mime_type_to_attachment_type("application/octet-stream") == "document"

    def test_none_defaults_to_document(self) -> None:
        assert map_mime_type_to_attachment_type(None) == "document"


# ---------------------------------------------------------------------------
# check_file_size
# ---------------------------------------------------------------------------


class TestCheckFileSize:
    """Test the file size guard."""

    def test_small_file_passes(self) -> None:
        check_file_size(b"small", 1024, "TestPlatform")

    def test_exact_limit_passes(self) -> None:
        check_file_size(b"x" * 1024, 1024, "TestPlatform")

    def test_oversized_file_raises(self) -> None:
        with pytest.raises(ValueError, match="TestPlatform"):
            check_file_size(b"x" * 1025, 1024, "TestPlatform")

    def test_error_includes_size_mb(self) -> None:
        with pytest.raises(ValueError, match="1.0 MB"):
            check_file_size(b"x" * (1024 * 1024 + 1), 1024 * 1024, "Discord")


# ---------------------------------------------------------------------------
# SecurityMixin
# ---------------------------------------------------------------------------


class _TestChannel(ChannelAdapter, SecurityMixin):
    """Minimal concrete implementation for testing SecurityMixin in isolation."""

    name = "test"

    def __init__(
        self,
        allowed_users: set[int] | None = None,
        allowed_groups: set[int] | None = None,
        allow_all: bool = False,
        mention_required: bool = False,
        triggers: list[str] | None = None,
        workspace_name: str = "test",
    ) -> None:
        self.allowed_users = allowed_users or set()
        self.allowed_groups = allowed_groups or set()
        self.allow_all = allow_all
        self.mention_required = mention_required
        self.triggers = triggers or []
        self.workspace_name = workspace_name

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        raise NotImplementedError

    def on_message(self, callback: Any) -> None:
        pass


class TestSecurityMixinAllowlist:
    """Test SecurityMixin allowlist enforcement."""

    def test_allow_all_permits_any_user(self) -> None:
        channel = _TestChannel(allow_all=True)
        assert channel._check_user_allowed(99999) is True

    def test_allow_all_overrides_empty_list(self) -> None:
        channel = _TestChannel(allow_all=True, allowed_users=set())
        assert channel._check_user_allowed(12345) is True

    def test_allowed_user_permitted(self) -> None:
        channel = _TestChannel(allowed_users={111, 222})
        assert channel._check_user_allowed(111) is True

    def test_disallowed_user_blocked(self) -> None:
        channel = _TestChannel(allowed_users={111})
        assert channel._check_user_allowed(999) is False

    def test_empty_allowlist_denies_all(self) -> None:
        channel = _TestChannel(allowed_users=set(), allow_all=False)
        assert channel._check_user_allowed(111) is False

    def test_allowed_group_permits_any_user(self) -> None:
        channel = _TestChannel(allowed_users={111}, allowed_groups={500})
        assert channel._check_user_allowed(999, group_id=500) is True

    def test_allowed_user_in_non_allowed_group(self) -> None:
        channel = _TestChannel(allowed_users={111}, allowed_groups={500})
        assert channel._check_user_allowed(111, group_id=999) is True

    def test_unknown_user_in_non_allowed_group_denied(self) -> None:
        channel = _TestChannel(allowed_users={111}, allowed_groups={500})
        assert channel._check_user_allowed(999, group_id=999) is False

    def test_no_group_allowlist_ignores_group(self) -> None:
        channel = _TestChannel(allowed_users={111}, allowed_groups=set())
        assert channel._check_user_allowed(111, group_id=12345) is True

    def test_only_group_allowlist_dm_denied(self) -> None:
        channel = _TestChannel(allowed_users=set(), allowed_groups={500})
        assert channel._check_user_allowed(999, group_id=None) is False

    def test_only_group_allowlist_no_user_allowlist(self) -> None:
        channel = _TestChannel(allowed_users=set(), allowed_groups={500})
        assert channel._check_user_allowed(999, group_id=500) is True


class TestSecurityMixinActivation:
    """Test SecurityMixin activation filtering."""

    def test_no_filters_passes_all(self) -> None:
        channel = _TestChannel(mention_required=False, triggers=[])
        assert channel._check_activation("hello", is_dm=False, is_command=False, is_mentioned=False) is True

    def test_dm_always_passes(self) -> None:
        channel = _TestChannel(triggers=["!ask"])
        assert channel._check_activation("hello", is_dm=True, is_command=False, is_mentioned=False) is True

    def test_command_always_passes(self) -> None:
        channel = _TestChannel(triggers=["!ask"])
        assert channel._check_activation("hello", is_dm=False, is_command=True, is_mentioned=False) is True

    def test_trigger_match(self) -> None:
        channel = _TestChannel(triggers=["!ask"])
        assert channel._check_activation("!ask for help", is_dm=False, is_command=False, is_mentioned=False) is True

    def test_trigger_no_match(self) -> None:
        channel = _TestChannel(triggers=["!ask"])
        assert channel._check_activation("hello there", is_dm=False, is_command=False, is_mentioned=False) is False

    def test_mention_required_with_mention(self) -> None:
        channel = _TestChannel(mention_required=True)
        assert channel._check_activation("hey", is_dm=False, is_command=False, is_mentioned=True) is True

    def test_mention_required_without_mention(self) -> None:
        channel = _TestChannel(mention_required=True)
        assert channel._check_activation("hey", is_dm=False, is_command=False, is_mentioned=False) is False

    def test_mention_or_trigger_trigger_wins(self) -> None:
        channel = _TestChannel(mention_required=True, triggers=["!ask"])
        assert channel._check_activation("!ask", is_dm=False, is_command=False, is_mentioned=False) is True

    def test_mention_or_trigger_mention_wins(self) -> None:
        channel = _TestChannel(mention_required=True, triggers=["!ask"])
        assert channel._check_activation("hey", is_dm=False, is_command=False, is_mentioned=True) is True

    def test_mention_or_trigger_neither(self) -> None:
        channel = _TestChannel(mention_required=True, triggers=["!ask"])
        assert channel._check_activation("hey", is_dm=False, is_command=False, is_mentioned=False) is False

    def test_case_insensitive_trigger(self) -> None:
        channel = _TestChannel(triggers=["!Ask"])
        assert channel._check_activation("!ask", is_dm=False, is_command=False, is_mentioned=False) is True


class TestSecurityMixinUnauthorizedText:
    """Test SecurityMixin unauthorized text building."""

    def test_builds_text_with_workspace(self) -> None:
        channel = _TestChannel(workspace_name="my_agent")
        text = channel._build_unauthorized_text(12345)
        assert "my_agent" in text
        assert "12345" in text

    def test_includes_group_id(self) -> None:
        channel = _TestChannel(workspace_name="test")
        text = channel._build_unauthorized_text(12345, group_id=999)
        assert "999" in text


# ---------------------------------------------------------------------------
# Integration: Discord and Telegram use SecurityMixin
# ---------------------------------------------------------------------------


class TestMixinIntegration:
    """Verify that Discord and Telegram actually inherit from SecurityMixin."""

    def test_discord_inherits_security_mixin(self) -> None:
        from openpaw.channels.discord import DiscordChannel
        assert issubclass(DiscordChannel, SecurityMixin)

    def test_telegram_inherits_security_mixin(self) -> None:
        from openpaw.channels.telegram import TelegramChannel
        assert issubclass(TelegramChannel, SecurityMixin)

    def test_discord_delegates_to_mixin(self) -> None:
        from openpaw.channels.discord import DiscordChannel

        channel = DiscordChannel(token="test", allowed_users=[111])
        msg = MagicMock()
        msg.author.id = 111
        msg.guild = None
        assert channel._is_allowed(msg) is True

    def test_telegram_delegates_to_mixin(self) -> None:
        from openpaw.channels.telegram import TelegramChannel

        channel = TelegramChannel(token="test", allowed_users=[111])
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 111
        update.effective_chat = None
        assert channel._is_allowed(update) is True
