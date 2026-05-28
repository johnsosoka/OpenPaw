"""Browser tool factories for LangChain StructuredTools."""
import json
import logging
from typing import Any, cast

from langchain_core.tools import StructuredTool

from openpaw.builtins.tools.browser.models import (
    BrowserClickInput,
    BrowserExecuteJsInput,
    BrowserNavigateInput,
    BrowserScreenshotInput,
    BrowserScrollInput,
    BrowserSelectInput,
    BrowserSwitchTabInput,
    BrowserTypeInput,
)
from openpaw.builtins.tools.browser.session import BrowserSession

logger = logging.getLogger(__name__)


def create_navigate_tool(browser_builtin: Any) -> StructuredTool:
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
        session = cast(BrowserSession, browser_builtin._get_session())
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


def create_snapshot_tool(browser_builtin: Any) -> StructuredTool:
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
        session = cast(BrowserSession, browser_builtin._get_session())
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


def create_click_tool(browser_builtin: Any) -> StructuredTool:
    """Create browser_click tool."""

    def click_sync(ref: int, keep_refs: bool = False) -> str:
        """Not implemented (browser is async-only)."""
        raise NotImplementedError("Browser click requires async execution")

    async def click_async(ref: int, keep_refs: bool = False) -> str:
        """Click an element by reference number.

        Args:
            ref: Element reference from browser_snapshot.
            keep_refs: Auto-refresh snapshot after click (for multi-selection).

        Returns:
            Confirmation or error message.
        """
        session = cast(BrowserSession, browser_builtin._get_session())
        return await session.click(ref, keep_refs=keep_refs)

    return StructuredTool.from_function(
        func=click_sync,
        coroutine=click_async,
        name="browser_click",
        description=(
            "Click an element by reference number from browser_snapshot. "
            "The page may change after clicking, so use browser_snapshot again "
            "to see the updated state.\n\n"
            "For multi-selection in custom dropdowns (React/Vue components "
            "that re-render after each click), use keep_refs=True. This "
            "auto-refreshes the snapshot after clicking so you can immediately "
            "click the next element without a separate browser_snapshot call. "
            "Example: click(3, keep_refs=True) → click(5, keep_refs=True) → ..."
        ),
        args_schema=BrowserClickInput,
    )


def create_type_tool(browser_builtin: Any) -> StructuredTool:
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
        session = cast(BrowserSession, browser_builtin._get_session())
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


def create_select_tool(browser_builtin: Any) -> StructuredTool:
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
        session = cast(BrowserSession, browser_builtin._get_session())
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


def create_scroll_tool(browser_builtin: Any) -> StructuredTool:
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
        session = cast(BrowserSession, browser_builtin._get_session())
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


def create_execute_js_tool(browser_builtin: Any) -> StructuredTool:
    """Create browser_execute_js tool."""

    def execute_js_sync(script: str, arg: str | None = None) -> str:
        raise NotImplementedError("Browser JS execution requires async execution")

    async def execute_js_async(script: str, arg: str | None = None) -> str:
        """Execute JavaScript in the browser page.

        Use this when accessibility-tree interaction is unreliable — for example,
        custom React/Vue dropdowns that re-render after every click, or elements
        that lack stable ARIA roles. You can directly manipulate the DOM, query
        element state, or dispatch events.

        Examples:
            - document.querySelectorAll('input[type=checkbox]').length
            - [...document.querySelectorAll('.item')].map(e => e.textContent)
            - (els) => els.forEach(e => e.click())  with arg='.my-checkbox'

        Args:
            script: JavaScript expression or arrow-function body to evaluate.
            arg: Optional JSON value passed into the script.

        Returns:
            Result of the script (string, or JSON for objects/arrays).
        """
        session = cast(BrowserSession, browser_builtin._get_session())
        parsed_arg = json.loads(arg) if arg else None
        return await session.execute_js(script, parsed_arg)

    return StructuredTool.from_function(
        func=execute_js_sync,
        coroutine=execute_js_async,
        name="browser_execute_js",
        description=(
            "Execute JavaScript code in the browser page context. "
            "Use this when accessibility-tree interaction is unreliable — "
            "for example, custom React/Vue dropdowns that re-render after "
            "every click, or elements that lack stable ARIA roles. "
            "You can directly manipulate the DOM, query element state, or "
            "dispatch events. Returns the script result as a string or JSON."
        ),
        args_schema=BrowserExecuteJsInput,
    )


def create_back_tool(browser_builtin: Any) -> StructuredTool:
    """Create browser_back tool."""

    def back_sync() -> str:
        """Not implemented (browser is async-only)."""
        raise NotImplementedError("Browser back requires async execution")

    async def back_async() -> str:
        """Navigate back in browser history.

        Returns:
            Confirmation with page title or error.
        """
        session = cast(BrowserSession, browser_builtin._get_session())
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


def create_screenshot_tool(browser_builtin: Any) -> StructuredTool:
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
        session = cast(BrowserSession, browser_builtin._get_session())
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


def create_close_tool(browser_builtin: Any) -> StructuredTool:
    """Create browser_close tool."""

    def close_sync() -> str:
        """Not implemented (browser is async-only)."""
        raise NotImplementedError("Browser close requires async execution")

    async def close_async() -> str:
        """Close the browser session.

        Returns:
            Confirmation message.
        """
        await browser_builtin.cleanup()
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


def create_tabs_tool(browser_builtin: Any) -> StructuredTool:
    """Create browser_tabs tool."""

    def tabs_sync() -> str:
        """Not implemented (browser is async-only)."""
        raise NotImplementedError("Browser tabs requires async execution")

    async def tabs_async() -> str:
        """List all open browser tabs.

        Returns:
            Formatted list of tabs with indices and titles.
        """
        session = cast(BrowserSession, browser_builtin._get_session())
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


def create_switch_tab_tool(browser_builtin: Any) -> StructuredTool:
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
        session = cast(BrowserSession, browser_builtin._get_session())
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
