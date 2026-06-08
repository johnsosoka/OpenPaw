"""Configuration model for status updates middleware."""

from pydantic import BaseModel, Field


class StatusUpdatesConfig(BaseModel):
    """Configuration for automatic and agent-driven status updates.

    Controls when the framework sends intermediary status messages to the user
    while the agent is working. Auto-detected events (tool calls, sub-agent
    dispatch) are throttled; agent-driven report_progress calls are not.
    """

    enabled: bool = Field(default=True, description="Enable status updates middleware")
    agent_start: bool = Field(
        default=True, description="Send 'Starting work...' when agent run begins"
    )
    tool_calls_detected: bool = Field(
        default=True, description="Send 'Using tools: X, Y...' when agent decides to call tools"
    )
    tool_start: bool = Field(
        default=True, description="Send 'Running tool: X...' before each tool execution"
    )
    tool_complete: bool = Field(
        default=False, description="Send 'Completed: X' after each tool execution"
    )
    subagent_spawned: bool = Field(
        default=True, description="Send 'Dispatched sub-agent: X' when spawn_agent is called"
    )
    steer_redirected: bool = Field(
        default=True,
        description="Send '🔄 Redirecting...' when steer mode skips tools",
    )
    run_interrupted: bool = Field(
        default=True,
        description="Send '🛑 Stopping...' when interrupt mode aborts a run",
    )
    collect_queued: bool = Field(
        default=True,
        description="Send '📨 New messages received...' when collect mode batches messages mid-run",
    )
    min_interval_seconds: int = Field(
        default=1, ge=0, description="Minimum seconds between auto-detected status updates"
    )
    max_updates_per_run: int = Field(
        default=10, ge=0, description="Maximum auto-detected updates per agent run"
    )
    template: str = Field(
        default="[{event}] {message}", description="Optional format template for status messages"
    )
    hermes_mode: bool = Field(
        default=True,
        description="Edit a single status message instead of sending multiple messages",
    )
    typing_indicator: bool = Field(
        default=True,
        description=(
            "Send typing indicator while agent is processing. "
            "The indicator is sent once at the start of a turn and auto-expires "
            "after ~5 seconds (Telegram) or ~10 seconds (Discord)."
        ),
    )
    reactions: bool = Field(
        default=True, description="Add emoji reactions to the user's original message"
    )
    use_emojis: bool = Field(
        default=True, description="Prefix status messages with relevant emojis"
    )

    model_config = {"extra": "allow"}
