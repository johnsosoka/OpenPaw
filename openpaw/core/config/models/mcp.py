"""MCP server configuration models."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MCPServerConfig(BaseModel):
    """Single MCP server binding for a workspace agent."""

    name: str = Field(description="Unique server name within the workspace (used for tool prefix and logs).")
    transport: Literal["http", "sse", "stdio"] = Field(
        description="Transport type. 'http' = Streamable HTTP (preferred), 'sse' = legacy SSE, 'stdio' = local subprocess."
    )
    enabled: bool = Field(default=True, description="Per-server toggle.")
    required: bool = Field(
        default=False,
        description="If True, connection failure aborts workspace start. Default False = log + skip.",
    )

    # HTTP / SSE fields
    url: str | None = Field(default=None, description="Endpoint URL for http/sse transports.")
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Optional headers (e.g., Authorization) for http/sse. Supports ${VAR} env var expansion.",
    )

    # Stdio fields
    command: str | None = Field(default=None, description="Executable for stdio transport (e.g., 'python').")
    args: list[str] = Field(default_factory=list, description="Args for stdio command.")
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables for stdio subprocess. Supports ${VAR} expansion.",
    )
    cwd: str | None = Field(default=None, description="Working directory for stdio subprocess.")

    # Tool filtering / namespacing
    tool_prefix: str | None = Field(
        default=None,
        description=(
            "Prefix applied to tool names from this server. Default = '{name}_'. "
            "Set to empty string '' to disable prefixing."
        ),
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="If non-empty, only these tool names (pre-prefix) are exposed.",
    )
    denied_tools: list[str] = Field(
        default_factory=list,
        description="Tool names (pre-prefix) to exclude. Applied after allowed_tools.",
    )

    @model_validator(mode="after")
    def validate_transport_fields(self) -> "MCPServerConfig":
        if self.transport in ("http", "sse"):
            if not self.url:
                raise ValueError(
                    f"MCP server '{self.name}': 'url' is required for transport='{self.transport}'."
                )
            if self.command or self.args or self.env or self.cwd:
                raise ValueError(
                    f"MCP server '{self.name}': 'command'/'args'/'env'/'cwd' are stdio-only "
                    f"and invalid for transport='{self.transport}'."
                )
        elif self.transport == "stdio":
            if not self.command:
                raise ValueError(
                    f"MCP server '{self.name}': 'command' is required for transport='stdio'."
                )
            if self.url or self.headers:
                raise ValueError(
                    f"MCP server '{self.name}': 'url'/'headers' are http/sse-only and invalid for transport='stdio'."
                )
        return self

    def resolved_tool_prefix(self) -> str:
        """Return the prefix to apply. Empty string opts out; None defaults to '{name}_'."""
        if self.tool_prefix is None:
            return f"{self.name}_"
        return self.tool_prefix

    model_config = {"extra": "forbid"}


class WorkspaceMCPConfig(BaseModel):
    """Workspace-level MCP configuration block."""

    enabled: bool = Field(default=False, description="Master toggle for MCP in this workspace.")
    servers: list[MCPServerConfig] = Field(
        default_factory=list,
        description="MCP server bindings. Each connects independently.",
    )

    @model_validator(mode="after")
    def validate_unique_names(self) -> "WorkspaceMCPConfig":
        names = [s.name for s in self.servers]
        if len(names) != len(set(names)):
            dupes = {n for n in names if names.count(n) > 1}
            raise ValueError(f"Duplicate MCP server names: {sorted(dupes)}")
        return self

    model_config = {"extra": "forbid"}
