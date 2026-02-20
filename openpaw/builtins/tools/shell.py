"""Shell command execution tool builtin."""

import asyncio
import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)

logger = logging.getLogger(__name__)


class ShellInput(BaseModel):
    """Input schema for shell command execution."""

    command: str = Field(description="The shell command to execute")
    timeout_seconds: int = Field(
        default=120,
        description=(
            "Maximum execution time in seconds (default: 120). "
            "Use higher values for known long-running operations."
        ),
        ge=1,
        le=600,
    )


class ShellToolBuiltin(BaseBuiltinTool):
    """Shell command execution capability.

    Provides async shell command execution with configurable command filtering for safety.
    This tool provides direct system access and should be used with caution.

    IMPORTANT: This tool is disabled by default and should only be enabled in
    trusted environments. The filtering mechanisms are safety nets, not security
    boundaries.

    Config options:
        allowed_commands: Optional list of allowed command prefixes.
                         If set, only commands starting with these prefixes are allowed.
        blocked_commands: List of blocked command prefixes (default includes dangerous commands).
        working_directory: Optional working directory constraint for command execution.
        default_timeout_seconds: Default timeout in seconds for commands (default: 120).
    """

    metadata = BuiltinMetadata(
        name="shell",
        display_name="Shell Command Execution",
        description="Execute shell commands on the host system",
        builtin_type=BuiltinType.TOOL,
        group="system",
        prerequisites=BuiltinPrerequisite(),  # No env vars required
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)

        # Default blocked commands - dangerous operations
        self.default_blocked = [
            "rm -rf",
            "sudo",
            "chmod",
            "chown",
            "> /dev",
            "mkfs",
            "dd if=",
            "mv /",
            "mv /*",
            "rm /",
            "rm /*",
            "format",
            "del /",
            ":(){:|:&};:",  # Fork bomb
        ]

    def get_langchain_tool(self) -> Any:
        """Return configured shell tool as a LangChain StructuredTool."""
        try:
            from langchain_core.tools import StructuredTool
        except ImportError as e:
            raise ImportError(
                "langchain-core is required for shell tool. "
                "Install with: pip install langchain-core"
            ) from e

        # Get configuration
        allowed_commands = self.config.get("allowed_commands", [])
        blocked_commands = self.config.get("blocked_commands", self.default_blocked)
        working_directory = self.config.get("working_directory")
        default_timeout = self.config.get("default_timeout_seconds", 120)

        async def execute_shell_command(command: str, timeout_seconds: int = default_timeout) -> str:
            """Execute a shell command with safety filtering and timeout.

            Args:
                command: The shell command to execute.
                timeout_seconds: Maximum execution time in seconds.

            Returns:
                Command output or error message.
            """
            # Validate command against filters
            validation_error = self._validate_command(
                command, allowed_commands, blocked_commands
            )
            if validation_error:
                logger.warning(f"Blocked shell command: {command} - {validation_error}")
                return f"[Command blocked: {validation_error}]"

            # Apply working directory if configured
            if working_directory:
                command = f"cd {working_directory} && {command}"

            # Track execution time
            start_time = time.time()

            try:
                logger.info(f"Executing shell command: {command[:100]}")

                # Create subprocess
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                # Execute with timeout
                try:
                    async with asyncio.timeout(timeout_seconds):
                        stdout, stderr = await process.communicate()
                except TimeoutError:
                    # Kill the process on timeout
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass  # Already exited
                    await process.wait()
                    elapsed = time.time() - start_time
                    logger.warning(f"Shell command timed out after {elapsed:.1f}s: {command[:100]}")
                    return f"[Command timed out after {timeout_seconds}s. The command was terminated.]"

                # Command completed - calculate duration
                elapsed = time.time() - start_time
                logger.info(f"Shell command completed in {elapsed:.1f}s: {command[:100]}")

                # Combine stdout and stderr
                output = ""
                if stdout:
                    output += stdout.decode('utf-8', errors='replace')
                if stderr:
                    if output:
                        output += "\n"
                    output += stderr.decode('utf-8', errors='replace')

                # Apply output truncation (100K char safety valve)
                max_chars = 100000
                if len(output) > max_chars:
                    output = (
                        f"[Output truncated: {len(output)} characters, showing first {max_chars}]\n"
                        f"{output[:max_chars]}"
                    )

                # Return output even on non-zero exit (let agent see the error)
                if not output:
                    output = "[No output]"

                return output

            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"Shell command failed after {elapsed:.1f}s: {e}")
                return f"[Command failed: {e}]"

        return StructuredTool.from_function(
            coroutine=execute_shell_command,
            name="shell",
            description=(
                "Execute shell commands on the host system. Use this for system operations, "
                "file manipulation, process management, and other shell tasks. "
                "Commands are filtered for safety - dangerous operations are blocked. "
                "You can specify a timeout_seconds parameter for long-running commands."
            ),
            args_schema=ShellInput,
        )

    def _validate_command(
        self,
        command: str,
        allowed_commands: list[str],
        blocked_commands: list[str],
    ) -> str | None:
        """Validate command against allow/block lists.

        Args:
            command: The command to validate.
            allowed_commands: List of allowed prefixes (empty = allow all).
            blocked_commands: List of blocked prefixes.

        Returns:
            Error message if command is invalid, None if valid.
        """
        command_lower = command.lower().strip()

        # Check blocked commands first (highest priority)
        for blocked in blocked_commands:
            if blocked.lower() in command_lower:
                return f"Command contains blocked pattern: '{blocked}'"

        # Check allowed commands if list is configured
        if allowed_commands:
            for allowed in allowed_commands:
                if command_lower.startswith(allowed.lower()):
                    return None  # Command is allowed

            # If allowed list exists but no match found
            return f"Command must start with one of: {', '.join(allowed_commands)}"

        # No allowed list and no blocked patterns - command is valid
        return None
