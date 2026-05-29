"""Browser session management for Playwright lifecycle."""

import logging
from pathlib import Path
from typing import Any

from openpaw.builtins.tools.browser.interaction import BrowserInteraction
from openpaw.builtins.tools.browser.lifecycle import BrowserLifecycle
from openpaw.builtins.tools.browser.navigation import BrowserNavigation
from openpaw.builtins.tools.browser.security import DomainPolicy
from openpaw.builtins.tools.browser.snapshot import SnapshotTransformer
from openpaw.builtins.tools.browser.state import BrowserState
from openpaw.core.paths import BROWSER_COOKIES_JSON

logger = logging.getLogger(__name__)


class BrowserSession:
    """Manages Playwright browser/context/page lifecycle for a workspace.

    Provides a high-level interface for browser automation with:
    - Lazy initialization (browser launches on first navigate)
    - Domain security validation (allowlist/blocklist)
    - Accessibility tree snapshots with numeric element refs
    - Cookie persistence across sessions
    - Tab management
    - Screenshot capture

    The session maintains element references from the last snapshot for
    interaction tools (click, type). These refs are invalidated after
    navigation or page-changing actions.
    """

    def __init__(self, config: dict[str, Any]):
        """Initialize browser session with configuration.

        Args:
            config: Configuration dict containing:
                - headless: Run browser in headless mode (default: True)
                - viewport_width: Browser viewport width (default: 1280)
                - viewport_height: Browser viewport height (default: 720)
                - timeout_seconds: Per-action timeout (default: 30)
                - downloads_dir: Relative downloads directory (default: "downloads")
                - screenshots_dir: Relative screenshots directory (default: "screenshots")
                - workspace_path: Absolute workspace root path (required)
                - persist_cookies: Save/load cookies (default: False)
                - allowed_domains: List of allowed domains (empty = all allowed)
                - blocked_domains: List of blocked domains (always takes precedence)
                - max_snapshot_depth: Maximum snapshot tree depth (default: 10)
        """
        self.config = config
        self.headless = config.get("headless", True)
        self.viewport_width = config.get("viewport_width", 1280)
        self.viewport_height = config.get("viewport_height", 720)
        self.timeout_seconds = config.get("timeout_seconds", 30)
        self.persist_cookies = config.get("persist_cookies", False)

        # Paths (workspace-relative)
        workspace_path = Path(config["workspace_path"])
        self.workspace_path = workspace_path
        self.downloads_dir = workspace_path / config.get("downloads_dir", "workspace/downloads")
        self.screenshots_dir = workspace_path / config.get(
            "screenshots_dir", "workspace/screenshots"
        )
        self.cookie_file = workspace_path / str(BROWSER_COOKIES_JSON)

        # Create directories if needed
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Domain security
        self.domain_policy = DomainPolicy(
            allowed_domains=config.get("allowed_domains", []),
            blocked_domains=config.get("blocked_domains", []),
        )

        # Snapshot transformer
        max_depth = config.get("max_snapshot_depth", 10)
        self.snapshot_transformer = SnapshotTransformer(max_depth=max_depth)

        # Playwright state (lazy init)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._active_page_index = 0  # Track active tab

        # Element ref map from last snapshot (invalidated on navigation)
        self._ref_map: dict[int, dict[str, Any]] = {}

        # Sub-components (initialized lazily on first use, or inline here)
        self._lifecycle = BrowserLifecycle(self)
        self._navigation = BrowserNavigation(self)
        self._interaction = BrowserInteraction(self)
        self._state = BrowserState(self)

        logger.info(
            f"BrowserSession initialized (headless={self.headless}, "
            f"timeout={self.timeout_seconds}s)"
        )

    @property
    def is_active(self) -> bool:
        """Check if browser is currently active."""
        return self._browser is not None and self._page is not None

    async def launch(self) -> None:
        """Launch Playwright browser and create context/page.

        Called automatically on first navigate. Creates browser instance,
        context with download handling, and initial page.
        """
        await self._lifecycle.launch()

    async def close(self) -> None:
        """Close browser and cleanup resources.

        Saves cookies if persistence is enabled, then closes page/context/browser.
        """
        await self._lifecycle.close()

    async def navigate(self, url: str) -> str:
        """Navigate to URL with domain validation.

        Args:
            url: URL to navigate to.

        Returns:
            Status message with page title or error.
        """
        return await self._navigation.navigate(url)

    async def back(self) -> str:
        """Navigate back in history.

        Returns:
            Status message or error.
        """
        return await self._navigation.back()

    async def snapshot(self) -> str:
        """Take accessibility snapshot with numbered element refs.

        Returns:
            Formatted snapshot text with [ref] annotations.
        """
        return await self._state.snapshot()

    async def click(self, ref: int, keep_refs: bool = False) -> str:
        """Click element by reference number.

        Args:
            ref: Element reference from snapshot.
            keep_refs: When True, auto-refresh the snapshot after clicking
                and return updated element refs. Useful for multi-selection
                in custom dropdowns where the DOM re-renders after each click.

        Returns:
            Confirmation message or error. When keep_refs=True, includes
            a refreshed snapshot so you can immediately click the next element.
        """
        return await self._interaction.click(ref, keep_refs=keep_refs)

    async def type_text(self, ref: int, text: str, press_enter: bool = False) -> str:
        """Type text into input element.

        Args:
            ref: Element reference from snapshot.
            text: Text to type.
            press_enter: Whether to press Enter after typing.

        Returns:
            Confirmation message or error.
        """
        return await self._interaction.type_text(ref, text, press_enter)

    async def select_option(self, ref: int, value: str) -> str:
        """Select dropdown option.

        Args:
            ref: Element reference from snapshot.
            value: Option value or text to select.

        Returns:
            Confirmation message or error.
        """
        return await self._interaction.select_option(ref, value)

    async def execute_js(self, script: str, arg: Any = None) -> str:
        """Execute JavaScript in the browser page context.

        Use this for direct DOM manipulation when accessibility tree interaction
        is unreliable (custom React/Vue components, dynamic dropdowns, etc.).

        Args:
            script: JavaScript expression or arrow function body to evaluate.
                If the script references ``arg``, the value is passed as the
                second parameter to ``page.evaluate()`` and available as the
                function argument.
            arg: Optional JSON-serializable value passed into the script.

        Returns:
            JSON-serialized result string, or error message.
        """
        return await self._interaction.execute_js(script, arg)

    async def scroll(self, direction: str, amount: str = "page") -> str:
        """Scroll the page.

        Args:
            direction: "up" or "down".
            amount: "page" (full viewport) or "half" (half viewport).

        Returns:
            Confirmation message or error.
        """
        return await self._navigation.scroll(direction, amount)

    async def screenshot(self, full_page: bool = False) -> str:
        """Take screenshot and save to workspace.

        Args:
            full_page: Capture full scrollable page (default: viewport only).

        Returns:
            Relative path to screenshot file or error.
        """
        return await self._interaction.screenshot(full_page)

    async def get_tabs(self) -> str:
        """List all open tabs.

        Returns:
            Formatted list of tabs with indices.
        """
        return await self._state.get_tabs()

    async def switch_tab(self, index: int) -> str:
        """Switch to tab by index.

        Args:
            index: Tab index from get_tabs.

        Returns:
            Confirmation message or error.
        """
        return await self._navigation.switch_tab(index)

    def _handle_frame_navigated(self, frame: Any) -> None:
        """Handle frame navigation events for redirect detection.

        Args:
            frame: Playwright frame object.
        """
        # Check if this is the main frame
        if self._page and frame == self._page.main_frame:
            url = getattr(frame, "url", "")

            # Validate domain (log warning, don't block — already navigated)
            if not self.domain_policy.is_allowed(url):
                logger.warning(
                    f"Page navigated to disallowed domain: {url}. "
                    "This may have been a redirect."
                )
