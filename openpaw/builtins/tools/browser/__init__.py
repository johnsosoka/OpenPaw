"""Browser automation builtin for OpenPaw."""

import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools.browser.session import BrowserSession

logger = logging.getLogger(__name__)


class BrowserNavigateInput(BaseModel):
    """Input schema for browser navigation."""

    url: str = Field(description="URL to navigate to")


class BrowserClickInput(BaseModel):
    """Input schema for clicking elements."""

    ref: int = Field(description="Element reference number from browser_snapshot")


class BrowserTypeInput(BaseModel):
    """Input schema for typing text."""

    ref: int = Field(description="Element reference number from browser_snapshot")
    text: str = Field(description="Text to type into the element")
    press_enter: bool = Field(
        default=False, description="Press Enter after typing (submits forms)"
    )


class BrowserSelectInput(BaseModel):
    """Input schema for selecting dropdown options."""

    ref: int = Field(description="Element reference number from browser_snapshot")
    value: str = Field(description="Option value or label to select")


class BrowserScrollInput(BaseModel):
    """Input schema for scrolling."""

    direction: str = Field(description="Scroll direction: 'up' or 'down'")
    amount: str = Field(
        default="page", description="Scroll amount: 'page' (full) or 'half'"
    )


class BrowserScreenshotInput(BaseModel):
    """Input schema for screenshots."""

    full_page: bool = Field(
        default=False,
        description="Capture entire scrollable page (default: viewport only)",
    )


