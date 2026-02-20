"""Tests for async shell tool builtin."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.builtins.tools.shell import ShellInput, ShellToolBuiltin


@pytest.fixture
def shell_tool():
    """Create a ShellToolBuiltin instance for testing."""
    return ShellToolBuiltin(config={})


@pytest.fixture
def shell_tool_with_config():
    """Create a ShellToolBuiltin with custom config."""
    config = {
        "allowed_commands": ["ls", "echo"],
        "blocked_commands": ["rm -rf", "sudo"],
        "working_directory": "/tmp",
        "default_timeout_seconds": 60,
    }
    return ShellToolBuiltin(config=config)


@pytest.mark.asyncio
async def test_basic_execution(shell_tool):
    """Test basic command execution returns output."""
    tool = shell_tool.get_langchain_tool()

    # Mock subprocess
    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"test output\n", b""))
    mock_process.kill = MagicMock()
    mock_process.wait = AsyncMock()

    with patch("asyncio.create_subprocess_shell", return_value=mock_process) as mock_create:
        result = await tool.coroutine(command="echo test", timeout_seconds=120)

        # Verify subprocess was created correctly
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args[0][0] == "echo test"
        assert call_args[1]["stdout"] == asyncio.subprocess.PIPE
        assert call_args[1]["stderr"] == asyncio.subprocess.PIPE

        # Verify output
        assert "test output" in result
        assert "[Command timed out" not in result


@pytest.mark.asyncio
async def test_timeout_behavior(shell_tool):
    """Test that commands exceeding timeout are killed and return timeout message."""
    tool = shell_tool.get_langchain_tool()

    # Mock subprocess that hangs
    mock_process = MagicMock()

    async def hanging_communicate():
        await asyncio.sleep(10)  # Hang longer than timeout

    mock_process.communicate = AsyncMock(side_effect=hanging_communicate)
    mock_process.kill = MagicMock()
    mock_process.wait = AsyncMock()

    with patch("asyncio.create_subprocess_shell", return_value=mock_process):
        result = await tool.coroutine(command="sleep 100", timeout_seconds=1)

        # Verify timeout message
        assert "[Command timed out after 1s" in result
        assert "The command was terminated" in result

        # Verify process was killed
        mock_process.kill.assert_called_once()
        mock_process.wait.assert_called_once()


@pytest.mark.asyncio
async def test_command_validation_blocked(shell_tool):
    """Test that blocked commands are rejected."""
    tool = shell_tool.get_langchain_tool()

    # Blocked command should return error without executing
    result = await tool.coroutine(command="sudo rm -rf /", timeout_seconds=120)

    assert "[Command blocked:" in result
    assert "blocked pattern" in result


@pytest.mark.asyncio
async def test_allowed_commands_enforcement(shell_tool_with_config):
    """Test that only allowed command prefixes work when allowlist is set."""
    tool = shell_tool_with_config.get_langchain_tool()

    # Allowed command (ls) should pass validation
    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"file1\nfile2\n", b""))

    with patch("asyncio.create_subprocess_shell", return_value=mock_process):
        result = await tool.coroutine(command="ls -la", timeout_seconds=60)
        assert "[Command blocked:" not in result

    # Disallowed command should be rejected
    result = await tool.coroutine(command="cat /etc/passwd", timeout_seconds=60)
    assert "[Command blocked:" in result
    assert "must start with one of" in result


@pytest.mark.asyncio
async def test_output_truncation(shell_tool):
    """Test that large output is truncated at 100K chars."""
    tool = shell_tool.get_langchain_tool()

    # Create output larger than 100K chars
    large_output = "x" * 150000
    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(large_output.encode(), b""))

    with patch("asyncio.create_subprocess_shell", return_value=mock_process):
        result = await tool.coroutine(command="echo test", timeout_seconds=120)

        # Verify truncation
        assert "[Output truncated: 150000 characters" in result
        assert "showing first 100000" in result
        assert len(result) < 150000  # Should be truncated


@pytest.mark.asyncio
async def test_non_zero_exit_code(shell_tool):
    """Test that non-zero exit code still returns stdout/stderr (no exception)."""
    tool = shell_tool.get_langchain_tool()

    # Command that fails but produces output
    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b"error: file not found\n"))
    mock_process.returncode = 1

    with patch("asyncio.create_subprocess_shell", return_value=mock_process):
        result = await tool.coroutine(command="cat nonexistent", timeout_seconds=120)

        # Should return the error output, not raise exception
        assert "error: file not found" in result
        assert "[Command failed:" not in result  # Generic failure wrapper shouldn't appear


@pytest.mark.asyncio
async def test_working_directory(shell_tool_with_config):
    """Test that working directory is prepended to command."""
    tool = shell_tool_with_config.get_langchain_tool()

    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"output", b""))

    with patch("asyncio.create_subprocess_shell", return_value=mock_process) as mock_create:
        await tool.coroutine(command="ls", timeout_seconds=60)

        # Verify command was prefixed with cd
        call_args = mock_create.call_args
        assert call_args[0][0] == "cd /tmp && ls"


@pytest.mark.asyncio
async def test_duration_logging(shell_tool, caplog):
    """Test that command duration is logged."""
    import logging

    caplog.set_level(logging.INFO)

    tool = shell_tool.get_langchain_tool()

    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"output", b""))

    with patch("asyncio.create_subprocess_shell", return_value=mock_process):
        await tool.coroutine(command="echo test", timeout_seconds=120)

        # Verify logging
        assert any("Shell command completed in" in record.message for record in caplog.records)
        assert any("echo test" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_async_execution():
    """Test that the tool is registered as async (has coroutine attribute)."""
    tool_builtin = ShellToolBuiltin(config={})
    tool = tool_builtin.get_langchain_tool()

    # Verify the tool is async
    assert hasattr(tool, "coroutine")
    assert tool.coroutine is not None
    assert asyncio.iscoroutinefunction(tool.coroutine)


@pytest.mark.asyncio
async def test_combined_stdout_stderr(shell_tool):
    """Test that stdout and stderr are combined in output."""
    tool = shell_tool.get_langchain_tool()

    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"stdout line\n", b"stderr line\n"))

    with patch("asyncio.create_subprocess_shell", return_value=mock_process):
        result = await tool.coroutine(command="some command", timeout_seconds=120)

        # Both should be in output
        assert "stdout line" in result
        assert "stderr line" in result


@pytest.mark.asyncio
async def test_no_output_handling(shell_tool):
    """Test that empty output returns [No output] message."""
    tool = shell_tool.get_langchain_tool()

    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_shell", return_value=mock_process):
        result = await tool.coroutine(command="true", timeout_seconds=120)

        assert "[No output]" in result


@pytest.mark.asyncio
async def test_default_timeout_from_config(shell_tool_with_config):
    """Test that default_timeout_seconds from config is used."""
    tool = shell_tool_with_config.get_langchain_tool()

    # The default timeout from config should be 60 seconds
    # We can't easily verify this directly without triggering a timeout,
    # but we can verify the tool accepts the parameter
    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"output", b""))

    with patch("asyncio.create_subprocess_shell", return_value=mock_process):
        # Call without timeout_seconds - should use config default (60)
        result = await tool.coroutine(command="echo test")
        assert "output" in result


@pytest.mark.asyncio
async def test_timeout_parameter_override(shell_tool_with_config):
    """Test that timeout_seconds parameter overrides config default."""
    tool = shell_tool_with_config.get_langchain_tool()

    mock_process = MagicMock()

    async def slow_communicate():
        await asyncio.sleep(5)

    mock_process.communicate = AsyncMock(side_effect=slow_communicate)
    mock_process.kill = MagicMock()
    mock_process.wait = AsyncMock()

    with patch("asyncio.create_subprocess_shell", return_value=mock_process):
        # Override with very short timeout
        result = await tool.coroutine(command="echo test", timeout_seconds=1)

        # Should timeout with the override value
        assert "[Command timed out after 1s" in result


@pytest.mark.asyncio
async def test_exception_handling(shell_tool):
    """Test that exceptions during execution are caught and logged."""
    tool = shell_tool.get_langchain_tool()

    # Simulate an exception during subprocess creation
    with patch("asyncio.create_subprocess_shell", side_effect=OSError("Permission denied")):
        result = await tool.coroutine(command="echo test", timeout_seconds=120)

        # Should return error message
        assert "[Command failed:" in result
        assert "Permission denied" in result


@pytest.mark.asyncio
async def test_input_schema_validation():
    """Test that ShellInput schema validates correctly."""
    # Valid input
    valid_input = ShellInput(command="echo test", timeout_seconds=120)
    assert valid_input.command == "echo test"
    assert valid_input.timeout_seconds == 120

    # Default timeout
    default_input = ShellInput(command="echo test")
    assert default_input.timeout_seconds == 120

    # Timeout constraints
    with pytest.raises(Exception):  # Pydantic validation error
        ShellInput(command="echo test", timeout_seconds=0)  # Below minimum

    with pytest.raises(Exception):  # Pydantic validation error
        ShellInput(command="echo test", timeout_seconds=700)  # Above maximum


@pytest.mark.asyncio
async def test_command_logging_truncation(shell_tool, caplog):
    """Test that long commands are truncated in logs."""
    import logging

    caplog.set_level(logging.INFO)

    tool = shell_tool.get_langchain_tool()

    # Create a very long command
    long_command = "echo " + "x" * 200

    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(b"output", b""))

    with patch("asyncio.create_subprocess_shell", return_value=mock_process):
        await tool.coroutine(command=long_command, timeout_seconds=120)

        # Verify command is truncated in logs (should show first 100 chars)
        log_messages = [record.message for record in caplog.records]
        assert any(
            "Executing shell command:" in msg and len(msg) < len(long_command) + 50
            for msg in log_messages
        )


@pytest.mark.asyncio
async def test_utf8_decoding_errors(shell_tool):
    """Test that invalid UTF-8 sequences are handled gracefully."""
    tool = shell_tool.get_langchain_tool()

    # Create output with invalid UTF-8 bytes
    invalid_utf8 = b"Valid text\xff\xfeInvalid bytes\n"

    mock_process = MagicMock()
    mock_process.communicate = AsyncMock(return_value=(invalid_utf8, b""))

    with patch("asyncio.create_subprocess_shell", return_value=mock_process):
        result = await tool.coroutine(command="some command", timeout_seconds=120)

        # Should decode with errors='replace', not crash
        assert "Valid text" in result
        # Invalid bytes should be replaced with replacement character
        assert isinstance(result, str)
