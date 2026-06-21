"""Tests for CLI error handling in run() entry point."""

from unittest.mock import patch

import pytest
import yaml

from openpaw.cli import run


class TestCliErrorHandling:
    """Tests for clean error reporting in the CLI entry point."""

    def test_keyboard_interrupt_exits_cleanly(self):
        """KeyboardInterrupt exits without traceback."""
        with patch("openpaw.cli.asyncio.run", side_effect=KeyboardInterrupt):
            # Should not raise
            run()

    def test_file_not_found_prints_error(self, capsys):
        """FileNotFoundError prints clean message and exits 1."""
        with patch("openpaw.cli.asyncio.run", side_effect=FileNotFoundError("Config file not found: config.yaml")):
            with pytest.raises(SystemExit) as exc_info:
                run()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Config file not found" in captured.err

    def test_yaml_error_prints_message(self, capsys):
        """yaml.YAMLError prints clean message and exits 1."""
        with patch("openpaw.cli.asyncio.run", side_effect=yaml.YAMLError("bad yaml")):
            with pytest.raises(SystemExit) as exc_info:
                run()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Invalid YAML" in captured.err

    def test_value_error_prints_config_error(self, capsys):
        """ValueError (e.g., from env var validation) prints config error and exits 1."""
        with patch(
            "openpaw.cli.asyncio.run",
            side_effect=ValueError("Unresolved environment variable(s) in config.yaml: ${MISSING_KEY}"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Configuration error" in captured.err
        assert "MISSING_KEY" in captured.err

    def test_generic_exception_prints_startup_failed(self, capsys):
        """Unknown exceptions print generic message with -v hint."""
        with patch("openpaw.cli.asyncio.run", side_effect=RuntimeError("something broke")):
            with pytest.raises(SystemExit) as exc_info:
                run()
            assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Startup failed" in captured.err
        assert "-v" in captured.err
