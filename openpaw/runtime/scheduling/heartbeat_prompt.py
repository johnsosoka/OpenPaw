"""Heartbeat prompt builder for OpenPaw."""

from typing import Any

from openpaw.core.prompts.heartbeat import (
    ACTIVE_TASKS_TEMPLATE,
    HEARTBEAT_PROMPT,
    build_task_summary,
)


class HeartbeatPromptBuilder:
    """Builds heartbeat prompts and task summaries."""

    @staticmethod
    def build_heartbeat_prompt(timestamp: str, task_summary: str | None = None) -> str:
        """Build the heartbeat prompt with current timestamp and optional task summary.

        Args:
            timestamp: ISO-formatted timestamp string.
            task_summary: Optional compact task summary to inject into the prompt.

        Returns:
            Formatted heartbeat prompt string.
        """
        prompt = HEARTBEAT_PROMPT.format(timestamp=timestamp)

        if task_summary:
            prompt += "\n" + ACTIVE_TASKS_TEMPLATE.format(task_summary=task_summary)

        return prompt

    @staticmethod
    def build_task_summary(tasks: list[dict[str, Any]]) -> str | None:
        """Build a compact task summary from TASKS.yaml data.

        Thin wrapper around build_task_summary from prompts.heartbeat.

        Args:
            tasks: List of task dictionaries (already filtered to active tasks).

        Returns:
            Formatted task summary string, or None if no tasks.
        """
        return build_task_summary(tasks)
