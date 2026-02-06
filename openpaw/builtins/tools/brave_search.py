"""Brave Search tool builtin."""

import logging
import os
from typing import Any

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)

logger = logging.getLogger(__name__)


class BraveSearchTool(BaseBuiltinTool):
    """Web search capability via Brave Search API.

    Provides agents with the ability to search the web for current information.
    Requires BRAVE_API_KEY environment variable to be set.

    Config options:
        count: Number of results to return (default: 5)
    """

    metadata = BuiltinMetadata(
        name="brave_search",
        display_name="Brave Web Search",
        description="Search the web using Brave Search API",
        builtin_type=BuiltinType.TOOL,
        group="web",
        prerequisites=BuiltinPrerequisite(env_vars=["BRAVE_API_KEY"]),
    )

    def get_langchain_tool(self) -> Any:
        """Return configured BraveSearch tool.

        Uses langchain_community's BraveSearch integration.
        """
        try:
            from langchain_community.tools import BraveSearch
        except ImportError as e:
            raise ImportError(
                "langchain-community is required for Brave Search. "
                "Install with: pip install langchain-community"
            ) from e

        api_key = os.environ.get("BRAVE_API_KEY", "")
        count = self.config.get("count", 5)

        logger.debug(f"Creating BraveSearch tool with count={count}")

        return BraveSearch.from_api_key(
            api_key=api_key,
            search_kwargs={"count": count},
        )
