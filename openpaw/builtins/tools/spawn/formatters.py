"""Formatting utilities for spawn tool output."""


def format_time_ago(seconds: float) -> str:
    """Format elapsed time in human-readable form.

    Args:
        seconds: Seconds elapsed.

    Returns:
        Human-readable string (e.g., "5m ago", "2h ago").
    """
    if seconds < 60:
        return f"{int(seconds)}s ago"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes}m ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours}h ago"
    else:
        days = int(seconds / 86400)
        return f"{days}d ago"


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form.

    Args:
        seconds: Duration in seconds.

    Returns:
        Human-readable string (e.g., "5m", "2h").
    """
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes}m"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours}h"
    else:
        days = int(seconds / 86400)
        return f"{days}d"


def format_spawn_success(request_id: str, label: str, timeout_minutes: int) -> str:
    """Format the success message after spawning a sub-agent.

    Args:
        request_id: The spawned sub-agent's ID.
        label: Human-readable label for the sub-agent.
        timeout_minutes: Configured timeout in minutes.

    Returns:
        Formatted success message.
    """
    return (
        f"Sub-agent spawned: {request_id}\n"
        f"Label: {label}\n"
        f"Timeout: {timeout_minutes}min\n"
        f"Use list_subagents to check status."
    )
