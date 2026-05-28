"""Browser automation builtin for OpenPaw."""

import logging
from typing import Any

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools.browser.session import BrowserSession
from openpaw.builtins.tools.browser.tools import (
    create_back_tool,
    create_click_tool,
    create_close_tool,
    create_execute_js_tool,
    create_navigate_tool,
    create_screenshot_tool,
    create_scroll_tool,
    create_select_tool,
    create_snapshot_tool,
    create_switch_tab_tool,
    create_tabs_tool,
    create_type_tool,
)

logger = logging.getLogger(__name__)


class BrowserToolBuiltin(BaseBuiltinTool):
    """Browser automation via Playwright with semantic snapshots.

    Provides agents with discrete browser control tools:
    - Navigate to URLs with domain security
    - Take semantic snapshots (accessibility tree with numeric refs)
    - Interact with elements (click, type, select)
    - Scroll, screenshot, tab management

    The browser session persists across tool calls and survives until:
    - Explicit browser_close
    - Conversation rotation (/new, /compact)
    - Workspace shutdown

    Config options:
        headless: Run browser in headless mode (default: True)
        viewport_width: Browser viewport width (default: 1280)
        viewport_height: Browser viewport height (default: 720)
        timeout_seconds: Per-action timeout (default: 30)
        max_snapshot_depth: Max tree depth for snapshots (default: 10)
        downloads_dir: Relative downloads directory (default: "downloads")
        screenshots_dir: Relative screenshots directory (default: "screenshots")
        persist_cookies: Save/load cookies across sessions (default: False)
        allowed_domains: List of allowed domains (empty = all)
        blocked_domains: List of blocked domains (takes precedence)
    """

    metadata = BuiltinMetadata(
        name="browser",
        display_name="Web Browser",
        description="Browser automation via Playwright with semantic snapshots",
        builtin_type=BuiltinType.TOOL,
        group="browser",
        prerequisites=BuiltinPrerequisite(packages=["playwright"]),
    )

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the browser tool builtin.

        Args:
            config: Configuration dict (see class docstring for options).
        """
        super().__init__(config)

        # Browser session (lazy init on first navigate)
        self._session: BrowserSession | None = None

        logger.info("BrowserToolBuiltin initialized")

    def get_langchain_tool(self) -> list:
        """Return list of browser tools as LangChain StructuredTools."""
        return [
            create_navigate_tool(self),
            create_snapshot_tool(self),
            create_click_tool(self),
            create_type_tool(self),
            create_select_tool(self),
            create_scroll_tool(self),
            create_execute_js_tool(self),
            create_back_tool(self),
            create_screenshot_tool(self),
            create_close_tool(self),
            create_tabs_tool(self),
            create_switch_tab_tool(self),
        ]

    def _get_session(self) -> BrowserSession:
        """Get or create browser session (lazy init).

        Returns:
            Active browser session.
        """
        if self._session is None:
            self._session = BrowserSession(self.config)
            logger.debug("Created new browser session")
        return self._session

    async def cleanup(self) -> None:
        """Close browser session.

        Called by WorkspaceRunner on stop/conversation rotation.
        """
        if self._session and self._session.is_active:
            logger.info("Cleaning up browser session")
            await self._session.close()
            self._session = None
