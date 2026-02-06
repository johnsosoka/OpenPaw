"""Shell command execution tool builtin."""

import logging
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


class ShellToolBuiltin(BaseBuiltinTool):
    """Shell command execution capability.

    Wraps LangChain's ShellTool with configurable command filtering for safety.
    This tool provides direct system access and should be used with caution.

    IMPORTANT: This tool is disabled by default and should only be enabled in
    trusted environments. The filtering mechanisms are safety nets, not security
    boundaries.

    Config options:
        allowed_commands: Optional list of allowed command prefixes.
                         If set, only commands starting with these prefixes are allowed.
        blocked_commands: List of blocked command prefixes (default includes dangerous commands).
        working_directory: Optional working directory constraint for command execution.
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
            from langchain_community.tools.shell import ShellTool
            from langchain_core.tools import StructuredTool
        except ImportError as e:
            raise ImportError(
                "langchain-community is required for ShellTool. "
                "Install with: pip install langchain-community"
            ) from e

        # Get configuration
        allowed_commands = self.config.get("allowed_commands", [])
        blocked_commands = self.config.get("blocked_commands", self.default_blocked)
        working_directory = self.config.get("working_directory")

        # Create underlying shell tool
        shell_tool = ShellTool()

        def execute_shell_command(command: str) -> str:
            """Execute a shell command with safety filtering.

            Args:
                command: The shell command to execute.

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

            try:
                logger.info(f"Executing shell command: {command}")
                result = shell_tool._run(command)
                return result
            except Exception as e:
                logger.error(f"Shell command failed: {e}")
                return f"[Command failed: {e}]"

        return StructuredTool.from_function(
            func=execute_shell_command,
            name="shell",
            description=(
                "Execute shell commands on the host system. Use this for system operations, "
                "file manipulation, process management, and other shell tasks. "
                "Commands are filtered for safety - dangerous operations are blocked."
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
