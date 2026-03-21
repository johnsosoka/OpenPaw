"""Persistent cron management builtin for agent-controlled YAML cron jobs."""

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from apscheduler.triggers.cron import CronTrigger
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.core.config.models import CronDefinition, CronOutputConfig
from openpaw.runtime.scheduling.loader import CronLoader

logger = logging.getLogger(__name__)

# Regex for valid cron job names: alphanumeric and hyphens only.
_VALID_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CreateCronInput(BaseModel):
    """Input schema for creating a persistent cron job."""

    name: str = Field(
        description=(
            "Unique name for this cron job. "
            "Use lowercase letters, digits, and hyphens only "
            "(e.g., 'morning-check', 'daily-summary'). "
            "This becomes the filename and job ID."
        )
    )
    schedule: str = Field(
        description=(
            "Standard cron expression: 'minute hour day-of-month month day-of-week'. "
            "Examples: '0 9 * * *' (daily at 9am), '*/15 * * * *' (every 15 min), "
            "'0 0 * * 0' (every Sunday midnight). "
            "Runs in the workspace timezone."
        )
    )
    prompt: str = Field(
        description=(
            "The instruction the agent will execute when this cron fires. "
            "Include all necessary context — the cron agent has no memory of "
            "previous conversations."
        )
    )
    enabled: bool = Field(
        default=True,
        description="Whether the cron job is active immediately after creation.",
    )
    delivery: str = Field(
        default="channel",
        description=(
            "Where to deliver results: 'channel' (send to user), "
            "'agent' (inject into main agent queue), or 'both'."
        ),
    )


class UpdateCronInput(BaseModel):
    """Input schema for updating an existing cron job."""

    name: str = Field(description="Name of the existing cron job to update.")
    schedule: str | None = Field(
        default=None,
        description=(
            "New cron expression to set. Leave unset to keep the current schedule."
        ),
    )
    prompt: str | None = Field(
        default=None,
        description="New prompt to set. Leave unset to keep the current prompt.",
    )
    enabled: bool | None = Field(
        default=None,
        description=(
            "Set to true to enable or false to disable. "
            "Leave unset to keep the current state."
        ),
    )
    delivery: str | None = Field(
        default=None,
        description=(
            "New delivery mode: 'channel', 'agent', or 'both'. "
            "Leave unset to keep the current delivery mode."
        ),
    )


class DeleteCronInput(BaseModel):
    """Input schema for deleting a cron job."""

    name: str = Field(description="Name of the cron job to permanently delete.")


