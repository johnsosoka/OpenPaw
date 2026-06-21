"""Checkpoint pruner for OpenPaw.

Prunes orphaned checkpoint data from the AsyncSqliteSaver database at workspace
startup.  A thread is considered orphaned when it no longer matches any active
conversation tracked by SessionManager.  Threads older than the configured
retention window are deleted from both the ``checkpoints`` and ``writes``
tables; a ``VACUUM`` is performed afterward to reclaim disk space.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import aiosqlite

from openpaw.runtime.session.manager import SessionManager

logger = logging.getLogger(__name__)


def _parse_conv_timestamp(conv_id: str) -> datetime | None:
    """Parse the UTC timestamp encoded in a conversation ID.

    Conversation IDs use the format::

        conv_YYYY-MM-DDTHH-MM-SS-MMMMMM

    The dashes inside the time component must be converted back to colons and
    the final dash (before microseconds) to a period before the string is
    parseable by :func:`datetime.fromisoformat`.

    Args:
        conv_id: Conversation ID string (e.g. ``"conv_2026-04-02T03-33-20-430352"``).

    Returns:
        Parsed UTC-aware :class:`datetime`, or ``None`` if parsing fails.
    """
    try:
        # Strip the "conv_" prefix
        raw = conv_id.removeprefix("conv_")

        # raw looks like: "2026-04-02T03-33-20-430352"
        # Split on "T" to separate date and time portions
        date_part, time_part = raw.split("T", 1)

        # time_part: "03-33-20-430352"
        # Split on "-" — always produces [HH, MM, SS, MMMMMM]
        time_segments = time_part.split("-")
        if len(time_segments) != 4:
            return None

        hh, mm, ss, us = time_segments
        iso_str = f"{date_part}T{hh}:{mm}:{ss}.{us}+00:00"
        return datetime.fromisoformat(iso_str)

    except (ValueError, AttributeError):
        logger.debug(f"Could not parse timestamp from conv_id: {conv_id!r}")
        return None


@dataclass
class PruneResult:
    """Statistics from a checkpoint pruning run.

    Attributes:
        threads_pruned: Number of distinct thread_ids deleted.
        checkpoints_deleted: Number of rows removed from the checkpoints table.
        writes_deleted: Number of rows removed from the writes table.
        vacuum_run: True if VACUUM was executed after deletion.
        skipped_unparseable: Thread IDs whose conv timestamp could not be parsed.
    """

    threads_pruned: int = 0
    checkpoints_deleted: int = 0
    writes_deleted: int = 0
    vacuum_run: bool = False
    skipped_unparseable: list[str] = field(default_factory=list)


class CheckpointPruner:
    """Prunes orphaned checkpoint rows from the SQLite database.

    At workspace startup, this class deletes checkpoint and write rows for
    conversation threads that:

    1. Are not the currently active conversation for any session, AND
    2. Have a conversation timestamp older than ``retention_days`` from now.

    After any deletions a ``VACUUM`` is run to reclaim disk space.

    Args:
        db_conn: Open :class:`aiosqlite.Connection` to the checkpoint database.
        session_manager: Live :class:`SessionManager` for the workspace.
        retention_days: Number of days before an orphaned thread is eligible
            for pruning.  Must be >= 1.
    """

    def __init__(
        self,
        db_conn: aiosqlite.Connection,
        session_manager: SessionManager,
        retention_days: int,
    ) -> None:
        self._db_conn = db_conn
        self._session_manager = session_manager
        self._retention_days = retention_days

    async def prune(self) -> PruneResult:
        """Prune orphaned checkpoint data.

        Returns:
            :class:`PruneResult` with counts of deleted threads, checkpoints,
            and writes, plus whether VACUUM was executed.
        """
        result = PruneResult()
        cutoff = datetime.now(UTC) - timedelta(days=self._retention_days)
        logger.info(
            f"Checkpoint pruner: starting (retention={self._retention_days}d, "
            f"cutoff={cutoff.date().isoformat()})"
        )

        # --- 1. Collect all thread IDs present in the database ---
        async with self._db_conn.execute(
            "SELECT DISTINCT thread_id FROM checkpoints"
        ) as cursor:
            rows = await cursor.fetchall()

        all_thread_ids: set[str] = {row[0] for row in rows}
        if not all_thread_ids:
            logger.info("Checkpoint pruner: database is empty, nothing to do")
            return result

        logger.info(
            f"Checkpoint pruner: {len(all_thread_ids)} distinct thread(s) in DB"
        )

        # --- 2. Determine which thread IDs are currently active ---
        active_thread_ids = self._session_manager.get_active_thread_ids()
        logger.info(
            f"Checkpoint pruner: {len(active_thread_ids)} active thread(s) in sessions"
        )

        # --- 3. Find threads eligible for deletion ---
        threads_to_delete: list[str] = []

        for thread_id in all_thread_ids:
            if thread_id in active_thread_ids:
                continue

            # Extract the conversation_id from the thread_id.
            # Thread ID format: "{session_key}:{conversation_id}"
            # session_key may itself contain colons (e.g. "telegram:123456"),
            # so split from the right to get the conv_id portion.
            _, conv_id = thread_id.rsplit(":", 1)

            if not conv_id.startswith("conv_"):
                logger.debug(f"Skipping thread with unexpected conv_id format: {thread_id!r}")
                result.skipped_unparseable.append(thread_id)
                continue

            conv_ts = _parse_conv_timestamp(conv_id)
            if conv_ts is None:
                logger.debug(f"Skipping thread with unparseable timestamp: {thread_id!r}")
                result.skipped_unparseable.append(thread_id)
                continue

            if conv_ts < cutoff:
                threads_to_delete.append(thread_id)
                logger.debug(f"Marked for deletion: {thread_id!r} (ts={conv_ts.isoformat()})")

        if not threads_to_delete:
            logger.info(
                f"Checkpoint pruner: no threads eligible for pruning "
                f"(skipped_unparseable={len(result.skipped_unparseable)})"
            )
            return result

        logger.info(
            f"Checkpoint pruner: {len(threads_to_delete)} thread(s) selected for deletion"
        )

        # --- 4. Batch-delete rows for eligible threads ---
        placeholders = ",".join("?" * len(threads_to_delete))

        async with self._db_conn.execute(
            f"DELETE FROM checkpoints WHERE thread_id IN ({placeholders})",
            threads_to_delete,
        ) as cursor:
            result.checkpoints_deleted = cursor.rowcount

        async with self._db_conn.execute(
            f"DELETE FROM writes WHERE thread_id IN ({placeholders})",
            threads_to_delete,
        ) as cursor:
            result.writes_deleted = cursor.rowcount

        await self._db_conn.commit()

        result.threads_pruned = len(threads_to_delete)

        logger.info(
            f"Checkpoint pruner: removed {result.checkpoints_deleted} checkpoint row(s) "
            f"and {result.writes_deleted} write row(s) "
            f"across {result.threads_pruned} thread(s)"
        )

        # --- 5. VACUUM to reclaim disk space ---
        logger.info("Checkpoint pruner: running VACUUM to reclaim disk space ...")
        t_start = time.monotonic()
        await self._db_conn.execute("VACUUM")
        elapsed_ms = (time.monotonic() - t_start) * 1000
        result.vacuum_run = True
        logger.info(f"Checkpoint pruner: VACUUM completed in {elapsed_ms:.0f}ms")

        return result
