"""Unit tests for extracted workspace processors.

These tests exercise the new focused processor classes directly,
complementing the existing integration tests that call them through
MessageProcessor backward-compatible wrappers.
"""

import logging
from datetime import UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.core.config.models import AutoCompactConfig, LifecycleConfig
from openpaw.model.message import Message
from openpaw.runtime.session.manager import SessionManager
from openpaw.workspace.processors.combiner import ContentCombiner
from openpaw.workspace.processors.compactor import AutoCompactor
from openpaw.workspace.processors.response_handler import ResponseHandler
from openpaw.workspace.processors.ttl_checker import SessionTTLChecker

# ============================================================================
# ContentCombiner
# ============================================================================


class TestContentCombiner:
    """Test ContentCombiner — pure message combining logic."""

    def test_build_combined_content_single_message(self):
        combiner = ContentCombiner()
        msg = Message(
            id="1", channel="telegram", session_key="telegram:123",
            user_id="123", content="hello",
        )
        assert combiner.build_combined_content([msg]) == "hello"

    def test_build_combined_content_with_alias(self):
        combiner = ContentCombiner(user_aliases={123: "John"})
        msg = Message(
            id="1", channel="telegram", session_key="telegram:123",
            user_id="123", content="hello",
        )
        assert combiner.build_combined_content([msg]) == "[John]: hello"

    def test_build_combined_content_multiple_messages(self):
        combiner = ContentCombiner(user_aliases={123: "John", 456: "Sarah"})
        messages = [
            Message(
                id="1", channel="telegram", session_key="telegram:123",
                user_id="123", content="hello",
            ),
            Message(
                id="2", channel="telegram", session_key="telegram:456",
                user_id="456", content="hi",
            ),
        ]
        assert combiner.build_combined_content(messages) == "[John]: hello\n[Sarah]: hi"

    def test_build_combined_content_system_no_prefix(self):
        combiner = ContentCombiner(user_aliases={123: "John"})
        messages = [
            Message(
                id="1", channel="telegram", session_key="telegram:123",
                user_id="123", content="hello",
            ),
            Message(
                id="2", channel="telegram", session_key="telegram:system",
                user_id="system", content="heartbeat",
            ),
        ]
        assert combiner.build_combined_content(messages) == "[John]: hello\nheartbeat"

    def test_build_combined_content_empty(self):
        combiner = ContentCombiner()
        assert combiner.build_combined_content([]) == ""

    def test_build_combined_content_preserves_multiline(self):
        combiner = ContentCombiner(user_aliases={123: "John"})
        msg = Message(
            id="1", channel="telegram", session_key="telegram:123",
            user_id="123", content="line1\nline2\nline3",
        )
        assert combiner.build_combined_content([msg]) == "[John]: line1\nline2\nline3"

    def test_resolve_user_name_alias(self):
        combiner = ContentCombiner(user_aliases={123: "John"})
        assert combiner.resolve_user_name("123") == "John"

    def test_resolve_user_name_first_name_fallback(self):
        combiner = ContentCombiner(user_aliases={0: "placeholder"})
        assert combiner.resolve_user_name("999", {"first_name": "Alice"}) == "Alice"

    def test_resolve_user_name_username_fallback(self):
        combiner = ContentCombiner(user_aliases={0: "placeholder"})
        assert combiner.resolve_user_name("999", {"username": "alice123"}) == "alice123"

    def test_resolve_user_name_system_returns_none(self):
        combiner = ContentCombiner(user_aliases={123: "John"})
        assert combiner.resolve_user_name("system", {"first_name": "Bot"}) is None

    def test_build_combined_content_from_tuples_messages(self):
        combiner = ContentCombiner(user_aliases={123: "John"})
        tuples = [
            ("ch1", Message(
                id="1", channel="telegram", session_key="telegram:123",
                user_id="123", content="hello",
            )),
        ]
        assert combiner.build_combined_content_from_tuples(tuples) == "[John]: hello"

    def test_build_combined_content_from_tuples_raw_strings(self):
        combiner = ContentCombiner()
        tuples = [("ch1", "raw1"), ("ch2", "raw2")]
        assert combiner.build_combined_content_from_tuples(tuples) == "raw1\nraw2"

    def test_build_combined_content_from_tuples_mixed(self):
        combiner = ContentCombiner(user_aliases={123: "John"})
        tuples = [
            ("ch1", Message(
                id="1", channel="telegram", session_key="telegram:123",
                user_id="123", content="hello",
            )),
            ("ch2", "raw notification"),
        ]
        assert combiner.build_combined_content_from_tuples(tuples) == "[John]: hello\nraw notification"

    def test_build_combined_content_from_tuples_empty(self):
        combiner = ContentCombiner()
        assert combiner.build_combined_content_from_tuples([]) == ""


