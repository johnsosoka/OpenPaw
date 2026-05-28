"""Sub-agent tool filtering.

Provides the floor set of excluded tools and the filtering logic for
sub-agent tool selection, including group: prefix resolution.
"""

from __future__ import annotations

import logging
from typing import Any

from openpaw.builtins.registry import BuiltinRegistry

logger = logging.getLogger(__name__)


# Tools excluded from sub-agents to prevent recursion and unwanted side effects
SUBAGENT_EXCLUDED_TOOLS = {
    # Prevent sub-sub-agents
    "spawn_agent",
    "list_subagents",
    "get_subagent_result",
    "cancel_subagent",
    # Prevent self-continuation (sub-agents are one-shot)
    "request_followup",
    # Prevent unsolicited user messaging (SubAgentRunner handles result delivery)
    "send_message",
    "send_file",
    # Prevent persistence mechanisms that outlive sub-agent lifecycle
    "schedule_at",
    "schedule_every",
    "list_scheduled",
    "cancel_scheduled",
    # Prevent orphaned browser sessions (subagents have no session key for cleanup)
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_select",
    "browser_scroll",
    "browser_back",
    "browser_screenshot",
    "browser_close",
    "browser_tabs",
    "browser_switch_tab",
    # Prevent persistent cron jobs that outlive the subagent lifecycle
    "create_cron",
    "list_crons",
    "update_cron",
    "delete_cron",
    # Plan tool requires a session key (undefined in subagent execution context)
    "write_plan",
    "read_plan",
}


def filter_subagent_tools(
    tools: list[Any],
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
    group_resolver: Any | None = None,
) -> list[Any]:
    """Filter tools for a sub-agent based on allowed/denied lists.

    Filtering order:
    1. SUBAGENT_EXCLUDED_TOOLS floor (always applied, never overridable)
    2. allowed_tools whitelist (if specified, only matching tools survive)
    3. denied_tools blocklist (removes additional tools)

    The group: prefix is resolved via group_resolver (e.g., "group:web" →
    ["browser_navigate", "browser_click", ...]).
    Unknown tool names in allowed/denied produce a warning log, not an error.

    Args:
        tools: List of LangChain tools to filter.
        allowed_tools: Optional whitelist of tool names (supports group: prefix).
        denied_tools: Optional additional deny list (supports group: prefix).
        group_resolver: Callable that resolves group names to tool name lists.
            Defaults to BuiltinRegistry.get_instance().get_group_members.

    Returns:
        Filtered list of tools.
    """
    if group_resolver is None:
        group_resolver = BuiltinRegistry.get_instance().get_group_members

    def _resolve_tool_names(names: list[str] | None) -> set[str]:
        """Expand group: prefixes and return a set of tool names."""
        if not names:
            return set()

        resolved: set[str] = set()
        for name in names:
            if name.startswith("group:"):
                group_name = name[6:]  # Strip "group:" prefix
                try:
                    group_tools = group_resolver(group_name)
                    resolved.update(group_tools)
                except Exception as e:
                    logger.warning(f"Failed to resolve group '{group_name}': {e}")
            else:
                resolved.add(name)
        return resolved

    # Get tool names from the tools list
    tool_names = {getattr(tool, "name", str(tool)) for tool in tools}

    # Step 1: Always remove SUBAGENT_EXCLUDED_TOOLS
    filtered = [
        tool
        for tool in tools
        if getattr(tool, "name", str(tool)) not in SUBAGENT_EXCLUDED_TOOLS
    ]

    # Step 2: Apply allowed_tools whitelist (if specified)
    if allowed_tools is not None:
        allowed_set = _resolve_tool_names(allowed_tools)
        # Warn about unknown tools in allowed list
        unknown_allowed = allowed_set - tool_names - SUBAGENT_EXCLUDED_TOOLS
        if unknown_allowed:
            logger.warning(
                f"Unknown tools in allowed_tools list: {sorted(unknown_allowed)}"
            )
        filtered = [
            tool for tool in filtered if getattr(tool, "name", str(tool)) in allowed_set
        ]

    # Step 3: Apply denied_tools blocklist (if specified)
    if denied_tools is not None:
        denied_set = _resolve_tool_names(denied_tools)
        # Warn about unknown tools in denied list
        unknown_denied = denied_set - tool_names
        if unknown_denied:
            logger.warning(
                f"Unknown tools in denied_tools list: {sorted(unknown_denied)}"
            )
        filtered = [
            tool for tool in filtered if getattr(tool, "name", str(tool)) not in denied_set
        ]

    return filtered
