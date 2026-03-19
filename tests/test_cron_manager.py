"""Tests for CronManagerBuiltin and CronScheduler hot-reload methods."""

from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest
import yaml

from openpaw.builtins.tools.cron_manager import CronManagerBuiltin
from openpaw.core.config.models import CronDefinition, CronOutputConfig
from openpaw.runtime.scheduling.cron import CronScheduler

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """Return a temporary workspace root with config/crons/ pre-created."""
    crons_dir = tmp_path / "config" / "crons"
    crons_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def crons_dir(workspace_path: Path) -> Path:
    """Return the config/crons directory within the temporary workspace."""
    return workspace_path / "config" / "crons"


@pytest.fixture
def builtin(crons_dir: Path) -> CronManagerBuiltin:
    """Return a CronManagerBuiltin pointed at the temp crons directory."""
    config = {
        "crons_dir": str(crons_dir),
        "default_channel": "telegram",
        "default_target_id": 123456789,
        "timezone": "UTC",
    }
    return CronManagerBuiltin(config=config)


def _get_tool(builtin: CronManagerBuiltin, name: str):
    """Extract a named StructuredTool from a CronManagerBuiltin."""
    tools = {t.name: t for t in builtin.get_langchain_tool()}
    return tools[name]


# ---------------------------------------------------------------------------
# CronManagerBuiltin — create_cron
# ---------------------------------------------------------------------------


