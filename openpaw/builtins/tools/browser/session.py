"""Browser session management for Playwright lifecycle."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from openpaw.builtins.tools.browser.security import DomainPolicy
from openpaw.builtins.tools.browser.snapshot import SnapshotTransformer

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
        self.downloads_dir = workspace_path / config.get("downloads_dir", "downloads")
        self.screenshots_dir = workspace_path / config.get(
            "screenshots_dir", "screenshots"
        )
        self.cookie_file = workspace_path / ".openpaw" / "browser_cookies.json"

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
        if self.is_active:
            logger.debug("Browser already active, skipping launch")
            return

        try:
            from playwright.async_api import async_playwright

            logger.info("Launching Playwright browser...")

            # Launch playwright
            self._playwright = await async_playwright().start()

            # Launch browser
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless
            )

            # Create context with downloads enabled
            context_kwargs = {
                "viewport": {
                    "width": self.viewport_width,
                    "height": self.viewport_height,
                },
                "accept_downloads": True,
            }

            # Load cookies if persist is enabled
            if self.persist_cookies and self.cookie_file.exists():
                try:
                    logger.info("Loading cookies from storage")
                    with open(self.cookie_file) as f:
                        storage_state = json.load(f)
                        context_kwargs["storage_state"] = storage_state
                except Exception as e:
                    logger.warning(f"Failed to load cookies: {e}")

            self._context = await self._browser.new_context(**context_kwargs)

            # Create initial page
            self._page = await self._context.new_page()
            self._page.set_default_timeout(self.timeout_seconds * 1000)  # ms

            # Register frame navigation handler for redirect detection
            self._page.on("framenavigated", self._handle_frame_navigated)

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
        if not self.is_active:
            logger.debug("Browser not active, nothing to close")
            return

        try:
            # Save cookies if persistence is enabled
            if self.persist_cookies and self._context:
                await self._save_cookies()

            # Close resources
            if self._page:
                await self._page.close()
                self._page = None

            if self._context:
                await self._context.close()
                self._context = None

            if self._browser:
                await self._browser.close()
                self._browser = None

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

            logger.info("Browser closed")

        except Exception as e:
            logger.error(f"Error closing browser: {e}")

    async def navigate(self, url: str) -> str:
        """Navigate to URL with domain validation.

        Args:
            url: URL to navigate to.

        Returns:
            Status message with page title or error.
        """
        # Validate domain policy
        if not self.domain_policy.is_allowed(url):
            logger.warning(f"Navigation blocked by domain policy: {url}")
            return f"Navigation blocked: {url} is not in the allowed domains list"

        # Launch browser if needed (lazy init)
        if not self.is_active:
            await self.launch()

        try:
            logger.info(f"Navigating to: {url}")
            response = await self._page.goto(url, wait_until="domcontentloaded")

            # Check if redirect went to disallowed domain
            final_url = self._page.url
            if final_url != url and not self.domain_policy.is_allowed(final_url):
                logger.warning(f"Redirect blocked: {url} -> {final_url}")
                return (
                    f"Navigation blocked: redirected to disallowed domain {final_url}"
                )

            # Invalidate refs (page content changed)
            self._ref_map = {}

            # Get page title
            title = await self._page.title()
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
        if not self.is_active:
            return "Browser not active. Use browser_navigate first."

        try:
            await self._page.go_back(wait_until="domcontentloaded")
            self._ref_map = {}  # Invalidate refs
            title = await self._page.title()
            logger.info(f"Navigated back: {title}")
            return f"Navigated back to: {title}\n\nUse browser_snapshot to see page content."
        except Exception as e:
            logger.error(f"Back navigation failed: {e}")
            return f"Back navigation failed: {str(e)}"

    async def _get_accessibility_tree(self) -> dict | None:
        """Get accessibility tree via CDP (Chrome DevTools Protocol).

        Playwright 1.58+ removed page.accessibility.snapshot(), so we use
        CDP's Accessibility.getFullAXTree instead and reconstruct the tree.

        Returns:
            Dict tree compatible with SnapshotTransformer, or None on error.
        """
        try:
            # Create CDP session
            client = await self._page.context.new_cdp_session(self._page)

            try:
                # Get full accessibility tree from CDP
                response = await client.send("Accessibility.getFullAXTree")
                nodes = response.get("nodes", [])

                if not nodes:
                    logger.debug("CDP returned empty accessibility tree")
                    return None

                # Build node lookup by ID
                node_map = {node["nodeId"]: node for node in nodes}

                # Helper to extract role string from CDP role object
                def get_role(node: dict) -> str:
                    role_obj = node.get("role", {})
                    value = role_obj.get("value", "")

                    # Normalize role names (CDP uses internal names like "RootWebArea")
                    role_map = {
                        "RootWebArea": "WebArea",
                        "WebArea": "WebArea",
                        "GenericContainer": "group",
                        "StaticText": None,  # Skip - leaf noise
                        "InlineTextBox": None,  # Skip - leaf noise
                    }

                    # Use mapping if available, otherwise keep lowercase
                    if value in role_map:
                        return role_map[value]
                    return value.lower() if value else ""

                # Helper to extract name from CDP name object
                def get_name(node: dict) -> str:
                    name_obj = node.get("name", {})
                    return name_obj.get("value", "") if isinstance(name_obj, dict) else ""

                # Helper to extract properties dict
                def get_properties(node: dict) -> dict:
                    props = {}
                    for prop in node.get("properties", []):
                        prop_name = prop.get("name", "")
                        prop_value = prop.get("value", {})

                        # Extract actual value based on type
                        if isinstance(prop_value, dict):
                            if "value" in prop_value:
                                props[prop_name] = prop_value["value"]
                        else:
                            props[prop_name] = prop_value

                    return props

                # Recursive function to build tree
                def build_tree(node_id: str) -> dict | None:
                    if node_id not in node_map:
                        return None

                    cdp_node = node_map[node_id]

                    # Skip ignored nodes (but include their children)
                    if cdp_node.get("ignored", False):
                        # Flatten through ignored nodes
                        children = []
                        for child_id in cdp_node.get("childIds", []):
                            child = build_tree(child_id)
                            if child:
                                children.append(child)
                        # Return children directly (unwrapped)
                        if len(children) == 1:
                            return children[0]
                        elif children:
                            return {"children": children}
                        return None

                    # Get role and skip internal leaf nodes
                    role = get_role(cdp_node)
                    if role is None:  # Explicitly filtered out (StaticText, etc.)
                        return None

                    # Build node dict
                    tree_node = {}

                    if role:
                        tree_node["role"] = role

                    name = get_name(cdp_node)
                    if name:
                        tree_node["name"] = name

                    # Extract properties
                    props = get_properties(cdp_node)
                    if "level" in props:
                        tree_node["level"] = props["level"]
                    if "checked" in props:
                        tree_node["checked"] = props["checked"]
                    if "disabled" in props:
                        tree_node["disabled"] = props["disabled"]
                    if "value" in props and props["value"]:
                        tree_node["value"] = props["value"]

                    # Recursively build children
                    children = []
                    for child_id in cdp_node.get("childIds", []):
                        child = build_tree(child_id)
                        if child:
                            # Handle flattened children from ignored nodes
                            if isinstance(child, list):
                                children.extend(child)
                            elif isinstance(child, dict) and "children" in child and "role" not in child:
                                # Unwrap container with only children
                                children.extend(child["children"])
                            else:
                                children.append(child)

                    if children:
                        tree_node["children"] = children

                    return tree_node

                # Find root node (usually first node)
                root_id = nodes[0]["nodeId"] if nodes else None
                if not root_id:
                    return None

                tree = build_tree(root_id)
                return tree

            finally:
                # Clean up CDP session
                await client.detach()

        except Exception as e:
            logger.error(f"CDP accessibility tree extraction failed: {e}")
            return None

    async def snapshot(self) -> str:
        """Take accessibility snapshot with numbered element refs.

        Returns:
            Formatted snapshot text with [ref] annotations.
        """
        if not self.is_active:
            return "Browser not active. Use browser_navigate first."

        try:
            # Get accessibility snapshot via CDP
            a11y_tree = await self._get_accessibility_tree()

            if not a11y_tree:
                return "Page snapshot empty (no accessible content)"

            # Transform to indexed format
            formatted_text, ref_map = self.snapshot_transformer.transform(a11y_tree)

            # Store ref map for element interaction
            self._ref_map = ref_map

            # Add header with metadata
            title = await self._page.title()
            url = self._page.url
            header = f"Page: {title}\nURL: {url}\nInteractive elements: {len(ref_map)}\n\n"

            logger.info(f"Snapshot captured: {len(ref_map)} interactive elements")
            return header + formatted_text

        except Exception as e:
            logger.error(f"Snapshot failed: {e}")
            return f"Snapshot failed: {str(e)}"

    async def click(self, ref: int) -> str:
        """Click element by reference number.

        Args:
            ref: Element reference from snapshot.

        Returns:
            Confirmation message or error.
        """
        if not self.is_active:
            return "Browser not active. Use browser_navigate first."

        if ref not in self._ref_map:
            return (
                f"Invalid element reference: {ref}\n"
                "The page may have changed. Use browser_snapshot to get current refs."
            )

        try:
            node = self._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")

            logger.info(f"Clicking element {ref}: {name} ({role})")

            # Try to locate element by role and name
            try:
                locator = self._page.get_by_role(role, name=name)
                await locator.click(timeout=self.timeout_seconds * 1000)
            except Exception:
                # Fallback: try by text if it's a link or button
                if role in ("link", "button") and name:
                    locator = self._page.get_by_text(name, exact=False)
                    await locator.first.click(timeout=self.timeout_seconds * 1000)
                else:
                    raise

            # Invalidate refs (page may have changed)
            self._ref_map = {}

            return (
                f"Clicked: {name} ({role})\n"
                "Page may have changed. Use browser_snapshot to see current state."
            )

        except Exception as e:
            logger.error(f"Click failed: {e}")
            return f"Click failed: {str(e)}\nThe element may not be clickable or visible."

    async def type_text(self, ref: int, text: str, press_enter: bool = False) -> str:
        """Type text into input element.

        Args:
            ref: Element reference from snapshot.
            text: Text to type.
            press_enter: Whether to press Enter after typing.

        Returns:
            Confirmation message or error.
        """
        if not self.is_active:
            return "Browser not active. Use browser_navigate first."

        if ref not in self._ref_map:
            return (
                f"Invalid element reference: {ref}\n"
                "The page may have changed. Use browser_snapshot to get current refs."
            )

        try:
            node = self._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")

            logger.info(f"Typing into element {ref}: {name} ({role})")

            # Locate input element
            locator = self._page.get_by_role(role, name=name)

            # Clear and type
            await locator.clear(timeout=self.timeout_seconds * 1000)
            await locator.fill(text, timeout=self.timeout_seconds * 1000)

            # Press Enter if requested
            if press_enter:
                await locator.press("Enter")
                # Invalidate refs (page may have changed)
                self._ref_map = {}
                return (
                    f"Typed '{text}' and pressed Enter in: {name}\n"
                    "Page may have changed. Use browser_snapshot to see current state."
                )

            return f"Typed '{text}' into: {name}"

        except Exception as e:
            logger.error(f"Type failed: {e}")
            return f"Type failed: {str(e)}\nThe element may not be an input or may not be visible."

    async def select_option(self, ref: int, value: str) -> str:
        """Select dropdown option.

        Args:
            ref: Element reference from snapshot.
            value: Option value or text to select.

        Returns:
            Confirmation message or error.
        """
        if not self.is_active:
            return "Browser not active. Use browser_navigate first."

        if ref not in self._ref_map:
            return (
                f"Invalid element reference: {ref}\n"
                "The page may have changed. Use browser_snapshot to get current refs."
            )

        try:
            node = self._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")

            logger.info(f"Selecting option in element {ref}: {name} ({role})")

            # Locate select element
            locator = self._page.get_by_role(role, name=name)

            # Try to select by value, then by label
            try:
                await locator.select_option(value=value, timeout=self.timeout_seconds * 1000)
            except Exception:
                await locator.select_option(label=value, timeout=self.timeout_seconds * 1000)

            return f"Selected '{value}' in: {name}"

        except Exception as e:
            logger.error(f"Select failed: {e}")
            return f"Select failed: {str(e)}\nThe element may not be a dropdown or the option may not exist."

    async def scroll(self, direction: str, amount: str = "page") -> str:
        """Scroll the page.

        Args:
            direction: "up" or "down".
            amount: "page" (full viewport) or "half" (half viewport).

        Returns:
            Confirmation message or error.
        """
        if not self.is_active:
            return "Browser not active. Use browser_navigate first."

        try:
            # Calculate scroll distance
            if amount == "half":
                distance = self.viewport_height // 2
            else:
                distance = self.viewport_height

            # Determine scroll direction
            if direction.lower() == "up":
                distance = -distance

            # Execute scroll
            await self._page.evaluate(f"window.scrollBy(0, {distance})")

            logger.info(f"Scrolled {direction} by {abs(distance)}px")
            return f"Scrolled {direction} ({amount})"

        except Exception as e:
            logger.error(f"Scroll failed: {e}")
            return f"Scroll failed: {str(e)}"

    async def screenshot(self, full_page: bool = False) -> str:
        """Take screenshot and save to workspace.

        Args:
            full_page: Capture full scrollable page (default: viewport only).

        Returns:
            Relative path to screenshot file or error.
        """
        if not self.is_active:
            return "Browser not active. Use browser_navigate first."

        try:
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
            file_path = self.screenshots_dir / filename

            # Take screenshot
            await self._page.screenshot(path=str(file_path), full_page=full_page)

            # Return relative path from workspace root
            rel_path = file_path.relative_to(self.workspace_path)

            logger.info(f"Screenshot saved: {rel_path}")
            return f"Screenshot saved: {rel_path}"

        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return f"Screenshot failed: {str(e)}"

    async def get_tabs(self) -> str:
        """List all open tabs.

        Returns:
            Formatted list of tabs with indices.
        """
        if not self.is_active:
            return "Browser not active. Use browser_navigate first."

        try:
            pages = self._context.pages
            lines = ["Open tabs:"]

            for i, page in enumerate(pages):
                title = await page.title()
                url = page.url
                active = " (active)" if page == self._page else ""
                lines.append(f"  [{i}] {title} - {url}{active}")

            logger.info(f"Listed {len(pages)} tabs")
            return "\n".join(lines)

        except Exception as e:
            logger.error(f"List tabs failed: {e}")
            return f"List tabs failed: {str(e)}"

    async def switch_tab(self, index: int) -> str:
        """Switch to tab by index.

        Args:
            index: Tab index from get_tabs.

        Returns:
            Confirmation message or error.
        """
        if not self.is_active:
            return "Browser not active. Use browser_navigate first."

        try:
            pages = self._context.pages

            if index < 0 or index >= len(pages):
                return f"Invalid tab index: {index}. Use browser_tabs to see available tabs."

            # Switch to page
            self._page = pages[index]
            self._page.set_default_timeout(self.timeout_seconds * 1000)

            # Re-register navigation handler
            self._page.on("framenavigated", self._handle_frame_navigated)

            # Invalidate refs (different page)
            self._ref_map = {}

            title = await self._page.title()
            url = self._page.url

            logger.info(f"Switched to tab {index}: {title}")
            return f"Switched to tab {index}: {title}\nURL: {url}\n\nUse browser_snapshot to see page content."

        except Exception as e:
            logger.error(f"Switch tab failed: {e}")
            return f"Switch tab failed: {str(e)}"

    async def _save_cookies(self) -> None:
        """Save browser cookies to workspace storage."""
        if not self._context:
            return

        try:
            # Ensure .openpaw directory exists
            self.cookie_file.parent.mkdir(parents=True, exist_ok=True)

            # Save storage state
            storage_state = await self._context.storage_state()
            with open(self.cookie_file, "w") as f:
                json.dump(storage_state, f, indent=2)

            logger.info(f"Cookies saved to {self.cookie_file}")

        except Exception as e:
            logger.warning(f"Failed to save cookies: {e}")

    async def _load_cookies(self) -> None:
        """Load browser cookies from workspace storage.

        Note: This is called during context creation via storage_state kwarg,
        not as a separate method. This is here for documentation.
        """
        pass

    def _handle_frame_navigated(self, frame) -> None:
        """Handle frame navigation events for redirect detection.

        Args:
            frame: Playwright frame object.
        """
        # Check if this is the main frame
        if frame == self._page.main_frame:
            url = frame.url

            # Validate domain (log warning, don't block — already navigated)
            if not self.domain_policy.is_allowed(url):
                logger.warning(
                    f"Page navigated to disallowed domain: {url}. "
                    "This may have been a redirect."
                )
