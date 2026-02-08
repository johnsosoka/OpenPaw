"""Sub-agent storage for managing spawned background agents.

This module handles persistence of sub-agent requests and results, allowing
parent agents to spawn background tasks and retrieve their outputs.
"""

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class SubAgentStatus(StrEnum):
    """Status values for sub-agent lifecycle.

    Lifecycle flow:
        pending -> running -> completed
        pending -> running -> failed
        any -> cancelled
        running (stale) -> timed_out
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass
class SubAgentRequest:
    """Represents a sub-agent spawn request.

    Attributes:
        id: Unique identifier (UUID or tool-generated).
        task: The prompt/instruction for the sub-agent.
        label: Human-readable label for the request.
        status: Current request status (pending, running, etc.).
        session_key: Session for result delivery routing (channel:id).
        created_at: When the request was created.
        started_at: When the sub-agent began execution.
        completed_at: When the sub-agent finished.
        timeout_minutes: Maximum runtime before timeout.
        notify: Whether to notify session on completion.
    """

    id: str
    task: str
    label: str
    status: SubAgentStatus
    session_key: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    timeout_minutes: int = 30
    notify: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with ISO 8601 datetime strings.

        Returns:
            Dictionary representation suitable for YAML serialization.
        """
        data = asdict(self)

        # Convert enum to string
        data["status"] = self.status.value

        # Convert datetimes to ISO 8601 strings
        data["created_at"] = self.created_at.isoformat()
        if self.started_at:
            data["started_at"] = self.started_at.isoformat()
        if self.completed_at:
            data["completed_at"] = self.completed_at.isoformat()

        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubAgentRequest":
        """Create instance from dictionary with ISO 8601 datetime strings.

        Args:
            data: Dictionary from YAML file.

        Returns:
            SubAgentRequest instance with parsed enums and datetimes.
        """
        # Parse enum
        status = SubAgentStatus(data["status"])

        # Parse datetimes
        created_at = datetime.fromisoformat(data["created_at"])
        started_at = datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
        completed_at = datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None

        return cls(
            id=data["id"],
            task=data["task"],
            label=data["label"],
            status=status,
            session_key=data["session_key"],
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            timeout_minutes=data.get("timeout_minutes", 30),
            notify=data.get("notify", True),
        )


@dataclass
class SubAgentResult:
    """Represents the result of a sub-agent execution.

    Attributes:
        request_id: ID of the corresponding SubAgentRequest.
        output: The sub-agent's response text.
        token_count: Total tokens used during execution.
        duration_ms: Execution time in milliseconds.
        error: Error message if execution failed.
    """

    request_id: str
    output: str
    token_count: int = 0
    duration_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation suitable for YAML serialization.
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubAgentResult":
        """Create instance from dictionary.

        Args:
            data: Dictionary from YAML file.

        Returns:
            SubAgentResult instance.
        """
        return cls(
            request_id=data["request_id"],
            output=data["output"],
            token_count=data.get("token_count", 0),
            duration_ms=data.get("duration_ms", 0.0),
            error=data.get("error"),
        )


