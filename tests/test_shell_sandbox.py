"""Tests for shell tool sandbox and command filtering."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from openpaw.builtins.tools.shell import ShellToolBuiltin


class TestShellWorkingDirectory:
    """Tests for shell tool working directory defaulting."""

    def test_working_directory_defaults_to_workspace_path(self):
        """Shell CWD defaults to workspace_path when no explicit working_directory."""
        config = {"workspace_path": Path("/home/agent/workspace")}
        builtin = ShellToolBuiltin(config)

        with patch("langchain_community.tools.shell.ShellTool") as mock_shell_cls:
            mock_shell = MagicMock()
            mock_shell._run.return_value = "output"
            mock_shell_cls.return_value = mock_shell

            tool = builtin.get_langchain_tool()
            tool.invoke({"command": "ls"})

            # Verify the command was prefixed with cd to workspace
            call_args = mock_shell._run.call_args[0][0]
            assert call_args.startswith("cd /home/agent/workspace && ")

    def test_explicit_working_directory_overrides_workspace_path(self):
        """Explicit working_directory takes priority over workspace_path."""
        config = {
            "workspace_path": Path("/home/agent/workspace"),
            "working_directory": "/custom/dir",
        }
        builtin = ShellToolBuiltin(config)

        with patch("langchain_community.tools.shell.ShellTool") as mock_shell_cls:
            mock_shell = MagicMock()
            mock_shell._run.return_value = "output"
            mock_shell_cls.return_value = mock_shell

            tool = builtin.get_langchain_tool()
            tool.invoke({"command": "ls"})

            call_args = mock_shell._run.call_args[0][0]
            assert call_args.startswith("cd /custom/dir && ")
            assert "/home/agent/workspace" not in call_args

    def test_no_workspace_path_fallback(self):
        """When neither working_directory nor workspace_path is set, no cd prefix."""
        config = {}
        builtin = ShellToolBuiltin(config)

        with patch("langchain_community.tools.shell.ShellTool") as mock_shell_cls:
            mock_shell = MagicMock()
            mock_shell._run.return_value = "output"
            mock_shell_cls.return_value = mock_shell

            tool = builtin.get_langchain_tool()
            tool.invoke({"command": "echo hello"})

            call_args = mock_shell._run.call_args[0][0]
            assert call_args == "echo hello"


class TestShellFormatFiltering:
    """Tests for format-related command filtering."""

    def test_format_method_allowed(self):
        """Python .format() should not be blocked."""
        builtin = ShellToolBuiltin({})
        result = builtin._validate_command(
            'python3 -c "print(\'{}\'.format(42))"',
            [],
            builtin.default_blocked,
        )
        assert result is None  # Not blocked

    def test_strftime_allowed(self):
        """strftime and date format commands should not be blocked."""
        builtin = ShellToolBuiltin({})
        result = builtin._validate_command(
            'date "+%Y-%m-%d %H:%M:%S"',
            [],
            builtin.default_blocked,
        )
        assert result is None  # Not blocked

    def test_python_format_string_allowed(self):
        """Python f-string/format operations should not be blocked."""
        builtin = ShellToolBuiltin({})
        result = builtin._validate_command(
            'python3 -c "x = format(42, \'08b\')"',
            [],
            builtin.default_blocked,
        )
        assert result is None  # Not blocked

    def test_windows_format_c_blocked(self):
        """Windows format c: should be blocked."""
        builtin = ShellToolBuiltin({})
        result = builtin._validate_command(
            "format c: /fs:ntfs",
            [],
            builtin.default_blocked,
        )
        assert result is not None  # Blocked

    def test_windows_format_d_blocked(self):
        """Windows format d: should be blocked."""
        builtin = ShellToolBuiltin({})
        result = builtin._validate_command(
            "format d:",
            [],
            builtin.default_blocked,
        )
        assert result is not None  # Blocked

    def test_diskutil_erasedisk_blocked(self):
        """macOS diskutil eraseDisk should be blocked."""
        builtin = ShellToolBuiltin({})
        result = builtin._validate_command(
            "diskutil eraseDisk JHFS+ Untitled /dev/disk2",
            [],
            builtin.default_blocked,
        )
        assert result is not None  # Blocked

    def test_diskutil_erasevolume_blocked(self):
        """macOS diskutil eraseVolume should be blocked."""
        builtin = ShellToolBuiltin({})
        result = builtin._validate_command(
            "diskutil eraseVolume APFS Untitled /dev/disk2s1",
            [],
            builtin.default_blocked,
        )
        assert result is not None  # Blocked

    def test_mkfs_still_blocked(self):
        """Linux mkfs should still be blocked (pre-existing)."""
        builtin = ShellToolBuiltin({})
        result = builtin._validate_command(
            "mkfs.ext4 /dev/sda1",
            [],
            builtin.default_blocked,
        )
        assert result is not None  # Blocked
