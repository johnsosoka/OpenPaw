"""Token usage and invocation metrics tracking for OpenPaw agents."""

import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


@dataclass
class InvocationMetrics:
    """Token usage metrics from a single agent invocation.

    Aggregates token counts across all LLM calls within a single agent run.
    Extracted from LangChain UsageMetadataCallbackHandler or AIMessage metadata.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    duration_ms: float = 0.0
    model: str = ""
    is_partial: bool = False


def extract_metrics_from_callback(
    callback_handler: Any,
    duration_ms: float,
    model_id: str,
) -> InvocationMetrics:
    """Extract metrics from UsageMetadataCallbackHandler after an agent run.

    Args:
        callback_handler: UsageMetadataCallbackHandler instance with usage_metadata attribute.
        duration_ms: Wall-clock duration of the agent invocation.
        model_id: Model identifier used for this invocation.

    Returns:
        InvocationMetrics with aggregated token counts and metadata.

    Notes:
        - Handles missing or empty usage_metadata gracefully (returns zeroed metrics).
        - Aggregates across all models if multiple model calls occurred.
        - llm_calls is inferred from the number of models in usage_metadata.
    """
    metrics = InvocationMetrics(duration_ms=duration_ms, model=model_id)

    # Check if callback has usage_metadata attribute
    if not hasattr(callback_handler, "usage_metadata"):
        logger.debug(
            "Callback handler has no usage_metadata attribute "
            "(provider may not support token tracking)"
        )
        return metrics

    usage_metadata = callback_handler.usage_metadata

    # Handle None or empty metadata
    if not usage_metadata:
        logger.debug(
            "Callback handler usage_metadata is empty "
            "(provider may not report token counts)"
        )
        return metrics

    # Aggregate across all models in usage_metadata
    # Format: {"model_name": {"input_tokens": int, "output_tokens": int, "total_tokens": int}}
    for model_name, model_usage in usage_metadata.items():
        if not isinstance(model_usage, dict):
            logger.warning(
                f"Unexpected usage_metadata format for model '{model_name}': {model_usage}"
            )
            metrics.is_partial = True
            continue

        metrics.input_tokens += model_usage.get("input_tokens", 0)
        metrics.output_tokens += model_usage.get("output_tokens", 0)
        metrics.total_tokens += model_usage.get("total_tokens", 0)
        metrics.llm_calls += 1

    # Validate totals (some providers may report incorrect sums)
    if metrics.total_tokens == 0 and (metrics.input_tokens > 0 or metrics.output_tokens > 0):
        metrics.total_tokens = metrics.input_tokens + metrics.output_tokens

    return metrics


class TokenUsageLogger:
    """Append-only JSONL logger for token usage metrics.

    Logs each agent invocation to {workspace}/.openpaw/token_usage.jsonl
    for session-level and workspace-level token tracking.
    """

    def __init__(self, workspace_path: Path) -> None:
        """Initialize the logger.

        Args:
            workspace_path: Path to the workspace directory.
        """
        self._workspace_path = Path(workspace_path)
        self._log_path = self._workspace_path / ".openpaw" / "token_usage.jsonl"
        self._lock = threading.Lock()

    def log(
        self,
        metrics: InvocationMetrics,
        workspace: str,
        invocation_type: str,
        session_key: str | None = None,
    ) -> None:
        """Append a token usage entry to the JSONL log.

        Args:
            metrics: Token usage metrics from the invocation.
            workspace: Workspace name.
            invocation_type: Type of invocation ("user", "cron", "heartbeat").
            session_key: Session key for user invocations (optional).
        """
        try:
            # Build log entry outside lock
            entry = {
                "timestamp": datetime.now(UTC).isoformat(),
                "workspace": workspace,
                "invocation_type": invocation_type,
                "session_key": session_key,
                "input_tokens": metrics.input_tokens,
                "output_tokens": metrics.output_tokens,
                "total_tokens": metrics.total_tokens,
                "llm_calls": metrics.llm_calls,
                "duration_ms": metrics.duration_ms,
                "model": metrics.model,
            }
            line = json.dumps(entry) + "\n"

            with self._lock:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._log_path, "a") as f:
                    f.write(line)

        except Exception as e:
            logger.warning(f"Failed to log token usage: {e}")


class TokenUsageReader:
    """Read and aggregate token usage from JSONL log."""

    def __init__(self, workspace_path: Path) -> None:
        """Initialize the reader.

        Args:
            workspace_path: Path to the workspace directory.
        """
        self._workspace_path = Path(workspace_path)
        self._log_path = self._workspace_path / ".openpaw" / "token_usage.jsonl"

    def tokens_today(self, timezone_str: str = "UTC") -> InvocationMetrics:
        """Aggregate all entries from today in the specified timezone.

        Args:
            timezone_str: IANA timezone string (e.g., "America/Denver").
                         Defaults to "UTC" for backward compatibility.

        Returns:
            Aggregated metrics for today's invocations.
        """
        if not self._log_path.exists():
            return InvocationMetrics()

        # Get today's date in the specified timezone
        timezone = ZoneInfo(timezone_str)
        today = datetime.now(timezone).date()
        aggregated = InvocationMetrics()

        try:
            with open(self._log_path) as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        # Parse timestamp and check if it's today in workspace timezone
                        timestamp = datetime.fromisoformat(entry["timestamp"])
                        # Convert to workspace timezone before comparing dates
                        entry_date = timestamp.astimezone(timezone).date()
                        if entry_date == today:
                            aggregated.input_tokens += entry.get("input_tokens", 0)
                            aggregated.output_tokens += entry.get("output_tokens", 0)
                            aggregated.total_tokens += entry.get("total_tokens", 0)
                            aggregated.llm_calls += entry.get("llm_calls", 0)
                            aggregated.duration_ms += entry.get("duration_ms", 0.0)
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.debug(f"Skipping malformed log entry: {e}")
                        continue
        except Exception as e:
            logger.warning(f"Failed to read token usage log: {e}")

        return aggregated

    def tokens_for_session(self, session_key: str, timezone_str: str = "UTC") -> InvocationMetrics:
        """Aggregate entries matching a session key from today in the specified timezone.

        Args:
            session_key: Session key to filter by.
            timezone_str: IANA timezone string (e.g., "America/Denver").
                         Defaults to "UTC" for backward compatibility.

        Returns:
            Aggregated metrics for the session from today.
        """
        if not self._log_path.exists():
            return InvocationMetrics()

        # Get today's date in the specified timezone
        timezone = ZoneInfo(timezone_str)
        today = datetime.now(timezone).date()
        aggregated = InvocationMetrics()

        try:
            with open(self._log_path) as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        # Parse timestamp and check if it's today in workspace timezone
                        timestamp = datetime.fromisoformat(entry["timestamp"])
                        # Convert to workspace timezone before comparing dates
                        entry_date = timestamp.astimezone(timezone).date()
                        if entry_date == today and entry.get("session_key") == session_key:
                            aggregated.input_tokens += entry.get("input_tokens", 0)
                            aggregated.output_tokens += entry.get("output_tokens", 0)
                            aggregated.total_tokens += entry.get("total_tokens", 0)
                            aggregated.llm_calls += entry.get("llm_calls", 0)
                            aggregated.duration_ms += entry.get("duration_ms", 0.0)
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.debug(f"Skipping malformed log entry: {e}")
                        continue
        except Exception as e:
            logger.warning(f"Failed to read token usage log: {e}")

        return aggregated