class SubAgentStore:
    """Manages persistent storage of sub-agent state in .openpaw/subagents.yaml.

    Provides CRUD operations for sub-agent requests and results with thread-safe
    file access. State is stored in YAML format at {workspace}/.openpaw/subagents.yaml.

    Example:
        >>> store = SubAgentStore(Path("agent_workspaces/gilfoyle"))
        >>> request = SubAgentRequest(
        ...     id=str(uuid.uuid4()),
        ...     task="Research topic X",
        ...     label="research-x",
        ...     status=SubAgentStatus.PENDING,
        ...     session_key="telegram:12345"
        ... )
        >>> store.create(request)
        >>> store.update_status(request.id, SubAgentStatus.RUNNING)
        >>> result = SubAgentResult(request_id=request.id, output="Here are the findings...")
        >>> store.save_result(result)
    """

    STORAGE_FILENAME = ".openpaw/subagents.yaml"
    MAX_RESULT_SIZE = 50_000  # 50K char truncation (consistent with read_file 100K valve)
    VERSION = 1

    def __init__(self, workspace_path: Path, max_age_hours: int = 24):
        """Initialize the sub-agent store.

        Args:
            workspace_path: Path to the agent workspace root.
            max_age_hours: Maximum age in hours for completed records.
        """
        self.workspace_path = Path(workspace_path)
        self.max_age_hours = max_age_hours
        self.storage_file = self.workspace_path / self.STORAGE_FILENAME
        self._lock = Lock()

        # Ensure .openpaw directory exists
        storage_dir = self.storage_file.parent
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Clean up stale records on initialization
        self.cleanup_stale()

        logger.info(f"SubAgentStore initialized: {self.storage_file}")

    def _load_unlocked(self) -> dict[str, Any]:
        """Load raw YAML data from storage. Caller must hold self._lock.

        Returns:
            Dictionary with 'version', 'last_updated', 'requests', and 'results' keys.
            Returns default structure if file doesn't exist.
        """
        if not self.storage_file.exists():
            logger.debug(f"Storage file does not exist: {self.storage_file}")
            return {
                "version": self.VERSION,
                "last_updated": datetime.now(UTC).isoformat(),
                "requests": [],
                "results": []
            }

        try:
            with self.storage_file.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                logger.error(f"Invalid storage format (expected dict): {self.storage_file}")
                return {
                    "version": self.VERSION,
                    "last_updated": datetime.now(UTC).isoformat(),
                    "requests": [],
                    "results": []
                }

            # Ensure required keys exist
            if "requests" not in data:
                data["requests"] = []
            if "results" not in data:
                data["results"] = []
            if "version" not in data:
                data["version"] = self.VERSION

            logger.debug(f"Loaded {len(data.get('requests', []))} request(s) from storage")
            return data

        except yaml.YAMLError as e:
            logger.error(f"Corrupted storage file {self.storage_file}: {e}")
            return {
                "version": self.VERSION,
                "last_updated": datetime.now(UTC).isoformat(),
                "requests": [],
                "results": []
            }
        except Exception as e:
            logger.error(f"Unexpected error loading {self.storage_file}: {e}", exc_info=True)
            return {
                "version": self.VERSION,
                "last_updated": datetime.now(UTC).isoformat(),
                "requests": [],
                "results": []
            }

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        """Persist YAML data to storage. Caller must hold self._lock.

        Args:
            data: Dictionary with version, last_updated, requests, and results.
        """
        try:
            # Update timestamp
            data["last_updated"] = datetime.now(UTC).isoformat()

            # Atomic write: write to temp file, then rename
            temp_file = self.storage_file.with_suffix(".tmp")

            with temp_file.open("w", encoding="utf-8") as f:
                yaml.dump(
                    data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                    indent=2
                )

            # Atomic rename (POSIX guarantees atomicity)
            temp_file.replace(self.storage_file)

            logger.debug(f"Saved {len(data.get('requests', []))} request(s) to storage")

        except Exception as e:
            logger.error(f"Failed to save sub-agent state to {self.storage_file}: {e}", exc_info=True)
            raise

    def create(self, request: SubAgentRequest) -> None:
        """Create a new sub-agent request and persist immediately.

        Args:
            request: SubAgentRequest instance to create.

        Raises:
            ValueError: If a request with the same ID already exists.
        """
        with self._lock:
            data = self._load_unlocked()

            # Check for duplicate ID
            if any(r["id"] == request.id for r in data["requests"]):
                raise ValueError(f"SubAgentRequest with ID {request.id} already exists")

            data["requests"].append(request.to_dict())
            self._save_unlocked(data)

        logger.info(f"Created sub-agent request: {request.id} ({request.label}, {request.status.value})")

    def update_status(self, request_id: str, status: SubAgentStatus, **kwargs: Any) -> bool:
        """Update a sub-agent request's status and optional fields.

        Args:
            request_id: Unique request identifier.
            status: New status value.
            **kwargs: Additional fields to update (started_at, completed_at, etc.).

        Returns:
            True if request was found and updated, False otherwise.

        Example:
            >>> store.update_status(
            ...     "req-123",
            ...     SubAgentStatus.COMPLETED,
            ...     completed_at=datetime.now(UTC)
            ... )
        """
        with self._lock:
            data = self._load_unlocked()

            for i, request_data in enumerate(data["requests"]):
                if request_data["id"] == request_id:
                    # Load existing request
                    request = SubAgentRequest.from_dict(request_data)

                    # Update status
                    request.status = status

                    # Update additional fields
                    for key, value in kwargs.items():
                        if hasattr(request, key):
                            setattr(request, key, value)
                        else:
                            logger.warning(f"Ignoring unknown field: {key}")

                    # Replace in data
                    data["requests"][i] = request.to_dict()
                    self._save_unlocked(data)

                    logger.info(f"Updated sub-agent request: {request_id} -> {status.value}")
                    return True

        logger.warning(f"Sub-agent request not found for update: {request_id}")
        return False

    def save_result(self, result: SubAgentResult) -> bool:
        """Save sub-agent result (truncates output if too large).

        Args:
            result: SubAgentResult instance to save.

        Returns:
            True if result was saved (request exists), False otherwise.
        """
        with self._lock:
            data = self._load_unlocked()

            # Verify request exists
            if not any(r["id"] == result.request_id for r in data["requests"]):
                logger.warning(f"Cannot save result: request {result.request_id} not found")
                return False

            # Truncate output if too large
            if len(result.output) > self.MAX_RESULT_SIZE:
                logger.warning(
                    f"Truncating result output from {len(result.output)} to {self.MAX_RESULT_SIZE} chars"
                )
                result.output = result.output[:self.MAX_RESULT_SIZE] + "\n\n[Output truncated]"

            # Remove existing result for this request (if any)
            data["results"] = [r for r in data["results"] if r["request_id"] != result.request_id]

            # Add new result
            data["results"].append(result.to_dict())
            self._save_unlocked(data)

        logger.info(f"Saved sub-agent result for request: {result.request_id}")
        return True

    def get(self, request_id: str) -> SubAgentRequest | None:
        """Retrieve a single sub-agent request by ID.

        Args:
            request_id: Unique request identifier.

        Returns:
            SubAgentRequest instance if found, None otherwise.
        """
        with self._lock:
            data = self._load_unlocked()

        for request_data in data["requests"]:
            if request_data["id"] == request_id:
                return SubAgentRequest.from_dict(request_data)

        return None

    def get_result(self, request_id: str) -> SubAgentResult | None:
        """Retrieve a sub-agent result by request ID.

        Args:
            request_id: Unique request identifier.

        Returns:
            SubAgentResult instance if found, None otherwise.
        """
        with self._lock:
            data = self._load_unlocked()

        for result_data in data["results"]:
            if result_data["request_id"] == request_id:
                return SubAgentResult.from_dict(result_data)

        return None

    def list_active(self) -> list[SubAgentRequest]:
        """List all active sub-agent requests (pending or running).

        Returns:
            List of SubAgentRequest instances with pending or running status.
        """
        with self._lock:
            data = self._load_unlocked()

        requests = []

        for request_data in data["requests"]:
            try:
                request = SubAgentRequest.from_dict(request_data)

                # Only include pending or running
                if request.status in (SubAgentStatus.PENDING, SubAgentStatus.RUNNING):
                    requests.append(request)
            except Exception as e:
                logger.error(f"Failed to parse request {request_data.get('id', 'unknown')}: {e}")
                continue

        return requests

    def list_recent(self, limit: int = 10) -> list[SubAgentRequest]:
        """List recent sub-agent requests (all statuses, sorted by created_at desc).

        Args:
            limit: Maximum number of requests to return.

        Returns:
            List of SubAgentRequest instances, most recent first.
        """
        with self._lock:
            data = self._load_unlocked()

        requests = []

        for request_data in data["requests"]:
            try:
                request = SubAgentRequest.from_dict(request_data)
                requests.append(request)
            except Exception as e:
                logger.error(f"Failed to parse request {request_data.get('id', 'unknown')}: {e}")
                continue

        # Sort by created_at descending
        requests.sort(key=lambda r: r.created_at, reverse=True)

        return requests[:limit]

    def cleanup_stale(self) -> int:
        """Remove old completed records and mark stale running/pending as failed.

        Prunes:
        - Completed/failed/cancelled/timed_out requests older than max_age_hours
        - Marks running/pending requests exceeding timeout_minutes as timed_out

        Returns:
            Number of records removed.
        """
        with self._lock:
            data = self._load_unlocked()
            now = datetime.now(UTC)
            cutoff = now - timedelta(hours=self.max_age_hours)

            initial_count = len(data["requests"])
            marked_stale = 0

            # Mark stale running/pending as timed_out
            for request_data in data["requests"]:
                try:
                    request = SubAgentRequest.from_dict(request_data)

                    # Check if running/pending and past timeout
                    if request.status in (SubAgentStatus.PENDING, SubAgentStatus.RUNNING):
                        timeout_delta = timedelta(minutes=request.timeout_minutes)
                        if now - request.created_at > timeout_delta:
                            logger.info(f"Marking stale request as timed_out: {request.id}")
                            request.status = SubAgentStatus.TIMED_OUT
                            request.completed_at = now
                            marked_stale += 1

                            # Update in data
                            for i, r in enumerate(data["requests"]):
                                if r["id"] == request.id:
                                    data["requests"][i] = request.to_dict()
                                    break
                except Exception as e:
                    logger.error(f"Failed to check request staleness: {e}")
                    continue

            # Remove old completed records
            data["requests"] = [
                r for r in data["requests"]
                if (
                    r["status"] not in ["completed", "failed", "cancelled", "timed_out"]
                    or (
                        r.get("completed_at")
                        and datetime.fromisoformat(r["completed_at"]) >= cutoff
                    )
                )
            ]

            # Remove orphaned results (no corresponding request)
            request_ids = {r["id"] for r in data["requests"]}
            data["results"] = [r for r in data["results"] if r["request_id"] in request_ids]

            removed = initial_count - len(data["requests"])

            # Save if anything changed (marked stale or removed)
            if marked_stale > 0 or removed > 0:
                self._save_unlocked(data)
                parts = []
                if marked_stale > 0:
                    parts.append(f"marked {marked_stale} stale")
                if removed > 0:
                    parts.append(f"removed {removed} old")
                logger.info(f"Sub-agent cleanup: {', '.join(parts)}")

        return removed


def create_subagent_request(
    task: str,
    label: str,
    session_key: str,
    status: SubAgentStatus = SubAgentStatus.PENDING,
    timeout_minutes: int = 30,
    notify: bool = True,
) -> SubAgentRequest:
    """Factory function for creating a new sub-agent request with auto-generated ID.

    Args:
        task: The prompt/instruction for the sub-agent.
        label: Human-readable label for the request.
        session_key: Session for result delivery routing.
        status: Initial request status (default: pending).
        timeout_minutes: Maximum runtime before timeout.
        notify: Whether to notify session on completion.

    Returns:
        SubAgentRequest instance with unique ID.

    Example:
        >>> request = create_subagent_request(
        ...     task="Research topic X",
        ...     label="research-x",
        ...     session_key="telegram:12345",
        ...     timeout_minutes=60
        ... )
    """
    return SubAgentRequest(
        id=str(uuid.uuid4()),
        task=task,
        label=label,
        status=status,
        session_key=session_key,
        timeout_minutes=timeout_minutes,
        notify=notify,
    )
