"""Workspace tool filtering based on allow/deny configuration."""

import logging
from typing import Any

from openpaw.core.config import WorkspaceToolsConfig


class ToolFilter:
    """Filters workspace tools based on allow/deny lists."""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def filter(self, tools: list[Any], config: Any) -> list[Any]:
        """Filter workspace tools based on allow/deny lists.

        Args:
            tools: List of workspace tools to filter.
            config: WorkspaceToolsConfig with allow/deny lists.

        Returns:
            Filtered list of tools.
        """
        # Handle case where config might not be WorkspaceToolsConfig
        if not isinstance(config, WorkspaceToolsConfig):
            return tools

        deny = config.deny
        allow = config.allow

        # No filtering if both lists are empty
        if not deny and not allow:
            return tools

        filtered = []
        filtered_out = []

        for tool in tools:
            tool_name = tool.name

            # Deny takes precedence
            if deny and tool_name in deny:
                filtered_out.append(tool_name)
                continue

            # Allow list filtering (if populated)
            if allow and tool_name not in allow:
                filtered_out.append(tool_name)
                continue

            filtered.append(tool)

        if filtered_out:
            self._logger.info(f"Filtered out workspace tools: {filtered_out}")

        if filtered:
            tool_names = [t.name for t in filtered]
            self._logger.info(f"Active workspace tools after filtering: {tool_names}")

        return filtered


def filter_workspace_tools(
    tools: list[Any],
    config: Any,
    logger: logging.Logger,
) -> list[Any]:
    """Filter workspace tools based on allow/deny lists.

    Standalone function for backward compatibility.

    Args:
        tools: List of workspace tools to filter.
        config: WorkspaceToolsConfig with allow/deny lists.
        logger: Logger for reporting filtered tools.

    Returns:
        Filtered list of tools.
    """
    return ToolFilter(logger).filter(tools, config)
