"""Browser navigation: URL navigation, back, scroll, and tab switching."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class BrowserNavigation:
    """Handles browser navigation operations.

    Includes URL navigation with domain validation, history navigation,
    page scrolling, and tab switching.
    """

    def __init__(self, session: Any) -> None:
        """Initialize with parent BrowserSession.

        Args:
            session: The BrowserSession instance that owns this navigation.
        """
        self._session: Any = session

    @property
    def _timeout_seconds(self) -> int:
        return int(self._session.timeout_seconds)

    async def navigate(self, url: str) -> str:
        """Navigate to URL with domain validation.

        Args:
            url: URL to navigate to.

        Returns:
            Status message with page title or error.
        """
        # Validate domain policy
        if not self._session.domain_policy.is_allowed(url):
            logger.warning(f"Navigation blocked by domain policy: {url}")
            return f"Navigation blocked: {url} is not in the allowed domains list"

        # Launch browser if needed (lazy init)
        if not self._session.is_active:
            await self._session._lifecycle.launch()

        try:
            logger.info(f"Navigating to: {url}")
            response = await self._session._page.goto(url, wait_until="domcontentloaded")

            # Check if redirect went to disallowed domain
            final_url = self._session._page.url
            if final_url != url and not self._session.domain_policy.is_allowed(final_url):
                logger.warning(f"Redirect blocked: {url} -> {final_url}")
                return (
                    f"Navigation blocked: redirected to disallowed domain {final_url}"
                )

            # Invalidate refs (page content changed)
            self._session._ref_map = {}

            # Get page title
            title = await self._session._page.title()
            status = response.status if response else "unknown"

            logger.info(f"Navigated successfully: {title} (status: {status})")
            return (
                f"Navigated to: {title}\nURL: {final_url}\nStatus: {status}\n\n"
                "Use browser_snapshot to see page content."
            )

        except Exception as e:
            logger.error(f"Navigation failed: {e}")
            return f"Navigation failed: {str(e)}"

    async def back(self) -> str:
        """Navigate back in history.

        Returns:
            Status message or error.
        """
        if not self._session.is_active:
            return "Browser not active. Use browser_navigate first."

        try:
            await self._session._page.go_back(wait_until="domcontentloaded")
            self._session._ref_map = {}  # Invalidate refs
            title = await self._session._page.title()
            logger.info(f"Navigated back: {title}")
            return f"Navigated back to: {title}\n\nUse browser_snapshot to see page content."
        except Exception as e:
            logger.error(f"Back navigation failed: {e}")
            return f"Back navigation failed: {str(e)}"

    async def scroll(self, direction: str, amount: str = "page") -> str:
        """Scroll the page.

        Args:
            direction: "up" or "down".
            amount: "page" (full viewport) or "half" (half viewport).

        Returns:
            Confirmation message or error.
        """
        if not self._session.is_active:
            return "Browser not active. Use browser_navigate first."

        try:
            # Calculate scroll distance
            if amount == "half":
                distance = self._session.viewport_height // 2
            else:
                distance = self._session.viewport_height

            # Determine scroll direction
            if direction.lower() == "up":
                distance = -distance

            # Execute scroll
            await self._session._page.evaluate(f"window.scrollBy(0, {distance})")

            logger.info(f"Scrolled {direction} by {abs(distance)}px")
            return f"Scrolled {direction} ({amount})"

        except Exception as e:
            logger.error(f"Scroll failed: {e}")
            return f"Scroll failed: {str(e)}"

    async def switch_tab(self, index: int) -> str:
        """Switch to tab by index.

        Args:
            index: Tab index from get_tabs.

        Returns:
            Confirmation message or error.
        """
        if not self._session.is_active:
            return "Browser not active. Use browser_navigate first."

        try:
            pages = self._session._context.pages

            if index < 0 or index >= len(pages):
                return f"Invalid tab index: {index}. Use browser_tabs to see available tabs."

            # Switch to page
            self._session._page = pages[index]
            self._session._page.set_default_timeout(self._timeout_seconds * 1000)

            # Re-register navigation handler
            self._session._page.on("framenavigated", self._session._handle_frame_navigated)

            # Invalidate refs (different page)
            self._session._ref_map = {}

            title = await self._session._page.title()
            url = self._session._page.url

            logger.info(f"Switched to tab {index}: {title}")
            return f"Switched to tab {index}: {title}\nURL: {url}\n\nUse browser_snapshot to see page content."

        except Exception as e:
            logger.error(f"Switch tab failed: {e}")
            return f"Switch tab failed: {str(e)}"
