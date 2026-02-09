"""Task storage for managing long-running agent operations.

This module handles persistence of task state, allowing agents to track
asynchronous operations across heartbeat invocations and restarts.
"""

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

import yaml

from openpaw.domain.task import Task, TaskPriority, TaskStatus

logger = logging.getLogger(__name__)


class TaskStore:
    """Manages persistent storage of task state in TASKS.yaml.

    Provides CRUD operations for task management with thread-safe file access.
    Tasks are stored in YAML format at {workspace_path}/TASKS.yaml.

    Example:
        >>> store = TaskStore(Path("agent_workspaces/gilfoyle"))
        >>> task = Task(
        ...     id=str(uuid.uuid4()),
        ...     type="research",
        ...     status=TaskStatus.IN_PROGRESS,
        ...     description="Market research for Q1 2026"
        ... )
        >>> store.create(task)
        >>> tasks = store.list(status=TaskStatus.IN_PROGRESS)
        >>> store.update(task.id, status=TaskStatus.COMPLETED)
    """

    STORAGE_FILENAME = "TASKS.yaml"
    VERSION = 1

    def __init__(self, workspace_path: Path):
        """Initialize the task store.

        Args:
            workspace_path: Path to the agent workspace root.
        """
        self.workspace_path = Path(workspace_path)
        self.storage_file = self.workspace_path / self.STORAGE_FILENAME
        self._lock = Lock()

        # Ensure workspace directory exists
        self.workspace_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"TaskStore initialized: {self.storage_file}")

    def _load_unlocked(self) -> dict[str, Any]:
        """Load raw YAML data from storage. Caller must hold self._lock.

        Returns:
            Dictionary with 'version', 'last_updated', and 'tasks' keys.
            Returns default structure if file doesn't exist.
        """
        if not self.storage_file.exists():
            logger.debug(f"Storage file does not exist: {self.storage_file}")
            return {
                "version": self.VERSION,
                "last_updated": datetime.now(UTC).isoformat(),
                "tasks": []
            }

        try:
            with self.storage_file.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                logger.error(f"Invalid storage format (expected dict): {self.storage_file}")
                return {
                    "version": self.VERSION,
                    "last_updated": datetime.now(UTC).isoformat(),
                    "tasks": []
                }

            # Ensure required keys exist
            if "tasks" not in data:
                data["tasks"] = []
            if "version" not in data:
                data["version"] = self.VERSION

            logger.debug(f"Loaded {len(data.get('tasks', []))} task(s) from storage")
            return data

        except yaml.YAMLError as e:
            logger.error(f"Corrupted storage file {self.storage_file}: {e}")
            return {
                "version": self.VERSION,
                "last_updated": datetime.now(UTC).isoformat(),
                "tasks": []
            }
        except Exception as e:
            logger.error(f"Unexpected error loading {self.storage_file}: {e}", exc_info=True)
            return {
                "version": self.VERSION,
                "last_updated": datetime.now(UTC).isoformat(),
                "tasks": []
            }

    def _load(self) -> dict[str, Any]:
        """Load raw YAML data from storage (thread-safe).

        Returns:
            Dictionary with 'version', 'last_updated', and 'tasks' keys.
            Returns default structure if file doesn't exist.
        """
        with self._lock:
            return self._load_unlocked()

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        """Persist YAML data to storage. Caller must hold self._lock.

        Args:
            data: Dictionary with version, last_updated, and tasks.
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

            logger.debug(f"Saved {len(data.get('tasks', []))} task(s) to storage")

        except Exception as e:
            logger.error(f"Failed to save tasks to {self.storage_file}: {e}", exc_info=True)
            raise

    def _save(self, data: dict[str, Any]) -> None:
        """Persist YAML data to storage (thread-safe).

        Args:
            data: Dictionary with version, last_updated, and tasks.
        """
        with self._lock:
            self._save_unlocked(data)

    def create(self, task: Task) -> None:
        """Create a new task and persist immediately.

        Args:
            task: Task instance to create.

        Raises:
            ValueError: If a task with the same ID already exists.
        """
        with self._lock:
            data = self._load_unlocked()

            # Check for duplicate ID
            if any(t["id"] == task.id for t in data["tasks"]):
                raise ValueError(f"Task with ID {task.id} already exists")

            data["tasks"].append(task.to_dict())
            self._save_unlocked(data)

        logger.info(f"Created task: {task.id} ({task.type}, {task.status.value})")

    def get(self, task_id: str) -> Task | None:
        """Retrieve a single task by ID.

        Args:
            task_id: Unique task identifier.

        Returns:
            Task instance if found, None otherwise.
        """
        with self._lock:
            data = self._load_unlocked()

        for task_data in data["tasks"]:
            if task_data["id"] == task_id:
                return Task.from_dict(task_data)

        return None

    def list(
        self,
        status: TaskStatus | None = None,
        type: str | None = None,
        priority: TaskPriority | None = None,
    ) -> list[Task]:
        """List tasks with optional filtering.

        Args:
            status: Filter by task status (None = all).
            type: Filter by task type (None = all).
            priority: Filter by priority level (None = all).

        Returns:
            List of Task instances matching filters.
        """
        with self._lock:
            data = self._load_unlocked()

        tasks = []

        for task_data in data["tasks"]:
            try:
                task = Task.from_dict(task_data)

                # Apply filters
                if status is not None and task.status != status:
                    continue
                if type is not None and task.type != type:
                    continue
                if priority is not None and task.priority != priority:
                    continue

                tasks.append(task)
            except Exception as e:
                logger.error(f"Failed to parse task {task_data.get('id', 'unknown')}: {e}")
                continue

        return tasks

    def update(self, task_id: str, **kwargs: Any) -> bool:
        """Update an existing task's fields.

        Args:
            task_id: Unique task identifier.
            **kwargs: Fields to update (status, notes, result_summary, etc.).

        Returns:
            True if task was found and updated, False otherwise.

        Example:
            >>> store.update(
            ...     "task-123",
            ...     status=TaskStatus.COMPLETED,
            ...     result_summary="Research complete",
            ...     completed_at=datetime.now(timezone.utc)
            ... )
        """
        with self._lock:
            data = self._load_unlocked()

            for i, task_data in enumerate(data["tasks"]):
                if task_data["id"] == task_id:
                    # Load existing task
                    task = Task.from_dict(task_data)

                    # Update fields
                    for key, value in kwargs.items():
                        if hasattr(task, key):
                            setattr(task, key, value)
                        else:
                            logger.warning(f"Ignoring unknown field: {key}")

                    # Replace in data
                    data["tasks"][i] = task.to_dict()
                    self._save_unlocked(data)

                    logger.info(f"Updated task: {task_id}")
                    return True

        logger.warning(f"Task not found for update: {task_id}")
        return False

    def delete(self, task_id: str) -> bool:
        """Delete a task by ID.

        Args:
            task_id: Unique task identifier.

        Returns:
            True if task was found and deleted, False otherwise.
        """
        with self._lock:
            data = self._load_unlocked()
            initial_count = len(data["tasks"])

            data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]

            if len(data["tasks"]) < initial_count:
                self._save_unlocked(data)
                logger.info(f"Deleted task: {task_id}")
                return True

        logger.warning(f"Task not found for deletion: {task_id}")
        return False

    def cleanup_old_tasks(self, max_age_days: int = 7) -> int:
        """Remove completed tasks older than specified age.

        Args:
            max_age_days: Maximum age in days for completed/failed tasks.

        Returns:
            Number of tasks removed.
        """
        with self._lock:
            data = self._load_unlocked()
            cutoff = datetime.now(UTC).timestamp() - (max_age_days * 86400)

            initial_count = len(data["tasks"])

            # Keep tasks that are:
            # 1. Not completed/failed, OR
            # 2. Completed/failed recently
            data["tasks"] = [
                t for t in data["tasks"]
                if (
                    t["status"] not in ["completed", "failed", "cancelled"]
                    or (
                        t.get("completed_at")
                        and datetime.fromisoformat(t["completed_at"]).timestamp() >= cutoff
                    )
                )
            ]

            removed = initial_count - len(data["tasks"])

            if removed > 0:
                self._save_unlocked(data)
                logger.info(f"Cleaned up {removed} old task(s) (older than {max_age_days} days)")

        return removed


def create_task(
    type: str,
    description: str,
    status: TaskStatus = TaskStatus.PENDING,
    priority: TaskPriority = TaskPriority.NORMAL,
    **kwargs: Any,
) -> Task:
    """Factory function for creating a new task with auto-generated ID.

    Args:
        type: Task type (research, deployment, batch, etc.).
        description: Human-readable task description.
        status: Initial task status (default: pending).
        priority: Task priority level (default: normal).
        **kwargs: Additional task fields (expected_duration_minutes, metadata, etc.).

    Returns:
        Task instance with unique ID.

    Example:
        >>> task = create_task(
        ...     type="research",
        ...     description="Market analysis for Q1 2026",
        ...     status=TaskStatus.IN_PROGRESS,
        ...     expected_duration_minutes=20,
        ...     metadata={"tool": "gpt_researcher"}
        ... )
    """
    return Task(
        id=str(uuid.uuid4()),
        type=type,
        description=description,
        status=status,
        priority=priority,
        **kwargs,
    )