# ============================================================================
# SessionTTLChecker
# ============================================================================


class TestSessionTTLCheckerIsGroupSession:
    """Test static group-session detection."""

    def test_empty_messages_returns_false(self):
        assert SessionTTLChecker.is_group_session([]) is False
        assert SessionTTLChecker.is_group_session(None) is False

    def test_telegram_private_returns_false(self):
        messages = [
            Message(
                id="1", channel="telegram", session_key="telegram:123",
                user_id="123", content="hi", metadata={"chat_type": "private"},
            ),
        ]
        assert SessionTTLChecker.is_group_session(messages) is False

    def test_telegram_supergroup_returns_true(self):
        messages = [
            Message(
                id="1", channel="telegram", session_key="telegram:-100123",
                user_id="123", content="hi", metadata={"chat_type": "supergroup"},
            ),
        ]
        assert SessionTTLChecker.is_group_session(messages) is True

    def test_telegram_group_returns_true(self):
        messages = [
            Message(
                id="1", channel="telegram", session_key="telegram:-100123",
                user_id="123", content="hi", metadata={"chat_type": "group"},
            ),
        ]
        assert SessionTTLChecker.is_group_session(messages) is True

    def test_discord_guild_returns_true(self):
        messages = [
            Message(
                id="1", channel="discord", session_key="discord:999",
                user_id="456", content="hi", metadata={"guild_id": 111222333},
            ),
        ]
        assert SessionTTLChecker.is_group_session(messages) is True

    def test_discord_dm_returns_false(self):
        messages = [
            Message(
                id="1", channel="discord", session_key="discord:999",
                user_id="456", content="hi", metadata={"guild_id": None},
            ),
        ]
        assert SessionTTLChecker.is_group_session(messages) is False


