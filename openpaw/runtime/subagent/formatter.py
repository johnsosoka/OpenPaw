"""Sub-agent formatting utilities.

Pure functions for formatting elapsed time and origin annotations.
"""

from openpaw.model.subagent import SubAgentRequest


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as a human-readable string.

    Args:
        seconds: Elapsed time in seconds.

    Returns:
        Human-readable string such as "45s", "5m 30s", or "1h 2m 30s".
    """
    minutes, secs = divmod(int(seconds), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def build_origin_suffix(request: SubAgentRequest) -> str:
    """Build the origin annotation string for notification/progress messages.

    Args:
        request: The sub-agent request to read the origin from.

    Returns:
        Empty string when no origin is set, otherwise a parenthetical
        such as " (spawned by session: telegram:123456)".
    """
    if not request.origin:
        return ""
    parts = request.origin.split(":", 1)
    if len(parts) == 2:
        return f" (spawned by {parts[0]}: {parts[1]})"
    return f" (spawned by {request.origin})"
