"""LangChain StructuredTool factories for cron manager builtin."""

import logging
from typing import Any

from langchain_core.tools import StructuredTool

from openpaw.builtins.tools.cron_manager.models import (
    CreateCronInput,
    DeleteCronInput,
    UpdateCronInput,
)
from openpaw.core.config.models import CronDefinition, CronOutputConfig

logger = logging.getLogger(__name__)


def create_create_cron_tool(builtin: Any) -> StructuredTool:
    """Create the create_cron tool."""

    def create_cron(
        name: str,
        schedule: str,
        prompt: str,
        enabled: bool = True,
        delivery: str = "channel",
    ) -> str:
        """Create a persistent YAML cron job and register it with the live scheduler.

        Args:
            name: Unique lowercase name for the cron job (hyphens allowed).
            schedule: Standard cron expression (e.g., '0 9 * * *').
            prompt: Instruction executed by the agent when the cron fires.
            enabled: Whether the job starts active (default: True).
            delivery: Output routing mode (channel/agent).

        Returns:
            Confirmation message or error string.
        """
        name = name.strip().lower()

        # Validate name
        name_error = builtin._validator.validate_name(name)
        if name_error:
            return f"[Error: {name_error}]"

        # Reject duplicates
        if builtin._persistence.exists(name):
            return (
                f"[Error: A cron job named '{name}' already exists. "
                f"Use update_cron to modify it or delete_cron to remove it first.]"
            )

        # Validate schedule
        schedule_error = builtin._validator.validate_schedule(schedule)
        if schedule_error:
            return f"[Error: {schedule_error}]"

        # Validate delivery
        delivery_error = builtin._validator.validate_delivery(delivery)
        if delivery_error:
            return f"[Error: {delivery_error}]"

        # Validate the full definition via Pydantic before writing
        output_config = CronOutputConfig(
            channel=builtin._persistence.default_channel,
            target_id=builtin._persistence.default_target_id,
            delivery=delivery,  # type: ignore[arg-type]
        )
        try:
            CronDefinition(
                name=name,
                schedule=schedule,
                enabled=enabled,
                prompt=prompt,
                output=output_config,
            )
        except Exception as e:
            return f"[Error: Invalid cron definition: {e}]"

        # Write to disk
        cron_dict = builtin._persistence.build_dict(
            name, schedule, prompt, enabled, delivery
        )
        try:
            builtin._persistence.write(cron_dict)
        except OSError as e:
            return f"[Error: Failed to write cron file: {e}]"

        logger.info(f"Created cron job '{name}' ({schedule})")

        # Hot-add to live scheduler
        if enabled:
            builtin._scheduler_bridge.reload(
                name, builtin._persistence.workspace_root
            )

        status = "enabled" if enabled else "disabled"
        return (
            f"Created cron job '{name}'.\n"
            f"  Schedule: {schedule} ({builtin.timezone})\n"
            f"  Status: {status}\n"
            f"  Delivery: {delivery}\n"
            f"  File: config/crons/{name}.yaml"
        )

    return StructuredTool.from_function(
        func=create_cron,
        name="create_cron",
        description=(
            "Create a persistent cron job that survives workspace restarts. "
            "Writes a YAML file to config/crons/ and registers it with the "
            "live scheduler immediately. "
            "Use this for recurring tasks that should run on a schedule "
            "(e.g., daily summaries, health checks, reminders)."
        ),
        args_schema=CreateCronInput,
    )


def create_list_crons_tool(builtin: Any) -> StructuredTool:
    """Create the list_crons tool."""

    def list_crons() -> str:
        """List all persistent YAML cron jobs in the workspace.

        Returns:
            Formatted list of cron jobs with name, schedule, status, and next run.
        """
        if not builtin._persistence.crons_dir.exists():
            return "No cron jobs defined. Use create_cron to add one."

        try:
            cron_defs = builtin._persistence.load_all()
        except Exception as e:
            return f"[Error: Failed to load cron definitions: {e}]"

        if not cron_defs:
            return "No cron jobs defined. Use create_cron to add one."

        lines = [f"Persistent cron jobs ({len(cron_defs)} total):\n"]

        for cron in cron_defs:
            status = "enabled" if cron.enabled else "disabled"

            # Compute next run time from live scheduler if available
            next_run = "unknown"
            if builtin._scheduler_bridge.scheduler and cron.enabled:
                try:
                    job = builtin._scheduler_bridge.scheduler._jobs.get(cron.name)
                    if job:
                        next_run_dt = job.next_run_time
                        if next_run_dt:
                            next_run = next_run_dt.strftime("%Y-%m-%d %H:%M %Z")
                except Exception:
                    pass  # best-effort

            prompt_preview = cron.prompt.strip()[:60]
            if len(cron.prompt.strip()) > 60:
                prompt_preview += "..."

            lines.append(
                f"  [{cron.name}]\n"
                f"    Schedule: {cron.schedule} ({builtin.timezone}) — next: {next_run}\n"
                f"    Status: {status}  Delivery: {cron.output.delivery}\n"
                f"    Prompt: {prompt_preview}\n"
            )

        return "\n".join(lines)

    return StructuredTool.from_function(
        func=list_crons,
        name="list_crons",
        description=(
            "List all persistent YAML cron jobs defined in this workspace. "
            "Shows name, schedule, enabled status, next run time, and a "
            "preview of each job's prompt."
        ),
    )


