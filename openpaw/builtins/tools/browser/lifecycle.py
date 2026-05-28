"""Browser lifecycle management: launch, close, and cookie persistence."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BrowserLifecycle:
    """Manages Playwright browser launch, teardown, and cookie persistence.

    This class is responsible for creating and destroying the browser
    instance, context, and page. It also handles loading and saving
    cookies when persistence is enabled.
    """

    def __init__(self, session: Any) -> None:
        """Initialize with parent BrowserSession.

        Args:
            session: The BrowserSession instance that owns this lifecycle.
        """
        self._session: Any = session

    @property
    def _headless(self) -> bool:
        return bool(self._session.headless)

    @property
    def _viewport_width(self) -> int:
        return int(self._session.viewport_width)

    @property
    def _viewport_height(self) -> int:
        return int(self._session.viewport_height)

    @property
    def _timeout_seconds(self) -> int:
        return int(self._session.timeout_seconds)

    @property
    def _persist_cookies(self) -> bool:
        return bool(self._session.persist_cookies)

    @property
    def _cookie_file(self) -> Path:
        return Path(self._session.cookie_file)

    async def launch(self) -> None:
        """Launch Playwright browser and create context/page.

        Called automatically on first navigate. Creates browser instance,
        context with download handling, and initial page.
        """
        if self._session.is_active:
            logger.debug("Browser already active, skipping launch")
            return

        try:
            from playwright.async_api import async_playwright

            logger.info("Launching Playwright browser...")

            # Launch playwright
            self._session._playwright = await async_playwright().start()

            # Launch browser
            self._session._browser = await self._session._playwright.chromium.launch(
                headless=self._headless
            )

            # Create context with downloads enabled
            context_kwargs = {
                "viewport": {
                    "width": self._viewport_width,
                    "height": self._viewport_height,
                },
                "accept_downloads": True,
            }

            # Load cookies if persist is enabled
            if self._persist_cookies and self._cookie_file.exists():
                try:
                    logger.info("Loading cookies from storage")
                    with open(self._cookie_file) as f:
                        storage_state = json.load(f)
                        context_kwargs["storage_state"] = storage_state
                except Exception as e:
                    logger.warning(f"Failed to load cookies: {e}")

            self._session._context = await self._session._browser.new_context(**context_kwargs)

            # Create initial page
            self._session._page = await self._session._context.new_page()
            self._session._page.set_default_timeout(self._timeout_seconds * 1000)  # ms

            # Register frame navigation handler for redirect detection
            self._session._page.on("framenavigated", self._session._handle_frame_navigated)

            logger.info("Browser launched successfully")

        except ImportError:
            logger.error(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to launch browser: {e}")
            raise

    async def close(self) -> None:
        """Close browser and cleanup resources.

        Saves cookies if persistence is enabled, then closes page/context/browser.
        """
        if not self._session.is_active:
            logger.debug("Browser not active, nothing to close")
            return

        try:
            # Save cookies if persistence is enabled
            if self._persist_cookies and self._session._context:
                await self._save_cookies()

            # Close resources
            if self._session._page:
                await self._session._page.close()
                self._session._page = None

            if self._session._context:
                await self._session._context.close()
                self._session._context = None

            if self._session._browser:
                await self._session._browser.close()
                self._session._browser = None

            if self._session._playwright:
                await self._session._playwright.stop()
                self._session._playwright = None

            logger.info("Browser closed")

        except Exception as e:
            logger.error(f"Error closing browser: {e}")

    async def _save_cookies(self) -> None:
        """Save browser cookies to workspace storage."""
        if not self._session._context:
            return

        try:
            # Ensure the data/ directory exists
            self._cookie_file.parent.mkdir(parents=True, exist_ok=True)

            # Save storage state
            storage_state = await self._session._context.storage_state()
            with open(self._cookie_file, "w") as f:
                json.dump(storage_state, f, indent=2)

            logger.info(f"Cookies saved to {self._cookie_file}")

        except Exception as e:
            logger.warning(f"Failed to save cookies: {e}")

    async def _load_cookies(self) -> None:
        """Load browser cookies from workspace storage.

        Note: This is called during context creation via storage_state kwarg,
        not as a separate method. This is here for documentation.
        """
        pass