class TestCreateCron:
    """Tests for the create_cron tool."""

    def test_create_valid_cron_writes_yaml_file(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """A valid create request should write a correctly structured YAML file."""
        tool = _get_tool(builtin, "create_cron")
        result = tool.invoke(
            {
                "name": "morning-check",
                "schedule": "0 9 * * *",
                "prompt": "Check the morning status.",
            }
        )

        assert "Created cron job 'morning-check'" in result
        assert "0 9 * * *" in result

        cron_file = crons_dir / "morning-check.yaml"
        assert cron_file.exists(), "YAML file should be written to disk"

        with cron_file.open() as f:
            data = yaml.safe_load(f)

        assert data["name"] == "morning-check"
        assert data["schedule"] == "0 9 * * *"
        assert data["prompt"] == "Check the morning status."
        assert data["enabled"] is True
        assert data["output"]["channel"] == "telegram"
        assert data["output"]["target_id"] == 123456789
        assert data["output"]["delivery"] == "channel"

    def test_create_cron_with_all_fields(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """All optional fields are written correctly when provided."""
        tool = _get_tool(builtin, "create_cron")
        tool.invoke(
            {
                "name": "daily-summary-1",
                "schedule": "0 18 * * *",
                "prompt": "Generate end-of-day summary.",
                "enabled": False,
                "delivery": "agent",
            }
        )

        with (crons_dir / "daily-summary-1.yaml").open() as f:
            data = yaml.safe_load(f)

        assert data["enabled"] is False
        assert data["output"]["delivery"] == "agent"

    def test_create_cron_invalid_schedule_returns_error(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """An unparseable cron expression should return an error, not write a file."""
        tool = _get_tool(builtin, "create_cron")
        result = tool.invoke(
            {
                "name": "bad-schedule",
                "schedule": "not-a-cron",
                "prompt": "This should fail.",
            }
        )

        assert "[Error:" in result
        assert not (crons_dir / "bad-schedule.yaml").exists()

    def test_create_cron_invalid_name_path_separator_returns_error(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """Names containing path separators should be rejected."""
        tool = _get_tool(builtin, "create_cron")
        result = tool.invoke(
            {
                "name": "my/cron",
                "schedule": "0 9 * * *",
                "prompt": "Path traversal attempt.",
            }
        )

        assert "[Error:" in result
        assert not any(crons_dir.iterdir())

    def test_create_cron_uppercase_name_is_normalized_to_lowercase(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """Uppercase input is lowercased before validation, so 'Morning' becomes 'morning'."""
        tool = _get_tool(builtin, "create_cron")
        result = tool.invoke(
            {
                "name": "Morning",
                "schedule": "0 9 * * *",
                "prompt": "Uppercase name is normalized.",
            }
        )

        # The name is lowercased by create_cron before validation — succeeds as 'morning'
        assert "Created cron job 'morning'" in result
        assert (crons_dir / "morning.yaml").exists()

    def test_create_cron_invalid_name_special_chars_returns_error(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """Names with special characters like dots should be rejected."""
        tool = _get_tool(builtin, "create_cron")
        result = tool.invoke(
            {
                "name": "my..cron",
                "schedule": "0 9 * * *",
                "prompt": "Dots in name.",
            }
        )

        assert "[Error:" in result

    def test_create_cron_duplicate_name_returns_error(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """Creating a cron with the same name as an existing file should return an error."""
        tool = _get_tool(builtin, "create_cron")
        tool.invoke(
            {
                "name": "duplicate-job",
                "schedule": "0 9 * * *",
                "prompt": "First creation.",
            }
        )

        result = tool.invoke(
            {
                "name": "duplicate-job",
                "schedule": "*/15 * * * *",
                "prompt": "Second creation should fail.",
            }
        )

        assert "[Error:" in result
        assert "already exists" in result

        # Original file should be unchanged
        with (crons_dir / "duplicate-job.yaml").open() as f:
            data = yaml.safe_load(f)
        assert data["prompt"] == "First creation."

    def test_create_disabled_cron_does_not_call_scheduler(
        self, builtin: CronManagerBuiltin
    ) -> None:
        """A disabled cron should write the file but not trigger hot-reload."""
        mock_scheduler = Mock()
        builtin.set_scheduler(mock_scheduler)

        tool = _get_tool(builtin, "create_cron")
        tool.invoke(
            {
                "name": "inactive-job",
                "schedule": "0 9 * * *",
                "prompt": "Disabled from the start.",
                "enabled": False,
            }
        )

        mock_scheduler.reload_cron.assert_not_called()

    def test_create_enabled_cron_triggers_hot_reload(
        self, builtin: CronManagerBuiltin, workspace_path: Path
    ) -> None:
        """An enabled cron should trigger hot-reload on the live scheduler."""
        mock_scheduler = Mock()
        builtin.set_scheduler(mock_scheduler)

        tool = _get_tool(builtin, "create_cron")
        tool.invoke(
            {
                "name": "active-job",
                "schedule": "0 9 * * *",
                "prompt": "Active from creation.",
                "enabled": True,
            }
        )

        mock_scheduler.reload_cron.assert_called_once()


# ---------------------------------------------------------------------------
# CronManagerBuiltin — list_crons
# ---------------------------------------------------------------------------


class TestListCrons:
    """Tests for the list_crons tool."""

    def test_list_crons_with_existing_jobs(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """list_crons should return formatted output for each defined job."""
        # Write two cron files directly
        for name, schedule in [("job-alpha", "0 8 * * *"), ("job-beta", "*/30 * * * *")]:
            data = {
                "name": name,
                "schedule": schedule,
                "enabled": True,
                "prompt": f"Prompt for {name}.",
                "output": {"channel": "telegram", "target_id": 123456789, "delivery": "channel"},
            }
            with (crons_dir / f"{name}.yaml").open("w") as f:
                yaml.safe_dump(data, f)

        tool = _get_tool(builtin, "list_crons")
        result = tool.invoke({})

        assert "job-alpha" in result
        assert "job-beta" in result
        assert "0 8 * * *" in result
        assert "*/30 * * * *" in result

    def test_list_crons_empty_returns_no_jobs_message(
        self, builtin: CronManagerBuiltin
    ) -> None:
        """list_crons should inform the user when no jobs are defined."""
        tool = _get_tool(builtin, "list_crons")
        result = tool.invoke({})

        assert "No cron jobs" in result

    def test_list_crons_shows_disabled_status(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """list_crons should show the disabled status for inactive jobs."""
        data = {
            "name": "paused-job",
            "schedule": "0 12 * * *",
            "enabled": False,
            "prompt": "Paused.",
            "output": {"channel": "telegram", "target_id": 123456789, "delivery": "channel"},
        }
        with (crons_dir / "paused-job.yaml").open("w") as f:
            yaml.safe_dump(data, f)

        tool = _get_tool(builtin, "list_crons")
        result = tool.invoke({})

        assert "disabled" in result

    def test_list_crons_truncates_long_prompt(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """Prompts longer than 60 characters should be truncated in the listing."""
        long_prompt = "A" * 80
        data = {
            "name": "verbose-job",
            "schedule": "0 9 * * *",
            "enabled": True,
            "prompt": long_prompt,
            "output": {"channel": "telegram", "target_id": 123456789, "delivery": "channel"},
        }
        with (crons_dir / "verbose-job.yaml").open("w") as f:
            yaml.safe_dump(data, f)

        tool = _get_tool(builtin, "list_crons")
        result = tool.invoke({})

        assert "..." in result
        # Full 80-char prompt should not appear verbatim
        assert long_prompt not in result


# ---------------------------------------------------------------------------
# CronManagerBuiltin — update_cron
# ---------------------------------------------------------------------------


class TestUpdateCron:
    """Tests for the update_cron tool."""

    def _write_cron(self, crons_dir: Path, name: str = "existing-job") -> None:
        """Helper to write a baseline cron YAML file."""
        data = {
            "name": name,
            "schedule": "0 9 * * *",
            "enabled": True,
            "prompt": "Original prompt.",
            "output": {"channel": "telegram", "target_id": 123456789, "delivery": "channel"},
        }
        with (crons_dir / f"{name}.yaml").open("w") as f:
            yaml.safe_dump(data, f)

    def test_update_schedule_field_only(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """Updating schedule should change only that field, leaving others intact."""
        self._write_cron(crons_dir)
        tool = _get_tool(builtin, "update_cron")
        result = tool.invoke({"name": "existing-job", "schedule": "*/15 * * * *"})

        assert "Updated cron job 'existing-job'" in result
        assert "schedule" in result

        with (crons_dir / "existing-job.yaml").open() as f:
            data = yaml.safe_load(f)

        assert data["schedule"] == "*/15 * * * *"
        assert data["prompt"] == "Original prompt."
        assert data["enabled"] is True

    def test_update_prompt_field_only(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """Updating prompt should change only that field."""
        self._write_cron(crons_dir)
        tool = _get_tool(builtin, "update_cron")
        tool.invoke({"name": "existing-job", "prompt": "Updated prompt."})

        with (crons_dir / "existing-job.yaml").open() as f:
            data = yaml.safe_load(f)

        assert data["prompt"] == "Updated prompt."
        assert data["schedule"] == "0 9 * * *"

    def test_update_enabled_field_to_false(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """Disabling a cron should persist the change to disk."""
        self._write_cron(crons_dir)
        tool = _get_tool(builtin, "update_cron")
        tool.invoke({"name": "existing-job", "enabled": False})

        with (crons_dir / "existing-job.yaml").open() as f:
            data = yaml.safe_load(f)

        assert data["enabled"] is False

    def test_update_delivery_field(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """Updating delivery mode should be persisted to the output section."""
        self._write_cron(crons_dir)
        tool = _get_tool(builtin, "update_cron")
        tool.invoke({"name": "existing-job", "delivery": "both"})

        with (crons_dir / "existing-job.yaml").open() as f:
            data = yaml.safe_load(f)

        assert data["output"]["delivery"] == "both"

    def test_update_nonexistent_cron_returns_error(
        self, builtin: CronManagerBuiltin
    ) -> None:
        """Updating a cron that does not exist should return an error."""
        tool = _get_tool(builtin, "update_cron")
        result = tool.invoke({"name": "ghost-job", "prompt": "New prompt."})

        assert "[Error:" in result
        assert "not found" in result

    def test_update_invalid_schedule_returns_error_and_leaves_file_unchanged(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """An invalid schedule on update should not modify the file on disk."""
        self._write_cron(crons_dir)
        tool = _get_tool(builtin, "update_cron")
        result = tool.invoke({"name": "existing-job", "schedule": "bad-expression"})

        assert "[Error:" in result

        with (crons_dir / "existing-job.yaml").open() as f:
            data = yaml.safe_load(f)

        assert data["schedule"] == "0 9 * * *"

    def test_update_triggers_scheduler_hot_reload(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """update_cron should always trigger hot-reload on the live scheduler."""
        self._write_cron(crons_dir)
        mock_scheduler = Mock()
        builtin.set_scheduler(mock_scheduler)

        tool = _get_tool(builtin, "update_cron")
        tool.invoke({"name": "existing-job", "prompt": "Refreshed."})

        mock_scheduler.reload_cron.assert_called_once()


# ---------------------------------------------------------------------------
# CronManagerBuiltin — delete_cron
# ---------------------------------------------------------------------------


class TestDeleteCron:
    """Tests for the delete_cron tool."""

    def _write_cron(self, crons_dir: Path, name: str = "target-job") -> Path:
        """Helper to write a cron YAML file and return its path."""
        data = {
            "name": name,
            "schedule": "0 9 * * *",
            "enabled": True,
            "prompt": "To be deleted.",
            "output": {"channel": "telegram", "target_id": 123456789, "delivery": "channel"},
        }
        path = crons_dir / f"{name}.yaml"
        with path.open("w") as f:
            yaml.safe_dump(data, f)
        return path

    def test_delete_cron_removes_yaml_file(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """Deleting a cron should remove the YAML file from disk."""
        path = self._write_cron(crons_dir)
        assert path.exists()

        tool = _get_tool(builtin, "delete_cron")
        result = tool.invoke({"name": "target-job"})

        assert "Deleted cron job 'target-job'" in result
        assert not path.exists()

    def test_delete_cron_nonexistent_returns_error(
        self, builtin: CronManagerBuiltin
    ) -> None:
        """Deleting a cron that does not exist should return an error."""
        tool = _get_tool(builtin, "delete_cron")
        result = tool.invoke({"name": "phantom-job"})

        assert "[Error:" in result
        assert "not found" in result

    def test_delete_cron_calls_remove_from_scheduler(
        self, builtin: CronManagerBuiltin, crons_dir: Path
    ) -> None:
        """delete_cron should remove the job from the live scheduler."""
        self._write_cron(crons_dir)
        mock_scheduler = Mock()
        builtin.set_scheduler(mock_scheduler)

        tool = _get_tool(builtin, "delete_cron")
        tool.invoke({"name": "target-job"})

        mock_scheduler.remove_cron.assert_called_once_with("target-job")


# ---------------------------------------------------------------------------
# CronManagerBuiltin — name validation
# ---------------------------------------------------------------------------


class TestNameValidation:
    """Tests for the internal _validate_name() regex."""

    @pytest.mark.parametrize(
        "name",
        [
            "morning-check",
            "daily-summary-1",
            "healthcheck",
            "a",
            "abc123",
            "job-0",
        ],
    )
    def test_valid_names_return_no_error(
        self, builtin: CronManagerBuiltin, name: str
    ) -> None:
        """Valid names conforming to the regex should return None."""
        assert builtin._validate_name(name) is None

    @pytest.mark.parametrize(
        "name",
        [
            "Morning",          # uppercase
            "my/cron",          # forward slash
            "my\\cron",         # backslash
            "my..cron",         # double dot
            "-starts-with-dash",# leading hyphen
            "",                 # empty string
            "has space",        # space
            "ALLCAPS",          # all uppercase
            "under_score",      # underscore (not allowed by regex)
        ],
    )
    def test_invalid_names_return_error_message(
        self, builtin: CronManagerBuiltin, name: str
    ) -> None:
        """Invalid names should return a non-None error message."""
        assert builtin._validate_name(name) is not None


# ---------------------------------------------------------------------------
# CronScheduler — reload_cron
# ---------------------------------------------------------------------------


class TestCronSchedulerReloadCron:
    """Tests for CronScheduler.reload_cron()."""

    @pytest.fixture
    def scheduler(self, tmp_path: Path) -> CronScheduler:
        """Return a CronScheduler with a mocked APScheduler instance."""
        sched = CronScheduler(
            workspace_path=tmp_path,
            agent_factory=Mock(),
            channels={"telegram": Mock()},
        )
        # Inject a mock APScheduler so we do not need to call async start()
        mock_apscheduler = MagicMock()
        sched._scheduler = mock_apscheduler
        return sched

    def _make_cron_def(self, name: str, enabled: bool) -> CronDefinition:
        return CronDefinition(
            name=name,
            schedule="0 9 * * *",
            enabled=enabled,
            prompt="Test prompt.",
            output=CronOutputConfig(channel="telegram", target_id=123456789),
        )

    def test_reload_enabled_cron_removes_then_adds(self, scheduler: CronScheduler) -> None:
        """reload_cron on an enabled job should remove the old entry and add a new one."""
        cron_def = self._make_cron_def("my-job", enabled=True)
        # Pre-populate _jobs so remove_job sees it
        scheduler._jobs["my-job"] = Mock()

        scheduler.reload_cron(cron_def)

        # remove_job should have been called
        scheduler._scheduler.remove_job.assert_called_once_with("my-job")
        # add_job should have been called to re-register
        scheduler._scheduler.add_job.assert_called_once()
        assert "my-job" in scheduler._jobs

    def test_reload_disabled_cron_removes_but_does_not_add(
        self, scheduler: CronScheduler
    ) -> None:
        """reload_cron on a disabled job should remove the job but not re-add it."""
        cron_def = self._make_cron_def("disabled-job", enabled=False)
        scheduler._jobs["disabled-job"] = Mock()

        scheduler.reload_cron(cron_def)

        scheduler._scheduler.remove_job.assert_called_once_with("disabled-job")
        scheduler._scheduler.add_job.assert_not_called()
        assert "disabled-job" not in scheduler._jobs

    def test_reload_cron_not_previously_registered(self, scheduler: CronScheduler) -> None:
        """reload_cron for a job that was never registered should still add it when enabled."""
        cron_def = self._make_cron_def("brand-new-job", enabled=True)
        # _jobs is empty — no pre-existing entry

        scheduler.reload_cron(cron_def)

        # remove_job should NOT be called (job was not in _jobs)
        scheduler._scheduler.remove_job.assert_not_called()
        scheduler._scheduler.add_job.assert_called_once()


# ---------------------------------------------------------------------------
# CronScheduler — remove_cron
# ---------------------------------------------------------------------------


class TestCronSchedulerRemoveCron:
    """Tests for CronScheduler.remove_cron()."""

    @pytest.fixture
    def scheduler(self, tmp_path: Path) -> CronScheduler:
        """Return a CronScheduler with a mocked APScheduler instance."""
        sched = CronScheduler(
            workspace_path=tmp_path,
            agent_factory=Mock(),
            channels={"telegram": Mock()},
        )
        mock_apscheduler = MagicMock()
        sched._scheduler = mock_apscheduler
        return sched

    def test_remove_cron_delegates_to_remove_job(self, scheduler: CronScheduler) -> None:
        """remove_cron should call remove_job with the supplied name."""
        scheduler._jobs["some-job"] = Mock()

        scheduler.remove_cron("some-job")

        scheduler._scheduler.remove_job.assert_called_once_with("some-job")
        assert "some-job" not in scheduler._jobs

    def test_remove_cron_silently_ignores_missing_job(
        self, scheduler: CronScheduler
    ) -> None:
        """remove_cron on a job that was never added should not raise."""
        # No jobs pre-registered — should return silently
        scheduler.remove_cron("nonexistent-job")

        scheduler._scheduler.remove_job.assert_not_called()