class CronManagerBuiltin(BaseBuiltinTool):
    """Persistent cron management — create, list, update, and delete YAML cron jobs.

    Unlike the dynamic cron tool (which uses in-memory task scheduling), this
    builtin writes YAML files to the workspace ``config/crons/`` directory.
    Jobs created here survive restarts and are loaded by the cron scheduler at
    startup alongside any hand-authored cron files.

    All changes are also applied to the live scheduler immediately so there is
    no need to restart the workspace.

    Config options:
        crons_dir: Absolute path to the workspace's config/crons/ directory.
        default_channel: Channel name for cron output routing (default: "telegram").
        default_target_id: Target user/channel ID for routing (default: None).
        timezone: Workspace timezone for schedule display (default: "UTC").
    """

    metadata = BuiltinMetadata(
        name="cron_manager",
        display_name="Cron Manager",
        description="Create, list, update, and delete persistent YAML cron jobs",
        builtin_type=BuiltinType.TOOL,
        group="automation",
        prerequisites=BuiltinPrerequisite(),  # No external dependencies required
    )

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the cron manager builtin.

        Args:
            config: Configuration dict containing:
                - crons_dir: Absolute path to config/crons/ directory (required)
                - default_channel: Channel name for output routing (default: "telegram")
                - default_target_id: Target ID for output routing (default: None)
                - timezone: Display timezone string (default: "UTC")
        """
        super().__init__(config)

        crons_dir = self.config.get("crons_dir")
        if not crons_dir:
            raise ValueError("CronManagerBuiltin requires 'crons_dir' in config")

        self.crons_dir = Path(crons_dir)
        self.default_channel = self.config.get("default_channel", "telegram")
        self.default_target_id: int | None = self.config.get("default_target_id")
        self.timezone = self.config.get("timezone", "UTC")

        # Scheduler reference — injected after startup via set_scheduler()
        self.scheduler: Any = None

        logger.info(f"CronManagerBuiltin initialized (crons_dir={self.crons_dir})")

    def get_langchain_tool(self) -> list[Any]:
        """Return cron management tools as a list of LangChain StructuredTools."""
        return [
            self._create_create_cron_tool(),
            self._create_list_crons_tool(),
            self._create_update_cron_tool(),
            self._create_delete_cron_tool(),
        ]

    def set_scheduler(self, scheduler: Any) -> None:
        """Connect a live CronScheduler for immediate hot-reload on changes.

        Called by lifecycle.py after the scheduler has started. Without a
        scheduler reference, file changes are still persisted to disk and
        will take effect on the next workspace restart.

        Args:
            scheduler: CronScheduler instance.
        """
        self.scheduler = scheduler
        logger.info("CronManager connected to live scheduler")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_name(self, name: str) -> str | None:
        """Return an error message if the name is invalid, otherwise None."""
        if not _VALID_NAME_RE.match(name):
            return (
                f"Invalid cron name '{name}'. "
                "Use lowercase letters, digits, and hyphens only "
                "(e.g., 'morning-check', 'daily-summary'). "
                "Must start with a letter or digit."
            )
        return None

    def _validate_schedule(self, schedule: str) -> str | None:
        """Return an error message if the cron expression is invalid, otherwise None."""
        try:
            CronTrigger.from_crontab(schedule)
        except (ValueError, KeyError) as e:
            return f"Invalid cron expression '{schedule}': {e}"
        return None

    def _validate_delivery(self, delivery: str) -> str | None:
        """Return an error message if the delivery mode is invalid, otherwise None."""
        allowed = {"channel", "agent", "both"}
        if delivery not in allowed:
            return f"Invalid delivery mode '{delivery}'. Must be one of: {allowed}"
        return None

    def _cron_file_path(self, name: str) -> Path:
        """Return the canonical YAML file path for a given cron name."""
        return self.crons_dir / f"{name}.yaml"

    def _cron_exists(self, name: str) -> bool:
        """Check if a YAML cron file exists for the given name."""
        return self._cron_file_path(name).exists()

    def _build_cron_dict(
        self,
        name: str,
        schedule: str,
        prompt: str,
        enabled: bool,
        delivery: str,
    ) -> dict[str, Any]:
        """Build the raw dict that maps 1-to-1 with the YAML file format."""
        output: dict[str, Any] = {"channel": self.default_channel, "delivery": delivery}
        if self.default_target_id is not None:
            output["target_id"] = self.default_target_id

        return {
            "name": name,
            "schedule": schedule,
            "enabled": enabled,
            "prompt": prompt,
            "output": output,
        }

    def _write_cron_yaml(self, cron_dict: dict[str, Any]) -> None:
        """Serialize a cron dict to YAML and write it to disk.

        Creates the crons directory if it does not yet exist.
        """
        self.crons_dir.mkdir(parents=True, exist_ok=True)
        path = self._cron_file_path(cron_dict["name"])
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(cron_dict, f, default_flow_style=False, sort_keys=False)

    def _load_cron_dict(self, name: str) -> dict[str, Any] | None:
        """Read and parse a YAML cron file. Returns None if not found."""
        path = self._cron_file_path(name)
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _reload_in_scheduler(self, name: str) -> None:
        """Hot-reload a YAML cron into the live scheduler if one is available."""
        if not self.scheduler:
            logger.debug(
                "No live scheduler available — cron change will take effect on next restart"
            )
            return

        try:
            loader = CronLoader(self.crons_dir.parent.parent)
            cron_def = loader.load_one(name)
            self.scheduler.reload_cron(cron_def)
            logger.info(f"Hot-reloaded cron job '{name}' in live scheduler")
        except Exception as e:
            logger.warning(f"Failed to hot-reload cron '{name}' in scheduler: {e}")

    def _remove_from_scheduler(self, name: str) -> None:
        """Remove a cron job from the live scheduler if one is available."""
        if not self.scheduler:
            logger.debug(
                "No live scheduler available — removal will take effect on next restart"
            )
            return

        try:
            self.scheduler.remove_cron(name)
            logger.info(f"Removed cron job '{name}' from live scheduler")
        except Exception as e:
            logger.debug(f"Cron '{name}' was not in live scheduler: {e}")

    # ------------------------------------------------------------------
    # Tool factories
    # ------------------------------------------------------------------

    def _create_create_cron_tool(self) -> StructuredTool:
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
                delivery: Output routing mode (channel/agent/both).

            Returns:
                Confirmation message or error string.
            """
            name = name.strip().lower()

            # Validate name
            name_error = self._validate_name(name)
            if name_error:
                return f"[Error: {name_error}]"

            # Reject duplicates
            if self._cron_exists(name):
                return (
                    f"[Error: A cron job named '{name}' already exists. "
                    f"Use update_cron to modify it or delete_cron to remove it first.]"
                )

            # Validate schedule
            schedule_error = self._validate_schedule(schedule)
            if schedule_error:
                return f"[Error: {schedule_error}]"

            # Validate delivery
            delivery_error = self._validate_delivery(delivery)
            if delivery_error:
                return f"[Error: {delivery_error}]"

            # Validate the full definition via Pydantic before writing
            output_config = CronOutputConfig(
                channel=self.default_channel,
                target_id=self.default_target_id,
                delivery=delivery,
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
            cron_dict = self._build_cron_dict(name, schedule, prompt, enabled, delivery)
            try:
                self._write_cron_yaml(cron_dict)
            except OSError as e:
                return f"[Error: Failed to write cron file: {e}]"

            logger.info(f"Created cron job '{name}' ({schedule})")

            # Hot-add to live scheduler
            if enabled:
                self._reload_in_scheduler(name)

            status = "enabled" if enabled else "disabled"
            return (
                f"Created cron job '{name}'.\n"
                f"  Schedule: {schedule} ({self.timezone})\n"
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

    def _create_list_crons_tool(self) -> StructuredTool:
        """Create the list_crons tool."""

        def list_crons() -> str:
            """List all persistent YAML cron jobs in the workspace.

            Returns:
                Formatted list of cron jobs with name, schedule, status, and next run.
            """
            if not self.crons_dir.exists():
                return "No cron jobs defined. Use create_cron to add one."

            loader = CronLoader(self.crons_dir.parent.parent)
            try:
                cron_defs = loader.load_all()
            except Exception as e:
                return f"[Error: Failed to load cron definitions: {e}]"

            if not cron_defs:
                return "No cron jobs defined. Use create_cron to add one."

            lines = [f"Persistent cron jobs ({len(cron_defs)} total):\n"]

            for cron in cron_defs:
                status = "enabled" if cron.enabled else "disabled"

                # Compute next run time from live scheduler if available
                next_run = "unknown"
                if self.scheduler and cron.enabled:
                    try:
                        job = self.scheduler._jobs.get(cron.name)
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
                    f"    Schedule: {cron.schedule} ({self.timezone}) — next: {next_run}\n"
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

    def _create_update_cron_tool(self) -> StructuredTool:
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
            if not self._cron_exists(name):
                return (
                    f"[Error: Cron job '{name}' not found. "
                    f"Use list_crons to see available jobs.]"
                )

            cron_dict = self._load_cron_dict(name)
            if not cron_dict:
                return f"[Error: Failed to read cron file for '{name}'.]"

            # Apply updates
            if schedule is not None:
                schedule_error = self._validate_schedule(schedule)
                if schedule_error:
                    return f"[Error: {schedule_error}]"
                cron_dict["schedule"] = schedule

            if prompt is not None:
                cron_dict["prompt"] = prompt

            if enabled is not None:
                cron_dict["enabled"] = enabled

            if delivery is not None:
                delivery_error = self._validate_delivery(delivery)
                if delivery_error:
                    return f"[Error: {delivery_error}]"
                if "output" not in cron_dict or not isinstance(cron_dict["output"], dict):
                    cron_dict["output"] = {"channel": self.default_channel}
                cron_dict["output"]["delivery"] = delivery

            # Validate the updated definition via Pydantic before writing
            try:
                CronDefinition(**cron_dict)
            except Exception as e:
                return f"[Error: Updated cron definition is invalid: {e}]"

            try:
                self._write_cron_yaml(cron_dict)
            except OSError as e:
                return f"[Error: Failed to write cron file: {e}]"

            logger.info(f"Updated cron job '{name}'")

            # Re-register with live scheduler — reload_cron handles enable/disable
            self._reload_in_scheduler(name)

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
                f"  Schedule: {cron_dict['schedule']} ({self.timezone})\n"
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

    def _create_delete_cron_tool(self) -> StructuredTool:
        """Create the delete_cron tool."""

        def delete_cron(name: str) -> str:
            """Permanently delete a YAML cron job and remove it from the live scheduler.

            Args:
                name: Name of the cron job to delete.

            Returns:
                Confirmation message or error string.
            """
            if not self._cron_exists(name):
                return (
                    f"[Error: Cron job '{name}' not found. "
                    f"Use list_crons to see available jobs.]"
                )

            # Remove from live scheduler first (before file is gone)
            self._remove_from_scheduler(name)

            # Remove YAML file
            try:
                self._cron_file_path(name).unlink()
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