class BrowserSwitchTabInput(BaseModel):
    """Input schema for switching tabs."""

    index: int = Field(description="Tab index from browser_tabs")


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
            self._create_navigate_tool(),
            self._create_snapshot_tool(),
            self._create_click_tool(),
            self._create_type_tool(),
            self._create_select_tool(),
            self._create_scroll_tool(),
            self._create_back_tool(),
            self._create_screenshot_tool(),
            self._create_close_tool(),
            self._create_tabs_tool(),
            self._create_switch_tab_tool(),
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

    def _create_navigate_tool(self) -> StructuredTool:
        """Create browser_navigate tool."""

        def navigate_sync(url: str) -> str:
            """Not implemented (browser is async-only)."""
            raise NotImplementedError("Browser navigation requires async execution")

        async def navigate_async(url: str) -> str:
            """Navigate to a URL.

            The browser will launch automatically on first navigation.
            Domain restrictions may apply based on workspace configuration.

            Args:
                url: URL to navigate to.

            Returns:
                Page title and status, or error message.
            """
            session = self._get_session()
            return await session.navigate(url)

        return StructuredTool.from_function(
            func=navigate_sync,
            coroutine=navigate_async,
            name="browser_navigate",
            description=(
                "Navigate browser to a URL. The browser launches automatically "
                "on first use. Domain restrictions may apply based on your workspace "
                "configuration. After navigating, use browser_snapshot to see page content."
            ),
            args_schema=BrowserNavigateInput,
        )

    def _create_snapshot_tool(self) -> StructuredTool:
        """Create browser_snapshot tool."""

        def snapshot_sync() -> str:
            """Not implemented (browser is async-only)."""
            raise NotImplementedError("Browser snapshot requires async execution")

        async def snapshot_async() -> str:
            """Take semantic snapshot of current page.

            Returns an accessibility tree representation with numbered refs like:
            [1] Login (button)
            [2] Username (textbox)
            [3] Password (textbox)

            Use these ref numbers with browser_click, browser_type, etc.
            Refs are invalidated after navigation or page-changing actions.

            Returns:
                Formatted snapshot with interactive element refs.
            """
            session = self._get_session()
            return await session.snapshot()

        return StructuredTool.from_function(
            func=snapshot_sync,
            coroutine=snapshot_async,
            name="browser_snapshot",
            description=(
                "Take a semantic snapshot of the current page. Returns an accessibility "
                "tree with numbered element refs like [1] Button, [2] Link, etc. "
                "Use these refs with browser_click, browser_type, and other interaction tools. "
                "IMPORTANT: Refs are ephemeral — always re-snapshot after actions that change the page."
            ),
        )

    def _create_click_tool(self) -> StructuredTool:
        """Create browser_click tool."""

        def click_sync(ref: int) -> str:
            """Not implemented (browser is async-only)."""
            raise NotImplementedError("Browser click requires async execution")

        async def click_async(ref: int) -> str:
            """Click an element by reference number.

            Args:
                ref: Element reference from browser_snapshot.

            Returns:
                Confirmation or error message.
            """
            session = self._get_session()
            return await session.click(ref)

        return StructuredTool.from_function(
            func=click_sync,
            coroutine=click_async,
            name="browser_click",
            description=(
                "Click an element by reference number from browser_snapshot. "
                "The page may change after clicking, so use browser_snapshot again "
                "to see the updated state."
            ),
            args_schema=BrowserClickInput,
        )

    def _create_type_tool(self) -> StructuredTool:
        """Create browser_type tool."""

        def type_sync(ref: int, text: str, press_enter: bool = False) -> str:
            """Not implemented (browser is async-only)."""
            raise NotImplementedError("Browser type requires async execution")

        async def type_async(ref: int, text: str, press_enter: bool = False) -> str:
            """Type text into an input element.

            Args:
                ref: Element reference from browser_snapshot.
                text: Text to type.
                press_enter: Press Enter after typing (submits forms).

            Returns:
                Confirmation or error message.
            """
            session = self._get_session()
            return await session.type_text(ref, text, press_enter)

        return StructuredTool.from_function(
            func=type_sync,
            coroutine=type_async,
            name="browser_type",
            description=(
                "Type text into an input element (textbox, searchbox, etc.). "
                "Use press_enter=True to submit forms. The page may change after "
                "pressing Enter, so use browser_snapshot again to see updated state."
            ),
            args_schema=BrowserTypeInput,
        )

    def _create_select_tool(self) -> StructuredTool:
        """Create browser_select tool."""

        def select_sync(ref: int, value: str) -> str:
            """Not implemented (browser is async-only)."""
            raise NotImplementedError("Browser select requires async execution")

        async def select_async(ref: int, value: str) -> str:
            """Select a dropdown option.

            Args:
                ref: Element reference from browser_snapshot.
                value: Option value or label to select.

            Returns:
                Confirmation or error message.
            """
            session = self._get_session()
            return await session.select_option(ref, value)

        return StructuredTool.from_function(
            func=select_sync,
            coroutine=select_async,
            name="browser_select",
            description=(
                "Select an option from a dropdown (combobox). "
                "Provide the option's value or visible label."
            ),
            args_schema=BrowserSelectInput,
        )

    def _create_scroll_tool(self) -> StructuredTool:
        """Create browser_scroll tool."""

        def scroll_sync(direction: str, amount: str = "page") -> str:
            """Not implemented (browser is async-only)."""
            raise NotImplementedError("Browser scroll requires async execution")

        async def scroll_async(direction: str, amount: str = "page") -> str:
            """Scroll the page.

            Args:
                direction: "up" or "down".
                amount: "page" (full viewport) or "half" (half viewport).

            Returns:
                Confirmation or error message.
            """
            session = self._get_session()
            return await session.scroll(direction, amount)

        return StructuredTool.from_function(
            func=scroll_sync,
            coroutine=scroll_async,
            name="browser_scroll",
            description=(
                "Scroll the page up or down. Use amount='page' for full viewport "
                "scroll or amount='half' for half viewport. After scrolling, use "
                "browser_snapshot to see newly visible content."
            ),
            args_schema=BrowserScrollInput,
        )

    def _create_back_tool(self) -> StructuredTool:
        """Create browser_back tool."""

        def back_sync() -> str:
            """Not implemented (browser is async-only)."""
            raise NotImplementedError("Browser back requires async execution")

        async def back_async() -> str:
            """Navigate back in browser history.

            Returns:
                Confirmation with page title or error.
            """
            session = self._get_session()
            return await session.back()

        return StructuredTool.from_function(
            func=back_sync,
            coroutine=back_async,
            name="browser_back",
            description=(
                "Navigate back in browser history. After going back, use "
                "browser_snapshot to see the previous page content."
            ),
        )

    def _create_screenshot_tool(self) -> StructuredTool:
        """Create browser_screenshot tool."""

        def screenshot_sync(full_page: bool = False) -> str:
            """Not implemented (browser is async-only)."""
            raise NotImplementedError("Browser screenshot requires async execution")

        async def screenshot_async(full_page: bool = False) -> str:
            """Take a screenshot of the current page.

            Args:
                full_page: Capture entire scrollable page (default: viewport only).

            Returns:
                Relative path to saved screenshot file.
            """
            session = self._get_session()
            return await session.screenshot(full_page)

        return StructuredTool.from_function(
            func=screenshot_sync,
            coroutine=screenshot_async,
            name="browser_screenshot",
            description=(
                "Take a screenshot of the current page and save to workspace. "
                "Use full_page=True to capture the entire scrollable page, or "
                "full_page=False (default) to capture only the visible viewport. "
                "Returns the file path where the screenshot was saved."
            ),
            args_schema=BrowserScreenshotInput,
        )

    def _create_close_tool(self) -> StructuredTool:
        """Create browser_close tool."""

        def close_sync() -> str:
            """Not implemented (browser is async-only)."""
            raise NotImplementedError("Browser close requires async execution")

        async def close_async() -> str:
            """Close the browser session.

            Returns:
                Confirmation message.
            """
            await self.cleanup()
            return "Browser closed. Use browser_navigate to start a new session."

        return StructuredTool.from_function(
            func=close_sync,
            coroutine=close_async,
            name="browser_close",
            description=(
                "Close the browser session and cleanup resources. "
                "Cookies are saved if persistence is enabled. "
                "A new session will be created on next browser_navigate."
            ),
        )

    def _create_tabs_tool(self) -> StructuredTool:
        """Create browser_tabs tool."""

        def tabs_sync() -> str:
            """Not implemented (browser is async-only)."""
            raise NotImplementedError("Browser tabs requires async execution")

        async def tabs_async() -> str:
            """List all open browser tabs.

            Returns:
                Formatted list of tabs with indices and titles.
            """
            session = self._get_session()
            return await session.get_tabs()

        return StructuredTool.from_function(
            func=tabs_sync,
            coroutine=tabs_async,
            name="browser_tabs",
            description=(
                "List all open browser tabs with their indices, titles, and URLs. "
                "Use these indices with browser_switch_tab to change the active tab."
            ),
        )

    def _create_switch_tab_tool(self) -> StructuredTool:
        """Create browser_switch_tab tool."""

        def switch_tab_sync(index: int) -> str:
            """Not implemented (browser is async-only)."""
            raise NotImplementedError("Browser switch tab requires async execution")

        async def switch_tab_async(index: int) -> str:
            """Switch to a different browser tab.

            Args:
                index: Tab index from browser_tabs.

            Returns:
                Confirmation with new tab title or error.
            """
            session = self._get_session()
            return await session.switch_tab(index)

        return StructuredTool.from_function(
            func=switch_tab_sync,
            coroutine=switch_tab_async,
            name="browser_switch_tab",
            description=(
                "Switch to a different browser tab by index. "
                "Use browser_tabs to see available tabs and their indices. "
                "After switching, use browser_snapshot to see the new tab's content."
            ),
            args_schema=BrowserSwitchTabInput,
        )