class TestSessionTTLCheckerCheck:
    """Test TTL check and rotation logic."""

    @pytest.fixture
    def mock_ttl_checker(self, tmp_path: Path):
        session_manager = SessionManager(tmp_path)
        logger = logging.getLogger("test")
        return SessionTTLChecker(
            session_manager=session_manager,
            conversation_archiver=None,
            session_ttl_minutes=60,
            lifecycle_config=None,
            logger=logger,
        )

    @pytest.mark.asyncio
    async def test_ttl_disabled_returns_none(self, mock_ttl_checker: SessionTTLChecker):
        mock_ttl_checker._session_ttl_minutes = 0
        result = await mock_ttl_checker.check(
            "telegram:1", "telegram:1:conv_old", None, None
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_dm_returns_none(self, mock_ttl_checker: SessionTTLChecker):
        messages = [
            Message(
                id="1", channel="telegram", session_key="telegram:123",
                user_id="123", content="hi", metadata={"chat_type": "private"},
            ),
        ]
        result = await mock_ttl_checker.check(
            "telegram:123", "telegram:123:conv_old", None, messages
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_not_expired_returns_none(self, mock_ttl_checker: SessionTTLChecker, tmp_path: Path):
        # Seed a recent session
        manager = SessionManager(tmp_path)
        manager.get_thread_id("telegram:1")  # creates session
        checker = SessionTTLChecker(
            session_manager=manager,
            conversation_archiver=None,
            session_ttl_minutes=60,
            lifecycle_config=None,
            logger=logging.getLogger("test"),
        )
        messages = [
            Message(
                id="1", channel="telegram", session_key="telegram:1",
                user_id="123", content="hi", metadata={"chat_type": "supergroup"},
            ),
        ]
        result = await checker.check("telegram:1", "telegram:1:conv_old", None, messages)
        assert result is None

    @pytest.mark.asyncio
    async def test_expired_rotates_conversation(self, mock_ttl_checker: SessionTTLChecker, tmp_path: Path):
        import datetime
        manager = SessionManager(tmp_path)
        manager.get_thread_id("telegram:1")
        # Backdate the session
        with manager._lock:
            manager._sessions["telegram:1"].last_active_at = (
                datetime.datetime.now(UTC) - datetime.timedelta(hours=2)
            )
        checker = SessionTTLChecker(
            session_manager=manager,
            conversation_archiver=None,
            session_ttl_minutes=60,
            lifecycle_config=None,
            logger=logging.getLogger("test"),
        )
        messages = [
            Message(
                id="1", channel="telegram", session_key="telegram:1",
                user_id="123", content="hi", metadata={"chat_type": "supergroup"},
            ),
        ]
        old_thread = manager.get_thread_id("telegram:1")
        result = await checker.check("telegram:1", old_thread, None, messages)
        assert result is not None
        assert result != old_thread

    @pytest.mark.asyncio
    async def test_expired_sends_notification(self, mock_ttl_checker: SessionTTLChecker, tmp_path: Path):
        import datetime
        manager = SessionManager(tmp_path)
        manager.get_thread_id("telegram:1")
        with manager._lock:
            manager._sessions["telegram:1"].last_active_at = (
                datetime.datetime.now(UTC) - datetime.timedelta(hours=2)
            )
        checker = SessionTTLChecker(
            session_manager=manager,
            conversation_archiver=None,
            session_ttl_minutes=60,
            lifecycle_config=LifecycleConfig(notify_session_ttl=True),
            logger=logging.getLogger("test"),
        )
        messages = [
            Message(
                id="1", channel="telegram", session_key="telegram:1",
                user_id="123", content="hi", metadata={"chat_type": "supergroup"},
            ),
        ]
        channel = AsyncMock()
        await checker.check("telegram:1", "telegram:1:conv_old", channel, messages)
        channel.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_expired_no_notification_when_disabled(self, mock_ttl_checker: SessionTTLChecker, tmp_path: Path):
        import datetime
        manager = SessionManager(tmp_path)
        manager.get_thread_id("telegram:1")
        with manager._lock:
            manager._sessions["telegram:1"].last_active_at = (
                datetime.datetime.now(UTC) - datetime.timedelta(hours=2)
            )
        checker = SessionTTLChecker(
            session_manager=manager,
            conversation_archiver=None,
            session_ttl_minutes=60,
            lifecycle_config=LifecycleConfig(notify_session_ttl=False),
            logger=logging.getLogger("test"),
        )
        messages = [
            Message(
                id="1", channel="telegram", session_key="telegram:1",
                user_id="123", content="hi", metadata={"chat_type": "supergroup"},
            ),
        ]
        channel = AsyncMock()
        await checker.check("telegram:1", "telegram:1:conv_old", channel, messages)
        channel.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_logger_override(self, mock_ttl_checker: SessionTTLChecker, tmp_path: Path):
        import datetime
        manager = SessionManager(tmp_path)
        manager.get_thread_id("telegram:1")
        with manager._lock:
            manager._sessions["telegram:1"].last_active_at = (
                datetime.datetime.now(UTC) - datetime.timedelta(hours=2)
            )
        checker = SessionTTLChecker(
            session_manager=manager,
            conversation_archiver=None,
            session_ttl_minutes=60,
            lifecycle_config=None,
            logger=logging.getLogger("test"),
        )
        messages = [
            Message(
                id="1", channel="telegram", session_key="telegram:1",
                user_id="123", content="hi", metadata={"chat_type": "supergroup"},
            ),
        ]
        mock_logger = MagicMock()
        await checker.check("telegram:1", "telegram:1:conv_old", None, messages, logger=mock_logger)
        mock_logger.info.assert_called()


# ============================================================================
# AutoCompactor
# ============================================================================


class TestAutoCompactor:
    """Test AutoCompactor — preventive and emergency compaction."""

    @pytest.fixture
    def mock_compactor(self):
        session_manager = MagicMock()
        logger = logging.getLogger("test")
        return AutoCompactor(
            session_manager=session_manager,
            conversation_archiver=AsyncMock(),
            auto_compact_config=AutoCompactConfig(enabled=True, trigger=0.8),
            lifecycle_config=None,
            logger=logger,
        )

    @pytest.mark.asyncio
    async def test_check_compact_disabled_returns_none(self, mock_compactor: AutoCompactor):
        mock_compactor._auto_compact_config = AutoCompactConfig(enabled=False)
        result = await mock_compactor.check_compact(
            "telegram:123", "telegram:123:conv_old", None, MagicMock()
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_check_compact_no_archiver_returns_none(self, mock_compactor: AutoCompactor):
        mock_compactor._conversation_archiver = None
        result = await mock_compactor.check_compact(
            "telegram:123", "telegram:123:conv_old", None, MagicMock()
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_check_compact_below_threshold_returns_none(self, mock_compactor: AutoCompactor):
        agent_runner = MagicMock()
        agent_runner.get_context_info = AsyncMock(
            return_value={"utilization": 0.5, "message_count": 50, "approximate_tokens": 100000}
        )
        result = await mock_compactor.check_compact(
            "telegram:123", "telegram:123:conv_old", None, agent_runner
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_check_compact_triggers_above_threshold(self, mock_compactor: AutoCompactor):
        agent_runner = MagicMock()
        agent_runner.get_context_info = AsyncMock(
            return_value={"utilization": 0.85, "message_count": 150, "approximate_tokens": 170000}
        )
        agent_runner.run = AsyncMock(return_value="Summary")
        agent_runner.checkpointer = MagicMock()
        mock_compactor._session_manager.new_conversation = MagicMock(return_value="conv_new")
        mock_compactor._session_manager.get_thread_id = MagicMock(return_value="telegram:123:conv_new")

        channel = AsyncMock()
        result = await mock_compactor.check_compact(
            "telegram:123", "telegram:123:conv_old", channel, agent_runner
        )

        assert result is not None
        assert "conv_new" in result
        mock_compactor._conversation_archiver.archive.assert_called_once()
        agent_runner.run.assert_called()
        channel.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_compact_error_returns_none(self, mock_compactor: AutoCompactor):
        agent_runner = MagicMock()
        agent_runner.get_context_info = AsyncMock(side_effect=Exception("db error"))
        result = await mock_compactor.check_compact(
            "telegram:123", "telegram:123:conv_old", None, agent_runner
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_recover_overflow_rotates(self, mock_compactor: AutoCompactor):
        agent_runner = MagicMock()
        agent_runner.checkpointer = MagicMock()
        mock_compactor._session_manager.new_conversation = MagicMock(return_value="conv_recovered")
        mock_compactor._session_manager.get_thread_id = MagicMock(return_value="telegram:123:conv_recovered")
        mock_compactor._lifecycle_config = MagicMock(notify_auto_compact=False)

        result = await mock_compactor.recover_overflow(
            "telegram:123", "telegram:123:conv_old", None, agent_runner
        )
        assert result is not None
        assert "conv_recovered" in result

    @pytest.mark.asyncio
    async def test_recover_overflow_notifies(self, mock_compactor: AutoCompactor):
        agent_runner = MagicMock()
        agent_runner.checkpointer = MagicMock()
        mock_compactor._session_manager.new_conversation = MagicMock(return_value="conv_recovered")
        mock_compactor._session_manager.get_thread_id = MagicMock(return_value="telegram:123:conv_recovered")
        mock_compactor._lifecycle_config = LifecycleConfig(notify_auto_compact=True)

        channel = AsyncMock()
        await mock_compactor.recover_overflow(
            "telegram:123", "telegram:123:conv_old", channel, agent_runner
        )
        channel.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_overflow_archive_failure_still_rotates(self, mock_compactor: AutoCompactor):
        mock_compactor._conversation_archiver.archive = AsyncMock(side_effect=Exception("disk full"))
        agent_runner = MagicMock()
        agent_runner.checkpointer = MagicMock()
        mock_compactor._session_manager.new_conversation = MagicMock(return_value="conv_recovered")
        mock_compactor._session_manager.get_thread_id = MagicMock(return_value="telegram:123:conv_recovered")
        mock_compactor._lifecycle_config = MagicMock(notify_auto_compact=False)

        result = await mock_compactor.recover_overflow(
            "telegram:123", "telegram:123:conv_old", None, agent_runner
        )
        assert result is not None

    def test_is_context_overflow_true(self):
        from fireworks.client.error import InvalidRequestError
        err = InvalidRequestError(
            '{"error": {"message": "The prompt is too long: 262377, model maximum context length: 262143"}}'
        )
        compactor = AutoCompactor(MagicMock(), None, None, None, logging.getLogger("test"))
        assert compactor.is_context_overflow(err) is True

    def test_is_context_overflow_false(self):
        compactor = AutoCompactor(MagicMock(), None, None, None, logging.getLogger("test"))
        assert compactor.is_context_overflow(RuntimeError("db error")) is False


# ============================================================================
# ResponseHandler
# ============================================================================


class TestResponseHandler:
    """Test ResponseHandler — response sending and ack suppression."""

    @pytest.fixture
    def mock_handler(self):
        loader = MagicMock()
        loader.get_tool_instance.return_value = None
        session_manager = MagicMock()
        logger = logging.getLogger("test")
        return ResponseHandler(
            builtin_loader=loader,
            session_manager=session_manager,
            logger=logger,
        )

    def test_is_system_event_batch_empty(self):
        assert ResponseHandler.is_system_event_batch([]) is False

    def test_is_system_event_batch_all_system(self):
        messages = [
            Message(id="1", channel="telegram", session_key="telegram:sys", user_id="system", content="cron"),
            Message(id="2", channel="telegram", session_key="telegram:sys", user_id="system", content="hb"),
        ]
        assert ResponseHandler.is_system_event_batch(messages) is True

    def test_is_system_event_batch_mixed(self):
        messages = [
            Message(id="1", channel="telegram", session_key="telegram:sys", user_id="system", content="cron"),
            Message(id="2", channel="telegram", session_key="telegram:123", user_id="123", content="hi"),
        ]
        assert ResponseHandler.is_system_event_batch(messages) is False

    def test_is_system_event_batch_all_user(self):
        messages = [
            Message(id="1", channel="telegram", session_key="telegram:123", user_id="123", content="hi"),
        ]
        assert ResponseHandler.is_system_event_batch(messages) is False

    @pytest.mark.asyncio
    async def test_send_response_normal(self, mock_handler: ResponseHandler):
        channel = AsyncMock()
        await mock_handler.send_response(
            "telegram:123", "hello response", channel,
            [Message(id="1", channel="telegram", session_key="telegram:123", user_id="123", content="hi")],
        )
        channel.send_message.assert_called_once_with("telegram:123", "hello response")
        mock_handler._session_manager.increment_message_count.assert_called_once_with("telegram:123")

    @pytest.mark.asyncio
    async def test_send_response_empty_fallback(self, mock_handler: ResponseHandler):
        channel = AsyncMock()
        await mock_handler.send_response(
            "telegram:123", "", channel,
            [Message(id="1", channel="telegram", session_key="telegram:123", user_id="123", content="hi")],
        )
        channel.send_message.assert_called_once()
        args = channel.send_message.call_args.args
        assert "empty" in args[1].lower() or "try again" in args[1].lower()

    @pytest.mark.asyncio
    async def test_send_response_no_channel(self, mock_handler: ResponseHandler):
        await mock_handler.send_response(
            "telegram:123", "hello", None,
            [Message(id="1", channel="telegram", session_key="telegram:123", user_id="123", content="hi")],
        )
        # Should not raise

    @pytest.mark.asyncio
    async def test_send_response_system_ack_suppresses(self, mock_handler: ResponseHandler):
        from openpaw.builtins.tools.acknowledge import AcknowledgeRequest

        ack_tool = MagicMock()
        ack_tool.get_pending_ack.return_value = AcknowledgeRequest(reason="routine check")
        mock_handler._builtin_loader.get_tool_instance.return_value = ack_tool

        channel = AsyncMock()
        await mock_handler.send_response(
            "telegram:sys", "system response", channel,
            [Message(id="1", channel="telegram", session_key="telegram:sys", user_id="system", content="cron")],
        )
        channel.send_message.assert_not_called()
        mock_handler._session_manager.increment_message_count.assert_called_once_with("telegram:sys")

    @pytest.mark.asyncio
    async def test_send_response_user_ack_not_suppressed(self, mock_handler: ResponseHandler):
        from openpaw.builtins.tools.acknowledge import AcknowledgeRequest

        ack_tool = MagicMock()
        ack_tool.get_pending_ack.return_value = AcknowledgeRequest(reason="routine check")
        mock_handler._builtin_loader.get_tool_instance.return_value = ack_tool

        channel = AsyncMock()
        await mock_handler.send_response(
            "telegram:123", "user response", channel,
            [Message(id="1", channel="telegram", session_key="telegram:123", user_id="123", content="hi")],
        )
        channel.send_message.assert_called_once_with("telegram:123", "user response")
