"""Formatting utilities for channel adapter messages.

Provides platform-agnostic text formatting helpers used by multiple
channel adapters (Discord, Telegram, and future channels).
"""

from typing import Any


def format_approval_message(
    tool_name: str, tool_args: dict[str, Any], show_args: bool
) -> str:
    """Build an approval-request message string.

    Escapes backticks to prevent markdown injection and truncates long
    argument strings.

    Args:
        tool_name: Name of the tool requiring approval.
        tool_args: Arguments passed to the tool.
        show_args: Whether to display tool arguments to the user.

    Returns:
        Formatted approval message text.
    """
    safe_tool_name = tool_name.replace("`", "'")
    text = f"🔒 **Approval Required**\nTool: `{safe_tool_name}`\n"
    if show_args and tool_args:
        args_str = str(tool_args)
        if len(args_str) > 500:
            args_str = args_str[:500] + "..."
        args_str = args_str.replace("`", "'")
        text += f"Args: `{args_str}`\n"
    return text


def format_unauthorized_response(
    user_id: int, workspace_name: str, group_id: int | None = None
) -> str:
    """Build a standard access-denied response with allowlist instructions.

    Args:
        user_id: The blocked user's platform ID.
        workspace_name: Name of the workspace for config path display.
        group_id: Optional group/server ID to include in the message.

    Returns:
        Formatted access-denied message text.
    """
    text = f"⛔ Access denied.\n\nYour user ID: `{user_id}`\n"
    if group_id is not None:
        text += f"Group ID: `{group_id}`\n"
    text += (
        f"\nTo gain access, add your ID to the allowlist:\n"
        f"`agent_workspaces/{workspace_name}/agent.yaml`\n\n"
        f"```yaml\n"
        f"channel:\n"
        f"  allowed_users:\n"
        f"    - {user_id}\n"
        f"```"
    )
    return text


def check_file_size(file_data: bytes, max_size: int, platform_name: str) -> None:
    """Validate that a file does not exceed a platform's size limit.

    Args:
        file_data: Raw file bytes.
        max_size: Maximum allowed size in bytes.
        platform_name: Human-readable platform name for error messages.

    Raises:
        ValueError: If file_data exceeds max_size.
    """
    size = len(file_data)
    if size > max_size:
        size_mb = size / (1024 * 1024)
        max_mb = max_size // (1024 * 1024)
        raise ValueError(
            f"File size ({size_mb:.1f} MB) exceeds {platform_name}'s "
            f"{max_mb} MB limit"
        )
