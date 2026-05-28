"""Task maintenance service for OpenPaw."""

import asyncio
import logging

from openpaw.stores.task import TaskStore


class TaskMaintenanceService:
    """Manages periodic task cleanup for a workspace."""

    def __init__(self, task_store: TaskStore, logger: logging.Logger):
        self._task_store = task_store
        self._logger = logger
        self._running = False

    def start(self) -> None:
        """Start the service (enable periodic cleanup)."""
        self._running = True

    def stop(self) -> None:
        """Stop the service (disable periodic cleanup)."""
        self._running = False

    def cleanup_old_tasks(self) -> None:
        """Clean up old completed tasks from TaskStore on startup."""
        try:
            removed = self._task_store.cleanup_old_tasks(
                max_age_days=3, stale_threshold_hours=48
            )
            if removed > 0:
                self._logger.info(
                    f"Cleaned up {removed} old task(s) from TaskStore"
                )

            from openpaw.model.task import TaskStatus

            active_tasks = self._task_store.list(status=TaskStatus.IN_PROGRESS)
            pending_tasks = self._task_store.list(status=TaskStatus.PENDING)
            awaiting_tasks = self._task_store.list(
                status=TaskStatus.AWAITING_CHECK
            )

            total_active = len(active_tasks) + len(pending_tasks) + len(awaiting_tasks)
            if total_active > 0:
                self._logger.info(
                    f"TaskStore has {total_active} active task(s) "
                    f"(pending: {len(pending_tasks)}, in_progress: {len(active_tasks)}, "
                    f"awaiting_check: {len(awaiting_tasks)})"
                )
        except FileNotFoundError:
            self._logger.debug("TaskStore file not found (new workspace)")
        except Exception as e:
            self._logger.warning(f"Failed to cleanup TaskStore: {e}")

    async def periodic_cleanup(self) -> None:
        """Run task cleanup every 6 hours."""
        while self._running:
            await asyncio.sleep(6 * 3600)  # 6 hours
            if not self._running:
                break
            try:
                removed = self._task_store.cleanup_old_tasks(
                    max_age_days=3, stale_threshold_hours=48
                )
                if removed > 0:
                    self._logger.info(
                        f"Periodic cleanup: removed {removed} old/stale tasks"
                    )
            except Exception as e:
                self._logger.warning(f"Periodic task cleanup failed: {e}")
