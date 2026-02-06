"""SSH remote execution tool builtin."""

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


class SSHInput(BaseModel):
    """Input schema for SSH tool."""

    host: str = Field(description="Target hostname or IP address")
    command: str = Field(description="Command to execute on the remote host")
    user: str | None = Field(
        default=None,
        description="Optional SSH username (uses default if not specified)",
    )
    key_path: str | None = Field(
        default=None,
        description="Optional SSH private key path (uses default if not specified)",
    )


class SSHTool(BaseBuiltinTool):
    """SSH remote command execution capability.

    Provides agents with the ability to execute commands on remote hosts
    via SSH. Requires explicit allowlist of permitted hosts for security.

    No environment variables required (uses SSH keys from system).

    Config options:
        allowed_hosts: List of permitted hostnames/IPs (required)
        default_user: Default SSH username (optional)
        default_key_path: Default SSH private key path (optional, e.g., "~/.ssh/id_rsa")
        timeout: Connection timeout in seconds (default: 30)
    """

    metadata = BuiltinMetadata(
        name="ssh",
        display_name="SSH Remote Execution",
        description="Execute commands on remote hosts via SSH",
        builtin_type=BuiltinType.TOOL,
        group="system",
        prerequisites=BuiltinPrerequisite(),
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._allowed_hosts = self.config.get("allowed_hosts", [])
        if not self._allowed_hosts:
            logger.warning(
                "SSH tool initialized with no allowed_hosts - all connections will be rejected"
            )

    def get_langchain_tool(self) -> Any:
        """Return configured SSH tool as a LangChain StructuredTool."""
        try:
            from langchain_core.tools import StructuredTool
        except ImportError as e:
            raise ImportError(
                "langchain-core is required for SSH tool. "
                "Install with: pip install langchain-core"
            ) from e

        async def execute_ssh_command(
            host: str,
            command: str,
            user: str | None = None,
            key_path: str | None = None,
        ) -> str:
            """Execute a command on a remote host via SSH.

            Args:
                host: Target hostname or IP address.
                command: Command to execute.
                user: Optional SSH username override.
                key_path: Optional SSH key path override.

            Returns:
                Command output (stdout/stderr) with execution status.
            """
            # Security: Validate host against allowlist
            if host not in self._allowed_hosts:
                return (
                    f"[ERROR] Host '{host}' is not in allowed_hosts list. "
                    f"Permitted hosts: {', '.join(self._allowed_hosts)}"
                )

            try:
                result = await self._execute_remote_command(
                    host=host,
                    command=command,
                    user=user,
                    key_path=key_path,
                )
                return result
            except Exception as e:
                logger.error(f"SSH command failed on {host}: {e}")
                return f"[ERROR] Failed to execute command on {host}: {e}"

        return StructuredTool.from_function(
            coroutine=execute_ssh_command,
            name="ssh_execute",
            description=(
                "Execute commands on remote hosts via SSH. Only permitted hosts can be accessed. "
                "Useful for remote system management, log inspection, and distributed operations."
            ),
            args_schema=SSHInput,
        )

    async def _execute_remote_command(
        self,
        host: str,
        command: str,
        user: str | None = None,
        key_path: str | None = None,
    ) -> str:
        """Execute command on remote host using asyncssh.

        Args:
            host: Target hostname or IP.
            command: Command to execute.
            user: Optional username override.
            key_path: Optional key path override.

        Returns:
            Formatted output with stdout/stderr.
        """
        try:
            import asyncssh
        except ImportError as e:
            raise ImportError(
                "asyncssh is required for SSH tool. Install with: pip install asyncssh"
            ) from e

        # Resolve connection parameters
        resolved_user = user or self.config.get("default_user")
        resolved_key_path = key_path or self.config.get("default_key_path")
        timeout = self.config.get("timeout", 30)

        # Expand tilde in key path if present
        if resolved_key_path:
            import os

            resolved_key_path = os.path.expanduser(resolved_key_path)

        logger.info(
            f"Connecting to {resolved_user}@{host}" if resolved_user else f"Connecting to {host}"
        )

        # Build connection arguments
        connect_kwargs: dict[str, Any] = {
            "host": host,
            "connect_timeout": timeout,
            "known_hosts": None,  # Disable host key checking (can be configured later)
        }

        if resolved_user:
            connect_kwargs["username"] = resolved_user

        if resolved_key_path:
            connect_kwargs["client_keys"] = [resolved_key_path]

        # Execute command
        try:
            async with asyncssh.connect(**connect_kwargs) as conn:
                result = await conn.run(command, check=False, timeout=timeout)

                # Format output
                output_parts = []
                output_parts.append(f"[SSH] {host}: {command}")
                output_parts.append(f"[Exit Code] {result.exit_status}")

                if result.stdout:
                    output_parts.append(f"[STDOUT]\n{result.stdout.strip()}")

                if result.stderr:
                    output_parts.append(f"[STDERR]\n{result.stderr.strip()}")

                if not result.stdout and not result.stderr:
                    output_parts.append("[No output]")

                return "\n\n".join(output_parts)

        except asyncssh.Error as e:
            logger.error(f"SSH connection error to {host}: {e}")
            return f"[ERROR] SSH connection failed: {e}"
        except TimeoutError:
            logger.error(f"SSH command timed out on {host}")
            return f"[ERROR] Command timed out after {timeout} seconds"
