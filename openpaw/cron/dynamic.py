"""Dynamic cron storage for agent self-scheduling.

This module handles persistence of dynamically-created scheduled tasks,
allowing agents to schedule their own follow-up actions at runtime.
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DynamicCronTask:
    """Represents a dynamically scheduled task created by an agent.

    Task Types:
        - once: Executes at a specific datetime (run_at)
        - interval: Executes repeatedly every N seconds (interval_seconds)
    """

    id: str
    task_type: str
    prompt: str
    created_at: datetime
    run_at: datetime | None = None
    interval_seconds: int | None = None
    next_run: datetime | None = None
    channel: str | None = None  # Channel to route response to (e.g., "telegram")
    chat_id: int | None = None  # Chat ID for routing response

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with ISO 8601 datetime strings."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        if self.run_at:
            data["run_at"] = self.run_at.isoformat()
        if self.next_run:
            data["next_run"] = self.next_run.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DynamicCronTask":
        """Create instance from dictionary with ISO 8601 datetime strings."""
        return cls(
            id=data["id"],
            task_type=data["task_type"],
            prompt=data["prompt"],
            created_at=datetime.fromisoformat(data["created_at"]),
            run_at=datetime.fromisoformat(data["run_at"]) if data.get("run_at") else None,
            interval_seconds=data.get("interval_seconds"),
            next_run=datetime.fromisoformat(data["next_run"]) if data.get("next_run") else None,
            channel=data.get("channel"),
            chat_id=data.get("chat_id"),
        )


class DynamicCronStore:
    """Manages persistent storage of dynamically scheduled agent tasks.

    Stores tasks in JSON format at {workspace_path}/dynamic_crons.json.
    Thread-safe with file locking for concurrent access.
    """

    STORAGE_FILENAME = "dynamic_crons.json"

    def __init__(self, workspace_path: Path):
        """Initialize the dynamic cron store.

        Args:
            workspace_path: Path to the agent workspace root.
        """
        self.workspace_path = Path(workspace_path)
        self.storage_file = self.workspace_path / self.STORAGE_FILENAME
        self._lock = Lock()

        # Ensure workspace directory exists
        self.workspace_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"DynamicCronStore initialized: {self.storage_file}")

    def load(self) -> list[DynamicCronTask]:
        """Load all tasks from storage.

        Returns:
            List of DynamicCronTask objects. Returns empty list if file doesn't exist
            or is corrupted.
        """
        with self._lock:
            if not self.storage_file.exists():
                logger.debug(f"Storage file does not exist: {self.storage_file}")
                return []

            try:
                with self.storage_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)

                if not isinstance(data, list):
                    logger.error(f"Invalid storage format (expected list): {self.storage_file}")
                    return []

                tasks = [DynamicCronTask.from_dict(task_data) for task_data in data]
                logger.info(f"Loaded {len(tasks)} dynamic cron task(s) from storage")
                return tasks

            except json.JSONDecodeError as e:
                logger.error(f"Corrupted storage file {self.storage_file}: {e}")
                return []
            except (KeyError, ValueError) as e:
                logger.error(f"Invalid task data in {self.storage_file}: {e}")
                return []
            except Exception as e:
                logger.error(f"Unexpected error loading {self.storage_file}: {e}", exc_info=True)
                return []

    def save(self, tasks: list[DynamicCronTask]) -> None:
        """Persist tasks to storage.

        Args:
            tasks: List of DynamicCronTask objects to save.
        """
        with self._lock:
            try:
                data = [task.to_dict() for task in tasks]

                # Atomic write: write to temp file, then rename
                temp_file = self.storage_file.with_suffix(".tmp")

                with temp_file.open("w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

                # Atomic rename (POSIX guarantees atomicity)
                temp_file.replace(self.storage_file)

                logger.info(f"Saved {len(tasks)} dynamic cron task(s) to storage")

            except Exception as e:
                logger.error(f"Failed to save tasks to {self.storage_file}: {e}", exc_info=True)
                raise

    def add_task(self, task: DynamicCronTask) -> None:
        """Add a new task and persist immediately.

        Args:
            task: DynamicCronTask to add.
        """
        tasks = self.load()
        tasks.append(task)
        self.save(tasks)
        logger.info(f"Added dynamic cron task: {task.id} ({task.task_type})")

    def remove_task(self, task_id: str) -> bool:
        """Remove a task by ID and persist immediately.

        Args:
            task_id: Unique task ID to remove.

        Returns:
            True if task was found and removed, False otherwise.
        """
        tasks = self.load()
        initial_count = len(tasks)
        tasks = [t for t in tasks if t.id != task_id]

        if len(tasks) < initial_count:
            self.save(tasks)
            logger.info(f"Removed dynamic cron task: {task_id}")
            return True

        logger.warning(f"Task not found for removal: {task_id}")
        return False

    def list_tasks(self) -> list[DynamicCronTask]:
        """Return all tasks from storage.

        Returns:
            List of all DynamicCronTask objects.
        """
        return self.load()

    def get_task(self, task_id: str) -> DynamicCronTask | None:
        """Get a single task by ID.

        Args:
            task_id: Unique task ID to retrieve.

        Returns:
            DynamicCronTask if found, None otherwise.
        """
        tasks = self.load()
        for task in tasks:
            if task.id == task_id:
                return task
        return None

    def update_task(self, task: DynamicCronTask) -> bool:
        """Update an existing task and persist immediately.

        Replaces the task with matching ID.

        Args:
            task: DynamicCronTask with updated data.

        Returns:
            True if task was found and updated, False otherwise.
        """
        tasks = self.load()
        updated = False

        for i, existing_task in enumerate(tasks):
            if existing_task.id == task.id:
                tasks[i] = task
                updated = True
                break

        if updated:
            self.save(tasks)
            logger.info(f"Updated dynamic cron task: {task.id}")
            return True

        logger.warning(f"Task not found for update: {task.id}")
        return False


def create_once_task(
    prompt: str,
    run_at: datetime,
    channel: str | None = None,
    chat_id: int | None = None,
) -> DynamicCronTask:
    """Factory function for creating a one-time scheduled task.

    Args:
        prompt: User prompt to inject when task fires.
        run_at: Datetime when the task should execute.
        channel: Channel to route response to (e.g., "telegram").
        chat_id: Chat ID for routing response.

    Returns:
        DynamicCronTask configured for one-time execution.
    """
    return DynamicCronTask(
        id=str(uuid.uuid4()),
        task_type="once",
        prompt=prompt,
        created_at=datetime.now(),
        run_at=run_at,
        channel=channel,
        chat_id=chat_id,
    )


def create_interval_task(
    prompt: str,
    interval_seconds: int,
    next_run: datetime,
    channel: str | None = None,
    chat_id: int | None = None,
) -> DynamicCronTask:
    """Factory function for creating a recurring interval task.

    Args:
        prompt: User prompt to inject when task fires.
        interval_seconds: Seconds between executions.
        next_run: Datetime of the first execution.
        channel: Channel to route response to (e.g., "telegram").
        chat_id: Chat ID for routing response.

    Returns:
        DynamicCronTask configured for recurring execution.
    """
    return DynamicCronTask(
        id=str(uuid.uuid4()),
        task_type="interval",
        prompt=prompt,
        created_at=datetime.now(),
        interval_seconds=interval_seconds,
        next_run=next_run,
        channel=channel,
        chat_id=chat_id,
    )
