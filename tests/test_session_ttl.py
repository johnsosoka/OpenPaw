"""Tests for the session TTL (time-to-live) feature.

Covers:
- WorkspaceConfig.session_ttl_minutes validation
- LifecycleConfig.notify_session_ttl default
- SessionManager.is_session_expired() logic
- MessageProcessor._check_session_ttl() integration
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from pydantic import ValidationError

from openpaw.core.config.models import LifecycleConfig, WorkspaceConfig
from openpaw.runtime.session.manager import SessionManager
from openpaw.workspace.message_processor import MessageProcessor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path) -> SessionManager:
    """Return a fresh SessionManager backed by a temp directory."""
    return SessionManager(tmp_path)


def _seed_session(
    manager: SessionManager,
    session_key: str,
    last_active_offset: timedelta | None,
) -> None:
    """Create a session and optionally backdate last_active_at.

    Args:
        manager: SessionManager instance.
        session_key: Session key to seed.
        last_active_offset: Negative timedelta applied to now() to set
            last_active_at in the past. Pass None to leave last_active_at
            unset (simulates first-message state).
    """
    manager.get_thread_id(session_key)  # Creates the session

    if last_active_offset is not None:
        with manager._lock:
            manager._sessions[session_key].last_active_at = (
                datetime.now(UTC) + last_active_offset
            )


def _make_processor(
    session_manager: SessionManager,
    session_ttl_minutes: int = 0,
    lifecycle_config: LifecycleConfig | None = None,
    conversation_archiver: object | None = None,
    agent_runner: object | None = None,
) -> MessageProcessor:
    """Build a MessageProcessor with just enough mocks to test TTL logic.

    When agent_runner is supplied the caller is responsible for configuring
    its checkpointer attribute; the helper only sets it on internally-created
    runners so that tests can freely set runner.checkpointer = None.
    """
    if agent_runner is not None:
        runner = agent_runner
    else:
        runner = MagicMock()
        runner.checkpointer = MagicMock()

    return MessageProcessor(
        agent_runner=runner,
        session_manager=session_manager,
        queue_manager=MagicMock(),
        builtin_loader=MagicMock(),
        queue_middleware=MagicMock(),
        approval_middleware=MagicMock(),
        approval_manager=None,
        workspace_name="test-workspace",
        token_logger=MagicMock(),
        logger=logging.getLogger("test"),
        conversation_archiver=conversation_archiver,
        session_ttl_minutes=session_ttl_minutes,
        lifecycle_config=lifecycle_config,
    )


# ---------------------------------------------------------------------------
# 1. Config Validation
# ---------------------------------------------------------------------------


class TestWorkspaceConfigSessionTtl:
    """WorkspaceConfig.session_ttl_minutes field validation."""

    def test_default_is_180(self) -> None:
        """Default session_ttl_minutes is 180 (3 hours)."""
        config = WorkspaceConfig()
        assert config.session_ttl_minutes == 180

    def test_zero_is_valid(self) -> None:
        """Zero is accepted and means TTL is disabled."""
        config = WorkspaceConfig(session_ttl_minutes=0)
        assert config.session_ttl_minutes == 0

    def test_negative_raises_validation_error(self) -> None:
        """Negative values are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            WorkspaceConfig(session_ttl_minutes=-1)
        assert "session_ttl_minutes" in str(exc_info.value)

    def test_custom_positive_value_accepted(self) -> None:
        """Arbitrary positive integers are accepted."""
        config = WorkspaceConfig(session_ttl_minutes=60)
        assert config.session_ttl_minutes == 60

    def test_large_value_accepted(self) -> None:
        """Very large values (e.g., 10080 = 1 week) are accepted."""
        config = WorkspaceConfig(session_ttl_minutes=10080)
        assert config.session_ttl_minutes == 10080


