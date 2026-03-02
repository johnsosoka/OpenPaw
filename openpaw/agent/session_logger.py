"""Session logging for scheduled agent runs (heartbeat, cron, subagent)."""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openpaw.agent.metrics import InvocationMetrics
from openpaw.core.paths import MEMORY_LOGS_DIR

logger = logging.getLogger(__name__)


@dataclass
class SessionRecord:
    """A single entry in a session JSONL file."""

    type: str  # "prompt", "response", "metadata"
    timestamp: str  # ISO 8601
    content: str | None = None
    tools_used: list[str] | None = None
    metrics: dict[str, Any] | None = None
    duration_ms: float | None = None


class SessionLogger:
    """Writes agent session data to JSONL files.

    Session files are stored at:
        {workspace_path}/memory/logs/{session_type}/{name}_{timestamp}.jsonl

    These are readable by the main agent via read_file().
    """

    def __init__(self, workspace_path: Path, session_type: str):
        """Initialize session logger.

        Args:
            workspace_path: Path to the workspace root directory.
            session_type: Type of session (heartbeat, cron, subagent).
        """
        self._workspace_path = Path(workspace_path)
        self._session_type = session_type
        self._sessions_dir = self._workspace_path / str(MEMORY_LOGS_DIR) / session_type
        self._current_path: Path | None = None

    def _ensure_dir(self) -> None:
        """Create session directory if it doesn't exist."""
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, name: str) -> Path:
        """Create a new session file. Returns the ABSOLUTE file path.

        Naming: {name}_{YYYY-MM-DD}T{HH-MM-SS}.jsonl

        Args:
            name: Session name (e.g., "heartbeat", cron job name).

        Returns:
            Absolute path to the created session file.
        """
        self._ensure_dir()
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"{name}_{timestamp}.jsonl"
        self._current_path = self._sessions_dir / filename
        return self._current_path

    def write_record(self, record: SessionRecord) -> None:
        """Append a record to the current session file.

        Args:
            record: SessionRecord to write.

        Raises:
            RuntimeError: If no session has been created yet.
        """
        if not self._current_path:
            raise RuntimeError("No active session. Call create_session() first.")

        data: dict[str, Any] = {"type": record.type, "timestamp": record.timestamp}
        if record.content is not None:
            data["content"] = record.content
        if record.tools_used is not None:
            data["tools_used"] = record.tools_used
        if record.metrics is not None:
            data["metrics"] = record.metrics
        if record.duration_ms is not None:
            data["duration_ms"] = record.duration_ms

        try:
            with self._current_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(data) + "\n")
        except OSError as e:
            logger.warning(f"Failed to write session record: {e}")

    def write_session(
        self,
        name: str,
        prompt: str,
        response: str,
        tools_used: list[str],
        metrics: InvocationMetrics | None,
        duration_ms: float,
    ) -> str:
        """Convenience: write a complete session in one call.

        Writes three records: prompt, response, metadata.

        Args:
            name: Session name for the file.
            prompt: The prompt sent to the agent.
            response: The agent's response.
            tools_used: List of tool names invoked.
            metrics: Token usage metrics (may be None).
            duration_ms: Total duration in milliseconds.

        Returns:
            Relative path to the session file (relative to workspace root),
            suitable for read_file() by the main agent.
        """
        self.create_session(name)
        now = datetime.now(UTC).isoformat()

        # Write prompt record
        self.write_record(
            SessionRecord(
                type="prompt",
                timestamp=now,
                content=prompt,
            )
        )

        # Write response record
        self.write_record(
            SessionRecord(
                type="response",
                timestamp=now,
                content=response,
            )
        )

        # Build metrics dict
        metrics_dict: dict[str, Any] | None = None
        if metrics:
            metrics_dict = {
                "input_tokens": metrics.input_tokens,
                "output_tokens": metrics.output_tokens,
                "total_tokens": metrics.total_tokens,
                "llm_calls": metrics.llm_calls,
            }

        # Write metadata record
        self.write_record(
            SessionRecord(
                type="metadata",
                timestamp=now,
                tools_used=tools_used if tools_used else None,
                metrics=metrics_dict,
                duration_ms=round(duration_ms, 1),
            )
        )

        # Return relative path for read_file() compatibility
        try:
            return str(self._current_path.relative_to(self._workspace_path))
        except ValueError:
            # Fallback to absolute if relative fails
            return str(self._current_path)
