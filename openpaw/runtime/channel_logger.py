"""Persistent JSONL channel logger for all visible channel messages."""

import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openpaw.core.paths import CHANNEL_LOGS_DIR
from openpaw.core.timezone import workspace_now
from openpaw.core.utils import sanitize_filename
from openpaw.model.channel import ChannelEvent

logger = logging.getLogger(__name__)


class ChannelLogger:
    """Persistent JSONL logger for channel messages.

    Writes all visible messages to daily-rotated JSONL files organized
    by server and channel:

        {workspace_path}/memory/logs/channel/{server}/{channel}/{YYYY-MM-DD}.jsonl

    Files are agent-readable via filesystem tools (read_file, grep_files).
    Agents may NOT write to this directory (path is under WRITE_PROTECTED_DIRS).

    DM events (server_name is None) are silently skipped — privacy by design.

    Log entries use short keys to minimise file size. Timestamps are always UTC,
    consistent with the "store in UTC" convention used throughout the framework.
    """

    def __init__(
        self,
        workspace_path: Path,
        timezone: str = "UTC",
        retention_days: int = 30,
    ) -> None:
        """Initialise the channel logger.

        Args:
            workspace_path: Absolute path to the workspace root directory.
            timezone: IANA timezone identifier used to determine the daily
                file date boundary (e.g., 'America/Denver').
            retention_days: Number of days to keep log files before archiving.
                Must be >= 1.
        """
        self._workspace_path = Path(workspace_path)
        self._timezone = timezone
        self._retention_days = retention_days
        self._channel_logs_dir = self._workspace_path / str(CHANNEL_LOGS_DIR)
        # Per-file locks prevent interleaved writes under concurrent calls.
        self._file_locks: dict[Path, threading.Lock] = {}
        self._registry_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def log_event(self, event: ChannelEvent) -> None:
        """Append a channel event to the appropriate daily log file.

        Best-effort: all errors are caught and logged at DEBUG level.
        They are never propagated to the caller.

        DM events (server_name is None) are silently skipped.

        Args:
            event: The channel event to persist.
        """
        if event.server_name is None:
            return

        try:
            import asyncio

            await asyncio.to_thread(self._write_event, event)
        except Exception:
            logger.debug("ChannelLogger.log_event failed", exc_info=True)

    def archive_old_logs(self) -> int:
        """Move log files older than retention_days to _archive/.

        Archive path mirrors the source structure under an ``_archive``
        subdirectory:

            memory/logs/channel/_archive/{server}/{channel}/{YYYY-MM-DD}.jsonl

        After archiving, empty source directories are removed to keep the
        tree tidy. This method is synchronous — it is intended to be called
        once at workspace startup, not in the hot path.

        Returns:
            Number of files archived.
        """
        if not self._channel_logs_dir.exists():
            return 0

        today = workspace_now(self._timezone).date()
        cutoff = today - timedelta(days=self._retention_days)
        archive_root = self._channel_logs_dir / "_archive"
        archived_count = 0

        for log_file in sorted(self._channel_logs_dir.rglob("*.jsonl")):
            # Skip anything already in the _archive subtree.
            try:
                log_file.relative_to(archive_root)
                continue
            except ValueError:
                pass

            file_date = self._parse_date_from_filename(log_file.name)
            if file_date is None or file_date >= cutoff:
                continue

            # Preserve the server/channel directory structure under _archive.
            try:
                relative_parts = log_file.relative_to(self._channel_logs_dir)
            except ValueError:
                logger.debug("Skipping file outside channel logs dir: %s", log_file)
                continue

            dest = archive_root / relative_parts
            dest.parent.mkdir(parents=True, exist_ok=True)

            try:
                log_file.rename(dest)
                archived_count += 1
                logger.debug("Archived channel log: %s -> %s", log_file, dest)
            except OSError:
                logger.debug("Failed to archive channel log: %s", log_file, exc_info=True)
                continue

        # Remove empty source directories (skip _archive and channel root itself).
        self._remove_empty_dirs(self._channel_logs_dir, stop_at=self._channel_logs_dir)

        return archived_count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_event(self, event: ChannelEvent) -> None:
        """Synchronous write — called via asyncio.to_thread()."""
        log_file = self._resolve_log_file(event)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        record = self._build_record(event)
        line = json.dumps(record, ensure_ascii=False) + "\n"

        file_lock = self._get_file_lock(log_file)
        with file_lock:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(line)

    def _resolve_log_file(self, event: ChannelEvent) -> Path:
        """Compute the daily log file path for an event.

        Path: {channel_logs_dir}/{server}/{channel}/{YYYY-MM-DD}.jsonl

        Server and channel names are sanitised so they are safe as directory
        names on all platforms. The file date is derived from the event
        timestamp (converted to workspace timezone), not wall-clock time,
        so records always land in the file matching their actual date.
        """
        import zoneinfo

        server_dir = sanitize_filename(event.server_name or "unknown")
        channel_dir = sanitize_filename(event.channel_label or event.channel_id)

        # Derive file date from event timestamp in workspace timezone.
        ts = event.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        tz = zoneinfo.ZoneInfo(self._timezone)
        date_str = ts.astimezone(tz).strftime("%Y-%m-%d")

        return self._channel_logs_dir / server_dir / channel_dir / f"{date_str}.jsonl"

    def _build_record(self, event: ChannelEvent) -> dict:
        """Convert a ChannelEvent into the compact JSONL record dict.

        Short keys are intentional — they reduce file size.
        Timestamps are always UTC ISO 8601.
        """
        # Normalise timestamp to UTC regardless of its original tzinfo.
        ts = event.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        else:
            ts = ts.astimezone(UTC)

        return {
            "ts": ts.isoformat(),
            "msg_id": event.message_id,
            "user_id": event.user_id,
            "display_name": event.display_name,
            "content": event.content,
            "attachments": event.attachment_names,
            "channel_id": event.channel_id,
            "server_id": event.server_id,
        }

    def _get_file_lock(self, path: Path) -> threading.Lock:
        """Return a per-file lock, creating it if necessary."""
        with self._registry_lock:
            if path not in self._file_locks:
                self._file_locks[path] = threading.Lock()
            return self._file_locks[path]

    @staticmethod
    def _parse_date_from_filename(filename: str) -> "datetime.date | None":
        """Extract the date from a YYYY-MM-DD.jsonl filename.

        Returns None if the filename does not match the expected pattern.
        """
        stem = Path(filename).stem
        try:
            return datetime.strptime(stem, "%Y-%m-%d").date()
        except ValueError:
            return None

    @staticmethod
    def _remove_empty_dirs(root: Path, stop_at: Path) -> None:
        """Remove empty directories under root, but do not remove root itself.

        Walks bottom-up so that a directory is only considered after its
        contents have been processed.
        """
        for dirpath in sorted(root.rglob("*"), reverse=True):
            if dirpath == stop_at or not dirpath.is_dir():
                continue
            # Skip anything inside _archive — we do not want to clean that.
            try:
                dirpath.relative_to(stop_at / "_archive")
                continue
            except ValueError:
                pass
            try:
                dirpath.rmdir()  # Only succeeds when directory is empty.
            except OSError:
                pass