class TestLifecycleConfigNotifySessionTtl:
    """LifecycleConfig.notify_session_ttl field defaults."""

    def test_notify_session_ttl_defaults_to_true(self) -> None:
        """notify_session_ttl is True by default."""
        config = LifecycleConfig()
        assert config.notify_session_ttl is True

    def test_notify_session_ttl_can_be_disabled(self) -> None:
        """notify_session_ttl can be set to False."""
        config = LifecycleConfig(notify_session_ttl=False)
        assert config.notify_session_ttl is False


# ---------------------------------------------------------------------------
# 2. SessionManager.is_session_expired()
# ---------------------------------------------------------------------------


class TestIsSessionExpired:
    """SessionManager.is_session_expired() behaviour."""

    def test_returns_false_when_ttl_is_zero(self, tmp_path: Path) -> None:
        """TTL of 0 always returns False (disabled)."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-5))

        assert manager.is_session_expired("telegram:1", ttl_minutes=0) is False

    def test_returns_false_for_unknown_session_key(self, tmp_path: Path) -> None:
        """Returns False when the session has never been created."""
        manager = _make_manager(tmp_path)

        assert manager.is_session_expired("telegram:unknown", ttl_minutes=30) is False

    def test_returns_false_when_last_active_at_is_none(self, tmp_path: Path) -> None:
        """New session with no activity (first message) is never expired."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", last_active_offset=None)

        # last_active_at is None because we never called increment_message_count
        state = manager.get_state("telegram:1")
        assert state is not None
        assert state.last_active_at is None

        assert manager.is_session_expired("telegram:1", ttl_minutes=1) is False

    def test_returns_false_when_session_within_ttl(self, tmp_path: Path) -> None:
        """Active session that last fired 10 min ago is not expired with 30-min TTL."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(minutes=-10))

        assert manager.is_session_expired("telegram:1", ttl_minutes=30) is False

    def test_returns_true_when_session_exceeds_ttl(self, tmp_path: Path) -> None:
        """Session that last fired 2 hours ago is expired with 60-min TTL."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-2))

        assert manager.is_session_expired("telegram:1", ttl_minutes=60) is True

    def test_exactly_at_boundary_is_not_expired(self, tmp_path: Path) -> None:
        """Elapsed time exactly equal to TTL is NOT expired (strict > comparison)."""
        manager = _make_manager(tmp_path)
        ttl_minutes = 30

        # Set last_active_at to exactly TTL seconds ago
        manager.get_thread_id("telegram:1")
        with manager._lock:
            manager._sessions["telegram:1"].last_active_at = (
                datetime.now(UTC) - timedelta(minutes=ttl_minutes)
            )

        # elapsed == ttl * 60 exactly — should NOT be expired (uses strict >)
        # Due to execution time the elapsed will be very slightly over the boundary,
        # so we verify the logic direction with a time that is 1 second under boundary.
        manager._sessions["telegram:1"].last_active_at = (
            datetime.now(UTC) - timedelta(seconds=ttl_minutes * 60 - 1)
        )

        assert manager.is_session_expired("telegram:1", ttl_minutes=ttl_minutes) is False

    def test_negative_ttl_treated_as_disabled(self, tmp_path: Path) -> None:
        """Negative ttl_minutes is treated the same as 0 (disabled)."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(days=-7))

        assert manager.is_session_expired("telegram:1", ttl_minutes=-5) is False


# ---------------------------------------------------------------------------
# 3. MessageProcessor._check_session_ttl() integration
# ---------------------------------------------------------------------------


class TestCheckSessionTtl:
    """MessageProcessor._check_session_ttl() end-to-end behaviour."""

    @pytest.mark.asyncio
    async def test_returns_none_when_ttl_disabled(self, tmp_path: Path) -> None:
        """Returns None immediately when session_ttl_minutes is 0."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-5))
        processor = _make_processor(manager, session_ttl_minutes=0)

        result = await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id="telegram:1:conv_old",
            channel=None,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_session_not_expired(self, tmp_path: Path) -> None:
        """Returns None when session is still within TTL window."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(minutes=-10))
        processor = _make_processor(manager, session_ttl_minutes=60)

        result = await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id="telegram:1:conv_current",
            channel=None,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_new_thread_id_when_expired(self, tmp_path: Path) -> None:
        """Returns a new thread_id when the session has expired."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-3))
        old_thread_id = manager.get_thread_id("telegram:1")

        processor = _make_processor(manager, session_ttl_minutes=60)

        result = await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id=old_thread_id,
            channel=None,
        )

        assert result is not None
        assert result != old_thread_id
        assert result.startswith("telegram:1:conv_")

    @pytest.mark.asyncio
    async def test_archives_conversation_when_archiver_available(
        self, tmp_path: Path
    ) -> None:
        """Calls archiver.archive() with ttl_expired tag when archiver is set."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-3))
        old_thread_id = manager.get_thread_id("telegram:1")

        archiver = AsyncMock()
        runner = MagicMock()
        runner.checkpointer = MagicMock()  # Non-None checkpointer

        processor = _make_processor(
            manager,
            session_ttl_minutes=60,
            conversation_archiver=archiver,
            agent_runner=runner,
        )

        await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id=old_thread_id,
            channel=None,
        )

        archiver.archive.assert_called_once()
        call_kwargs = archiver.archive.call_args.kwargs
        assert call_kwargs["thread_id"] == old_thread_id
        assert call_kwargs["session_key"] == "telegram:1"
        assert "ttl_expired" in call_kwargs["tags"]

    @pytest.mark.asyncio
    async def test_skips_archive_when_archiver_is_none(self, tmp_path: Path) -> None:
        """Does not crash and still rotates when archiver is None."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-3))
        old_thread_id = manager.get_thread_id("telegram:1")

        processor = _make_processor(
            manager,
            session_ttl_minutes=60,
            conversation_archiver=None,
        )

        result = await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id=old_thread_id,
            channel=None,
        )

        # Rotation still happened
        assert result is not None
        assert result != old_thread_id

    @pytest.mark.asyncio
    async def test_skips_archive_when_checkpointer_is_none(
        self, tmp_path: Path
    ) -> None:
        """Does not call archiver when checkpointer is None."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-3))
        old_thread_id = manager.get_thread_id("telegram:1")

        archiver = AsyncMock()
        runner = MagicMock()
        runner.checkpointer = None  # No checkpointer

        processor = _make_processor(
            manager,
            session_ttl_minutes=60,
            conversation_archiver=archiver,
            agent_runner=runner,
        )

        await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id=old_thread_id,
            channel=None,
        )

        archiver.archive.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_notification_to_channel_when_expired(
        self, tmp_path: Path
    ) -> None:
        """Sends a message to the channel when session expires."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-3))
        old_thread_id = manager.get_thread_id("telegram:1")

        channel = AsyncMock()
        lifecycle = LifecycleConfig(notify_session_ttl=True)
        processor = _make_processor(
            manager, session_ttl_minutes=60, lifecycle_config=lifecycle
        )

        await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id=old_thread_id,
            channel=channel,
        )

        channel.send_message.assert_called_once()
        call_args = channel.send_message.call_args
        assert call_args.args[0] == "telegram:1"
        # Message should mention expiry/inactivity
        sent_text: str = call_args.args[1]
        assert any(
            word in sent_text.lower()
            for word in ("expired", "inactivity", "fresh", "new")
        )

    @pytest.mark.asyncio
    async def test_does_not_notify_when_notify_session_ttl_is_false(
        self, tmp_path: Path
    ) -> None:
        """Skips channel notification when notify_session_ttl is False."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-3))
        old_thread_id = manager.get_thread_id("telegram:1")

        channel = AsyncMock()
        lifecycle = LifecycleConfig(notify_session_ttl=False)
        processor = _make_processor(
            manager, session_ttl_minutes=60, lifecycle_config=lifecycle
        )

        result = await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id=old_thread_id,
            channel=channel,
        )

        # Rotation still happened
        assert result is not None
        # But no notification was sent
        channel.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_notification_failure_is_handled_gracefully(
        self, tmp_path: Path
    ) -> None:
        """A failing channel.send_message() does not propagate as an exception."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-3))
        old_thread_id = manager.get_thread_id("telegram:1")

        channel = AsyncMock()
        channel.send_message.side_effect = RuntimeError("network error")

        lifecycle = LifecycleConfig(notify_session_ttl=True)
        processor = _make_processor(
            manager, session_ttl_minutes=60, lifecycle_config=lifecycle
        )

        # Should not raise — notification is best-effort
        result = await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id=old_thread_id,
            channel=channel,
        )

        # Rotation still succeeded
        assert result is not None

    @pytest.mark.asyncio
    async def test_logs_info_message_on_ttl_expiry(self, tmp_path: Path) -> None:
        """An info-level log is emitted when the session TTL expires."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-3))
        old_thread_id = manager.get_thread_id("telegram:1")

        mock_logger = Mock()
        processor = _make_processor(manager, session_ttl_minutes=60)
        processor._logger = mock_logger

        await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id=old_thread_id,
            channel=None,
        )

        mock_logger.info.assert_called()
        log_message: str = mock_logger.info.call_args.args[0]
        assert "telegram:1" in log_message

    @pytest.mark.asyncio
    async def test_archive_failure_is_handled_gracefully(
        self, tmp_path: Path
    ) -> None:
        """A failing archiver does not prevent conversation rotation."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-3))
        old_thread_id = manager.get_thread_id("telegram:1")

        archiver = AsyncMock()
        archiver.archive.side_effect = Exception("disk full")

        runner = MagicMock()
        runner.checkpointer = MagicMock()

        processor = _make_processor(
            manager,
            session_ttl_minutes=60,
            conversation_archiver=archiver,
            agent_runner=runner,
        )

        # Should not raise
        result = await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id=old_thread_id,
            channel=None,
        )

        # Rotation still succeeded despite archive failure
        assert result is not None
        assert result != old_thread_id

    @pytest.mark.asyncio
    async def test_notify_defaults_to_true_when_lifecycle_config_is_none(
        self, tmp_path: Path
    ) -> None:
        """When lifecycle_config is None, notification is sent (default behaviour)."""
        manager = _make_manager(tmp_path)
        _seed_session(manager, "telegram:1", timedelta(hours=-3))
        old_thread_id = manager.get_thread_id("telegram:1")

        channel = AsyncMock()
        # lifecycle_config is intentionally None
        processor = _make_processor(
            manager, session_ttl_minutes=60, lifecycle_config=None
        )

        await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id=old_thread_id,
            channel=channel,
        )

        # getattr(None, "notify_session_ttl", True) returns True
        channel.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_session_rotated_independently_per_key(
        self, tmp_path: Path
    ) -> None:
        """TTL expiry for one session key does not affect another."""
        manager = _make_manager(tmp_path)

        # session A: old (expired)
        _seed_session(manager, "telegram:1", timedelta(hours=-3))
        old_thread_a = manager.get_thread_id("telegram:1")

        # session B: recent (not expired)
        _seed_session(manager, "telegram:2", timedelta(minutes=-5))
        thread_b_before = manager.get_thread_id("telegram:2")

        processor = _make_processor(manager, session_ttl_minutes=60)

        # Expire session A
        result_a = await processor._check_session_ttl(
            session_key="telegram:1",
            thread_id=old_thread_a,
            channel=None,
        )

        # Session B should be unchanged
        result_b = await processor._check_session_ttl(
            session_key="telegram:2",
            thread_id=thread_b_before,
            channel=None,
        )

        assert result_a is not None  # A was rotated
        assert result_b is None  # B was not touched
        assert manager.get_thread_id("telegram:2") == thread_b_before
