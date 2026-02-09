"""Tests for SessionManager."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openpaw.runtime.session.manager import SessionManager, SessionState


def test_get_thread_id_format(tmp_path: Path):
    """Test thread_id returns correct format."""
    manager = SessionManager(tmp_path)
    session_key = "telegram:123456"

    thread_id = manager.get_thread_id(session_key)

    # Format: {session_key}:{conversation_id}
    assert thread_id.startswith("telegram:123456:conv_")
    parts = thread_id.split(":")
    assert len(parts) == 3
    assert parts[0] == "telegram"
    assert parts[1] == "123456"
    assert parts[2].startswith("conv_")


def test_get_thread_id_creates_new_session(tmp_path: Path):
    """Test get_thread_id creates new session on first call."""
    manager = SessionManager(tmp_path)
    session_key = "telegram:123456"

    # First call should create session
    thread_id = manager.get_thread_id(session_key)
    assert thread_id is not None

    # State should exist
    state = manager.get_state(session_key)
    assert state is not None
    assert state.conversation_id.startswith("conv_")
    assert state.message_count == 0
    assert state.last_active_at is None


def test_get_thread_id_idempotent(tmp_path: Path):
    """Test get_thread_id returns same thread_id on repeated calls."""
    manager = SessionManager(tmp_path)
    session_key = "telegram:123456"

    thread_id_1 = manager.get_thread_id(session_key)
    thread_id_2 = manager.get_thread_id(session_key)

    assert thread_id_1 == thread_id_2


def test_new_conversation_rotates_id(tmp_path: Path):
    """Test new_conversation rotates conversation_id and returns old one."""
    manager = SessionManager(tmp_path)
    session_key = "telegram:123456"

    # Get initial conversation
    initial_thread_id = manager.get_thread_id(session_key)
    initial_conv_id = initial_thread_id.split(":")[-1]

    # Rotate conversation
    old_conv_id = manager.new_conversation(session_key)

    # Should return old conversation ID
    assert old_conv_id == initial_conv_id

    # New thread_id should be different
    new_thread_id = manager.get_thread_id(session_key)
    new_conv_id = new_thread_id.split(":")[-1]

    assert new_conv_id != initial_conv_id
    assert new_conv_id.startswith("conv_")


def test_increment_message_count(tmp_path: Path):
    """Test increment_message_count bumps count and updates timestamp."""
    manager = SessionManager(tmp_path)
    session_key = "telegram:123456"

    # Create session
    manager.get_thread_id(session_key)

    # Increment count
    manager.increment_message_count(session_key)

    # Verify count increased
    state = manager.get_state(session_key)
    assert state is not None
    assert state.message_count == 1
    assert state.last_active_at is not None

    # Increment again
    manager.increment_message_count(session_key)

    # Verify count increased again
    state = manager.get_state(session_key)
    assert state.message_count == 2


def test_persistence_survives_reload(tmp_path: Path):
    """Test JSON persistence survives manager reload."""
    session_key = "telegram:123456"

    # Create manager and session
    manager1 = SessionManager(tmp_path)
    thread_id_1 = manager1.get_thread_id(session_key)
    manager1.increment_message_count(session_key)
    manager1.increment_message_count(session_key)

    # Create new manager instance (simulates restart)
    manager2 = SessionManager(tmp_path)
    thread_id_2 = manager2.get_thread_id(session_key)

    # Should load same conversation
    assert thread_id_1 == thread_id_2

    # Should preserve message count
    state = manager2.get_state(session_key)
    assert state is not None
    assert state.message_count == 2


def test_multiple_sessions(tmp_path: Path):
    """Test manager handles multiple independent sessions."""
    manager = SessionManager(tmp_path)

    session1 = "telegram:111"
    session2 = "telegram:222"

    # Create two sessions
    thread_id_1 = manager.get_thread_id(session1)
    thread_id_2 = manager.get_thread_id(session2)

    # Should be different
    assert thread_id_1 != thread_id_2
    assert thread_id_1.startswith("telegram:111:")
    assert thread_id_2.startswith("telegram:222:")

    # Update one session
    manager.increment_message_count(session1)

    # Other session unaffected
    state1 = manager.get_state(session1)
    state2 = manager.get_state(session2)

    assert state1.message_count == 1
    assert state2.message_count == 0


def test_list_sessions(tmp_path: Path):
    """Test list_sessions returns all active sessions."""
    manager = SessionManager(tmp_path)

    # Create multiple sessions
    manager.get_thread_id("telegram:111")
    manager.get_thread_id("telegram:222")
    manager.get_thread_id("discord:333")

    # List sessions
    sessions = manager.list_sessions()

    assert len(sessions) == 3
    assert "telegram:111" in sessions
    assert "telegram:222" in sessions
    assert "discord:333" in sessions


def test_get_state_returns_none_for_unknown_session(tmp_path: Path):
    """Test get_state returns None for unknown session."""
    manager = SessionManager(tmp_path)

    state = manager.get_state("unknown:session")

    assert state is None


def test_increment_message_count_for_unknown_session(tmp_path: Path):
    """Test increment_message_count handles unknown session gracefully."""
    manager = SessionManager(tmp_path)

    # Should not crash
    manager.increment_message_count("unknown:session")

    # Should not create session
    state = manager.get_state("unknown:session")
    assert state is None


def test_conversation_id_format(tmp_path: Path):
    """Test conversation ID follows timestamp format."""
    manager = SessionManager(tmp_path)

    # Get conversation ID
    thread_id = manager.get_thread_id("test:123")
    conv_id = thread_id.split(":")[-1]

    # Should match format: conv_YYYY-MM-DDTHH-MM-SS-MMMMMM
    assert conv_id.startswith("conv_")
    timestamp_part = conv_id[5:]  # Remove "conv_" prefix

    # Should be parseable as datetime-ish format with microseconds
    assert len(timestamp_part) == 26  # YYYY-MM-DDTHH-MM-SS-MMMMMM
    assert timestamp_part[4] == "-"
    assert timestamp_part[7] == "-"
    assert timestamp_part[10] == "T"
    assert timestamp_part[13] == "-"
    assert timestamp_part[16] == "-"
    assert timestamp_part[19] == "-"  # Separator before microseconds


def test_openpaw_directory_created(tmp_path: Path):
    """Test SessionManager creates .openpaw directory."""
    manager = SessionManager(tmp_path)

    openpaw_dir = tmp_path / ".openpaw"
    assert openpaw_dir.exists()
    assert openpaw_dir.is_dir()


def test_sessions_json_created_on_first_save(tmp_path: Path):
    """Test sessions.json is created on first state change."""
    manager = SessionManager(tmp_path)

    # Initially no file
    state_file = tmp_path / ".openpaw" / "sessions.json"
    # File may or may not exist yet (depends on whether constructor saves empty state)

    # Create a session (definitely triggers save)
    manager.get_thread_id("telegram:123")

    # Now file should exist
    assert state_file.exists()
    assert state_file.is_file()


def test_corrupted_json_handled_gracefully(tmp_path: Path):
    """Test manager handles corrupted JSON file gracefully."""
    # Create corrupted JSON file
    openpaw_dir = tmp_path / ".openpaw"
    openpaw_dir.mkdir(parents=True, exist_ok=True)
    state_file = openpaw_dir / "sessions.json"
    state_file.write_text("{corrupted json content")

    # Should not crash
    manager = SessionManager(tmp_path)

    # Should start with empty state
    sessions = manager.list_sessions()
    assert len(sessions) == 0

    # Should be able to create new sessions
    thread_id = manager.get_thread_id("telegram:123")
    assert thread_id is not None


def test_session_state_to_dict(tmp_path: Path):
    """Test SessionState.to_dict serialization."""
    state = SessionState(
        conversation_id="conv_2026-02-07T14-30-00",
        started_at=datetime(2026, 2, 7, 14, 30, 0, tzinfo=UTC),
        message_count=5,
        last_active_at=datetime(2026, 2, 7, 15, 0, 0, tzinfo=UTC),
    )

    data = state.to_dict()

    assert data["conversation_id"] == "conv_2026-02-07T14-30-00"
    assert data["started_at"] == "2026-02-07T14:30:00+00:00"
    assert data["message_count"] == 5
    assert data["last_active_at"] == "2026-02-07T15:00:00+00:00"


def test_session_state_from_dict(tmp_path: Path):
    """Test SessionState.from_dict deserialization."""
    data = {
        "conversation_id": "conv_2026-02-07T14-30-00",
        "started_at": "2026-02-07T14:30:00+00:00",
        "message_count": 5,
        "last_active_at": "2026-02-07T15:00:00+00:00",
    }

    state = SessionState.from_dict(data)

    assert state.conversation_id == "conv_2026-02-07T14-30-00"
    assert state.started_at == datetime(2026, 2, 7, 14, 30, 0, tzinfo=UTC)
    assert state.message_count == 5
    assert state.last_active_at == datetime(2026, 2, 7, 15, 0, 0, tzinfo=UTC)


def test_session_state_roundtrip(tmp_path: Path):
    """Test SessionState serialization roundtrip."""
    original = SessionState(
        conversation_id="conv_2026-02-07T14-30-00",
        started_at=datetime(2026, 2, 7, 14, 30, 0, tzinfo=UTC),
        message_count=10,
        last_active_at=datetime(2026, 2, 7, 16, 0, 0, tzinfo=UTC),
    )

    # Roundtrip
    data = original.to_dict()
    restored = SessionState.from_dict(data)

    assert restored.conversation_id == original.conversation_id
    assert restored.started_at == original.started_at
    assert restored.message_count == original.message_count
    assert restored.last_active_at == original.last_active_at
