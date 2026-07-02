"""Status event bus and sinks (ADR-106 Phase A).

``StatusBus`` fans events out from producers to pluggable sinks. Delivery is
best-effort: a failing sink is debug-logged and skipped — status plumbing
must never break an agent run (same philosophy as channel logging).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path

from openpaw.core.paths import MEMORY_LOGS_DIR
from openpaw.model.status_event import StatusEvent, StatusSink

logger = logging.getLogger(__name__)


class NullStatusEmitter:
    """No-op emitter so producers can take a StatusEmitter unconditionally."""

    async def emit(self, event: StatusEvent) -> None:
        """Discard the event."""
        return None


class StatusBus:
    """Per-workspace fan-out from emitters to sinks.

    Sink order is delivery order. A failing sink is logged at debug and
    skipped; the bus never raises into the caller.
    """

    def __init__(self, workspace: str) -> None:
        """Initialize the bus.

        Args:
            workspace: Owning workspace name (for log context).
        """
        self._workspace = workspace
        self._sinks: list[StatusSink] = []

    def add_sink(self, sink: StatusSink) -> None:
        """Register a sink; order is delivery order."""
        self._sinks.append(sink)

    async def emit(self, event: StatusEvent) -> None:
        """Fan out to every sink; contain all sink failures."""
        for sink in self._sinks:
            try:
                await sink.handle(event)
            except Exception:
                logger.debug(
                    "Status sink %s failed for %s (workspace=%s)",
                    type(sink).__name__,
                    event.kind,
                    self._workspace,
                    exc_info=True,
                )


class SessionLogSink:
    """Appends status events as JSONL to the workspace session-log area.

    Design choice: a single rolling file at
    ``{workspace}/memory/logs/events/status_events.jsonl`` — mirroring the
    SessionLogger layout (``memory/logs/{type}/``) while keeping the sink a
    trivial append. The ``run_id`` field on each line provides per-run
    correlation, so per-run files are unnecessary.

    Writes are tiny appends done via ``asyncio.to_thread`` guarded by a
    ``threading.Lock`` (repo convention for file persistence).
    """

    def __init__(self, workspace_path: Path) -> None:
        """Initialize the sink.

        Args:
            workspace_path: Path to the workspace root directory.
        """
        self._path = (
            Path(workspace_path) / str(MEMORY_LOGS_DIR) / "events" / "status_events.jsonl"
        )
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        """Absolute path of the JSONL file this sink writes to."""
        return self._path

    async def handle(self, event: StatusEvent) -> None:
        """Serialize the event and append it as one JSONL line."""
        line = json.dumps(
            {
                "kind": str(event.kind),
                "workspace": event.workspace,
                "session_key": event.session_key,
                "run_id": event.run_id,
                "node": event.node,
                "payload": event.payload,
                "ts": event.ts.isoformat(),
            }
        )
        await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