def create_update_cron_tool(builtin: Any) -> StructuredTool:
    """Create the update_cron tool."""

    def update_cron(
        name: str,
        schedule: str | None = None,
        prompt: str | None = None,
        enabled: bool | None = None,
        delivery: str | None = None,
    ) -> str:
        """Update fields on an existing YAML cron job.

        Only provided fields are modified; omitted fields keep their current values.

        Args:
            name: Name of the cron job to update.
            schedule: New cron expression (optional).
            prompt: New prompt text (optional).
            enabled: New enabled state (optional).
            delivery: New delivery mode (optional).

        Returns:
            Confirmation message or error string.
        """
        if not builtin._persistence.exists(name):
            return (
                f"[Error: Cron job '{name}' not found. "
                f"Use list_crons to see available jobs.]"
            )

        cron_dict = builtin._persistence.load(name)
        if not cron_dict:
            return f"[Error: Failed to read cron file for '{name}'.]"

        # Apply updates
        if schedule is not None:
            schedule_error = builtin._validator.validate_schedule(schedule)
            if schedule_error:
                return f"[Error: {schedule_error}]"
            cron_dict["schedule"] = schedule

        if prompt is not None:
            cron_dict["prompt"] = prompt

        if enabled is not None:
            cron_dict["enabled"] = enabled

        if delivery is not None:
            delivery_error = builtin._validator.validate_delivery(delivery)
            if delivery_error:
                return f"[Error: {delivery_error}]"
            if "output" not in cron_dict or not isinstance(cron_dict["output"], dict):
                cron_dict["output"] = {
                    "channel": builtin._persistence.default_channel
                }
            cron_dict["output"]["delivery"] = delivery

        # Validate the updated definition via Pydantic before writing
        try:
            CronDefinition(**cron_dict)
        except Exception as e:
            return f"[Error: Updated cron definition is invalid: {e}]"

        try:
            builtin._persistence.write(cron_dict)
        except OSError as e:
            return f"[Error: Failed to write cron file: {e}]"

        logger.info(f"Updated cron job '{name}'")

        # Re-register with live scheduler — reload_cron handles enable/disable
        builtin._scheduler_bridge.reload(name, builtin._persistence.workspace_root)

        updated_fields = [
            k for k, v in [
                ("schedule", schedule),
                ("prompt", prompt),
                ("enabled", enabled),
                ("delivery", delivery),
            ]
            if v is not None
        ]
        return (
            f"Updated cron job '{name}'.\n"
            f"  Modified fields: {', '.join(updated_fields)}\n"
            f"  Schedule: {cron_dict['schedule']} ({builtin.timezone})\n"
            f"  Status: {'enabled' if cron_dict.get('enabled', True) else 'disabled'}"
        )

    return StructuredTool.from_function(
        func=update_cron,
        name="update_cron",
        description=(
            "Update one or more fields of an existing persistent cron job. "
            "Only the fields you provide will be changed; others remain as-is. "
            "Changes are written to disk and applied to the live scheduler immediately."
        ),
        args_schema=UpdateCronInput,
    )


def create_delete_cron_tool(builtin: Any) -> StructuredTool:
    """Create the delete_cron tool."""

    def delete_cron(name: str) -> str:
        """Permanently delete a YAML cron job and remove it from the live scheduler.

        Args:
            name: Name of the cron job to delete.

        Returns:
            Confirmation message or error string.
        """
        if not builtin._persistence.exists(name):
            return (
                f"[Error: Cron job '{name}' not found. "
                f"Use list_crons to see available jobs.]"
            )

        # Remove from live scheduler first (before file is gone)
        builtin._scheduler_bridge.remove(name)

        # Remove YAML file
        try:
            builtin._persistence.file_path(name).unlink()
        except OSError as e:
            return f"[Error: Failed to delete cron file: {e}]"

        logger.info(f"Deleted cron job '{name}'")
        return f"Deleted cron job '{name}'. The file config/crons/{name}.yaml has been removed."

    return StructuredTool.from_function(
        func=delete_cron,
        name="delete_cron",
        description=(
            "Permanently delete a persistent cron job. "
            "Removes the YAML file from config/crons/ and unregisters the job "
            "from the live scheduler. This action cannot be undone."
        ),
        args_schema=DeleteCronInput,
    )


__all__ = [
    "create_create_cron_tool",
    "create_list_crons_tool",
    "create_update_cron_tool",
    "create_delete_cron_tool",
]
