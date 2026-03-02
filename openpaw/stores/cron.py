"""Dynamic cron storage for agent self-scheduling.

This module handles persistence of dynamically-created scheduled tasks,
allowing agents to schedule their own follow-up actions at runtime.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from openpaw.core.paths import DYNAMIC_CRONS_JSON
from openpaw.model.cron import DynamicCronTask

logger = logging.getLogger(__name__)


class DynamicCronStore:
    """Manages persistent storage of dynamically scheduled agent tasks.

    Stores tasks in JSON format at {workspace_path}/data/dynamic_crons.json.
    Thread-safe with file locking for concurrent access.
    """

    def __init__(self, workspace_path: Path):
        """Initialize the dynamic cron store.

        Args:
            workspace_path: Path to the agent workspace root.
        """
        self.workspace_path = Path(workspace_path)
        self.storage_file = self.workspace_path / str(DYNAMIC_CRONS_JSON)
        self._lock = Lock()

        # Ensure the data/ directory exists
        self.storage_file.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"DynamicCronStore initialized: {self.storage_file}")

    def _load_unlocked(self) -> list[DynamicCronTask]:
        """Load all tasks from storage. Caller must hold self._lock.

        Returns:
            List of DynamicCronTask objects. Returns empty list if file doesn't exist
            or is corrupted.
        """
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

    def load(self) -> list[DynamicCronTask]:
        """Load all tasks from storage (thread-safe).

        Returns:
            List of DynamicCronTask objects. Returns empty list if file doesn't exist
            or is corrupted.
        """
        with self._lock:
            return self._load_unlocked()

    def _save_unlocked(self, tasks: list[DynamicCronTask]) -> None:
        """Persist tasks to storage. Caller must hold self._lock.

        Args:
            tasks: List of DynamicCronTask objects to save.
        """
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

    def save(self, tasks: list[DynamicCronTask]) -> None:
        """Persist tasks to storage (thread-safe).

        Args:
            tasks: List of DynamicCronTask objects to save.
        """
        with self._lock:
            self._save_unlocked(tasks)

    def add_task(self, task: DynamicCronTask) -> None:
        """Add a new task and persist immediately.

        Args:
            task: DynamicCronTask to add.
        """
        with self._lock:
            tasks = self._load_unlocked()
            tasks.append(task)
            self._save_unlocked(tasks)
        logger.info(f"Added dynamic cron task: {task.id} ({task.task_type})")

    def remove_task(self, task_id: str) -> bool:
        """Remove a task by ID and persist immediately.

        Args:
            task_id: Unique task ID to remove.

        Returns:
            True if task was found and removed, False otherwise.
        """
        with self._lock:
            tasks = self._load_unlocked()
            initial_count = len(tasks)
            tasks = [t for t in tasks if t.id != task_id]

            if len(tasks) < initial_count:
                self._save_unlocked(tasks)
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
        with self._lock:
            tasks = self._load_unlocked()
            updated = False

            for i, existing_task in enumerate(tasks):
                if existing_task.id == task.id:
                    tasks[i] = task
                    updated = True
                    break

            if updated:
                self._save_unlocked(tasks)
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
        created_at=datetime.now(UTC),
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
        created_at=datetime.now(UTC),
        interval_seconds=interval_seconds,
        next_run=next_run,
        channel=channel,
        chat_id=chat_id,
    )
