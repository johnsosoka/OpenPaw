"""Configuration models for approval gates and tool timeouts."""

from pydantic import BaseModel, Field


class ToolApprovalConfig(BaseModel):
    """Configuration for a single tool's approval requirements."""

    require_approval: bool = Field(
        default=True,
        description="Whether this tool requires user approval before execution",
    )
    show_args: bool = Field(
        default=True,
        description="Whether to show tool arguments in the approval prompt",
    )


class ApprovalGatesConfig(BaseModel):
    """Root configuration for the approval gates system."""

    enabled: bool = Field(
        default=False,
        description="Whether approval gates are active for this workspace",
    )
    timeout_seconds: int = Field(
        default=120,
        description="Seconds to wait for user approval before applying default action",
    )
    default_action: str = Field(
        default="deny",
        description="Action when approval times out: 'deny' or 'approve'",
    )
    tools: dict[str, ToolApprovalConfig] = Field(
        default_factory=dict,
        description="Per-tool approval configuration (tool_name -> config)",
    )


class ToolTimeoutsConfig(BaseModel):
    """Configuration for per-tool-call timeouts."""

    default_seconds: int = Field(
        default=120,
        description="Default timeout for tool calls in seconds",
    )
    overrides: dict[str, int] = Field(
        default_factory=dict,
        description="Per-tool timeout overrides (tool_name -> timeout_seconds)",
    )
