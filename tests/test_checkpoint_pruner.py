"""Tests for CheckpointPruner.

Tests use in-memory aiosqlite databases with the real AsyncSqliteSaver schema
created manually, plus a real SessionManager so the active-thread detection
logic exercises the actual code path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from openpaw.runtime.session.manager import SessionManager
from openpaw.runtime.session.pruner import (
    CheckpointPruner,
    PruneResult,
    _parse_conv_timestamp,
)

# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

CREATE_CHECKPOINTS = """
    CREATE TABLE IF NOT EXISTS checkpoints (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        parent_checkpoint_id TEXT,
        type TEXT,
        checkpoint BLOB,
        metadata BLOB,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
    )
"""

CREATE_WRITES = """
    CREATE TABLE IF NOT EXISTS writes (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        idx INTEGER NOT NULL,
        channel TEXT NOT NULL,
        type TEXT,
        value BLOB,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
    )
"""


async def _setup_schema(conn: aiosqlite.Connection) -> None:
    await conn.execute(CREATE_CHECKPOINTS)
    await conn.execute(CREATE_WRITES)
    await conn.commit()


async def _insert_checkpoint(
    conn: aiosqlite.Connection,
    thread_id: str,
    checkpoint_id: str = "ckpt_1",
) -> None:
    await conn.execute(
        "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id) VALUES (?, '', ?)",
        (thread_id, checkpoint_id),
    )
    await conn.commit()


async def _insert_write(
    conn: aiosqlite.Connection,
    thread_id: str,
    checkpoint_id: str = "ckpt_1",
    task_id: str = "task_1",
    idx: int = 0,
) -> None:
    await conn.execute(
        "INSERT INTO writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel) "
        "VALUES (?, '', ?, ?, ?, 'messages')",
        (thread_id, checkpoint_id, task_id, idx),
    )
    await conn.commit()


def _conv_id_for(dt: datetime) -> str:
    """Build a conv_id string from a datetime the same way SessionManager does."""
    timestamp = dt.strftime("%Y-%m-%dT%H-%M-%S")
    microseconds = dt.strftime("%f")
    return f"conv_{timestamp}-{microseconds}"


# ---------------------------------------------------------------------------
# Unit tests for _parse_conv_timestamp
# ---------------------------------------------------------------------------


def test_parse_conv_timestamp_valid():
    """Parse a well-formed conv_id and verify the result."""
    conv_id = "conv_2026-04-02T03-33-20-430352"
    result = _parse_conv_timestamp(conv_id)

    assert result is not None
    assert result == datetime(2026, 4, 2, 3, 33, 20, 430352, tzinfo=UTC)


def test_parse_conv_timestamp_invalid_returns_none():
    """Malformed conv_id returns None without raising."""
    assert _parse_conv_timestamp("conv_not-a-date") is None
    assert _parse_conv_timestamp("no-prefix") is None
    assert _parse_conv_timestamp("conv_") is None


# ---------------------------------------------------------------------------
# Integration tests using real aiosqlite + real SessionManager
# ---------------------------------------------------------------------------


async def test_prune_removes_orphaned_threads(tmp_path: Path):
    """Orphaned threads older than the retention window are removed from both tables."""
    conn = await aiosqlite.connect(":memory:")
    await _setup_schema(conn)

    session_manager = SessionManager(tmp_path)

    old_dt = datetime.now(UTC) - timedelta(days=10)
    old_thread = f"telegram:111:{_conv_id_for(old_dt)}"

    another_old_dt = datetime.now(UTC) - timedelta(days=15)
    another_old_thread = f"telegram:222:{_conv_id_for(another_old_dt)}"

    # Active session: register via SessionManager so it is never deleted
    active_thread = session_manager.get_thread_id("telegram:333")

    for tid in (old_thread, another_old_thread, active_thread):
        await _insert_checkpoint(conn, tid)
        await _insert_write(conn, tid)

    pruner = CheckpointPruner(conn, session_manager, retention_days=7)
    result = await pruner.prune()

    assert result.threads_pruned == 2

    # Orphaned rows must be gone from both tables
    async with conn.execute(
        "SELECT thread_id FROM checkpoints WHERE thread_id IN (?, ?)",
        (old_thread, another_old_thread),
    ) as cursor:
        assert await cursor.fetchall() == []

    async with conn.execute(
        "SELECT thread_id FROM writes WHERE thread_id IN (?, ?)",
        (old_thread, another_old_thread),
    ) as cursor:
        assert await cursor.fetchall() == []

    await conn.close()


async def test_prune_preserves_active_thread(tmp_path: Path):
    """The active conversation thread is never deleted regardless of age."""
    conn = await aiosqlite.connect(":memory:")
    await _setup_schema(conn)

    session_manager = SessionManager(tmp_path)
    active_thread = session_manager.get_thread_id("telegram:123")

    await _insert_checkpoint(conn, active_thread)
    await _insert_write(conn, active_thread)

    pruner = CheckpointPruner(conn, session_manager, retention_days=7)
    result = await pruner.prune()

    assert result.threads_pruned == 0

    async with conn.execute(
        "SELECT thread_id FROM checkpoints WHERE thread_id = ?",
        (active_thread,),
    ) as cursor:
        assert await cursor.fetchone() is not None

    await conn.close()


async def test_prune_respects_retention_days(tmp_path: Path):
    """Threads younger than retention_days are NOT pruned even if orphaned."""
    conn = await aiosqlite.connect(":memory:")
    await _setup_schema(conn)

    session_manager = SessionManager(tmp_path)

    # Recent orphan: 3 days old — within the 7-day window, must survive
    recent_dt = datetime.now(UTC) - timedelta(days=3)
    recent_thread = f"telegram:444:{_conv_id_for(recent_dt)}"

    # Old orphan: 10 days old — outside the 7-day window, must be deleted
    old_dt = datetime.now(UTC) - timedelta(days=10)
    old_thread = f"telegram:555:{_conv_id_for(old_dt)}"

    for tid in (recent_thread, old_thread):
        await _insert_checkpoint(conn, tid)

    pruner = CheckpointPruner(conn, session_manager, retention_days=7)
    result = await pruner.prune()

    assert result.threads_pruned == 1

    async with conn.execute(
        "SELECT thread_id FROM checkpoints WHERE thread_id = ?",
        (recent_thread,),
    ) as cursor:
        assert await cursor.fetchone() is not None

    await conn.close()


async def test_prune_skips_unparseable_thread_ids(tmp_path: Path):
    """Thread IDs with non-standard formats are left alone and tracked in result."""
    conn = await aiosqlite.connect(":memory:")
    await _setup_schema(conn)

    session_manager = SessionManager(tmp_path)

    # A thread_id with a conv portion we cannot parse
    malformed_thread = "telegram:999:not-a-conv-id"
    await _insert_checkpoint(conn, malformed_thread)

    # A valid old orphan to verify the pruner still works otherwise
    old_dt = datetime.now(UTC) - timedelta(days=20)
    old_thread = f"telegram:888:{_conv_id_for(old_dt)}"
    await _insert_checkpoint(conn, old_thread)

    pruner = CheckpointPruner(conn, session_manager, retention_days=7)
    result = await pruner.prune()

    # Only the old valid thread should be deleted
    assert result.threads_pruned == 1
    assert malformed_thread in result.skipped_unparseable

    # Malformed thread must still exist in the DB
    async with conn.execute(
        "SELECT thread_id FROM checkpoints WHERE thread_id = ?",
        (malformed_thread,),
    ) as cursor:
        assert await cursor.fetchone() is not None

    await conn.close()


async def test_prune_result_stats(tmp_path: Path):
    """PruneResult reflects correct row counts for checkpoints and writes."""
    conn = await aiosqlite.connect(":memory:")
    await _setup_schema(conn)

    session_manager = SessionManager(tmp_path)

    old_dt = datetime.now(UTC) - timedelta(days=20)
    old_thread = f"telegram:100:{_conv_id_for(old_dt)}"

    # Two checkpoints and three write rows for a single thread
    await _insert_checkpoint(conn, old_thread, "ckpt_a")
    await _insert_checkpoint(conn, old_thread, "ckpt_b")
    await _insert_write(conn, old_thread, "ckpt_a", task_id="t1", idx=0)
    await _insert_write(conn, old_thread, "ckpt_a", task_id="t1", idx=1)
    await _insert_write(conn, old_thread, "ckpt_b", task_id="t2", idx=0)

    pruner = CheckpointPruner(conn, session_manager, retention_days=7)
    result = await pruner.prune()

    assert isinstance(result, PruneResult)
    assert result.threads_pruned == 1
    assert result.checkpoints_deleted == 2
    assert result.writes_deleted == 3

    await conn.close()


async def test_prune_handles_empty_database(tmp_path: Path):
    """Empty database returns zero stats without error."""
    conn = await aiosqlite.connect(":memory:")
    await _setup_schema(conn)

    session_manager = SessionManager(tmp_path)
    pruner = CheckpointPruner(conn, session_manager, retention_days=7)

    result = await pruner.prune()

    assert result.threads_pruned == 0
    assert result.checkpoints_deleted == 0
    assert result.writes_deleted == 0
    assert result.vacuum_run is False

    await conn.close()


async def test_vacuum_runs_after_deletion(tmp_path: Path):
    """VACUUM is executed when at least one thread is deleted."""
    conn = await aiosqlite.connect(":memory:")
    await _setup_schema(conn)

    session_manager = SessionManager(tmp_path)

    old_dt = datetime.now(UTC) - timedelta(days=30)
    old_thread = f"telegram:200:{_conv_id_for(old_dt)}"
    await _insert_checkpoint(conn, old_thread)

    pruner = CheckpointPruner(conn, session_manager, retention_days=7)
    result = await pruner.prune()

    assert result.threads_pruned == 1
    assert result.vacuum_run is True

    await conn.close()


async def test_vacuum_does_not_run_when_nothing_deleted(tmp_path: Path):
    """VACUUM is skipped when no threads qualify for pruning."""
    conn = await aiosqlite.connect(":memory:")
    await _setup_schema(conn)

    session_manager = SessionManager(tmp_path)

    # Recent orphan: only 2 days old — younger than 7-day retention
    recent_dt = datetime.now(UTC) - timedelta(days=2)
    recent_thread = f"telegram:300:{_conv_id_for(recent_dt)}"
    await _insert_checkpoint(conn, recent_thread)

    pruner = CheckpointPruner(conn, session_manager, retention_days=7)
    result = await pruner.prune()

    assert result.threads_pruned == 0
    assert result.vacuum_run is False

    await conn.close()


async def test_prune_cleans_both_tables(tmp_path: Path):
    """Rows are removed from BOTH checkpoints AND writes tables for deleted threads."""
    conn = await aiosqlite.connect(":memory:")
    await _setup_schema(conn)

    session_manager = SessionManager(tmp_path)

    old_dt = datetime.now(UTC) - timedelta(days=20)
    old_thread = f"telegram:666:{_conv_id_for(old_dt)}"

    await _insert_checkpoint(conn, old_thread, "ckpt_a")
    await _insert_checkpoint(conn, old_thread, "ckpt_b")
    await _insert_write(conn, old_thread, "ckpt_a", task_id="t1", idx=0)
    await _insert_write(conn, old_thread, "ckpt_a", task_id="t1", idx=1)
    await _insert_write(conn, old_thread, "ckpt_b", task_id="t2", idx=0)

    pruner = CheckpointPruner(conn, session_manager, retention_days=7)
    await pruner.prune()

    async with conn.execute(
        "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (old_thread,)
    ) as cursor:
        (count,) = await cursor.fetchone()
    assert count == 0

    async with conn.execute(
        "SELECT COUNT(*) FROM writes WHERE thread_id = ?", (old_thread,)
    ) as cursor:
        (count,) = await cursor.fetchone()
    assert count == 0

    await conn.close()


async def test_prune_no_op_when_all_threads_active(tmp_path: Path):
    """No rows are deleted when every DB thread belongs to an active session."""
    conn = await aiosqlite.connect(":memory:")
    await _setup_schema(conn)

    session_manager = SessionManager(tmp_path)

    thread_a = session_manager.get_thread_id("telegram:100")
    thread_b = session_manager.get_thread_id("telegram:200")

    for tid in (thread_a, thread_b):
        await _insert_checkpoint(conn, tid)

    pruner = CheckpointPruner(conn, session_manager, retention_days=7)
    result = await pruner.prune()

    assert result.threads_pruned == 0
    assert result.checkpoints_deleted == 0

    await conn.close()
