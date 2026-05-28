"""Browser interaction: click, type, select, execute JS, and screenshot."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class BrowserInteraction:
    """Handles element interaction and JavaScript execution.

    Includes clicking, typing, selecting dropdown options, executing
    JavaScript, and taking screenshots.
    """

    def __init__(self, session: Any) -> None:
        """Initialize with parent BrowserSession.

        Args:
            session: The BrowserSession instance that owns this interaction.
        """
        self._session: Any = session

    @property
    def _timeout_seconds(self) -> int:
        return int(self._session.timeout_seconds)

    @property
    def _screenshots_dir(self) -> Path:
        return Path(self._session.screenshots_dir)

    @property
    def _workspace_path(self) -> Path:
        return Path(self._session.workspace_path)

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
        if not self._session.is_active:
            return "Browser not active. Use browser_navigate first."

        if ref not in self._session._ref_map:
            return (
                f"Invalid element reference: {ref}\n"
                "The page may have changed. Use browser_snapshot to get current refs."
            )

        try:
            node = self._session._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")

            logger.info(f"Clicking element {ref}: {name} ({role}) keep_refs={keep_refs}")

            # Try to locate element by role and name
            try:
                locator = self._session._page.get_by_role(role, name=name)
                await locator.click(timeout=self._timeout_seconds * 1000)
            except Exception:
                # Fallback: try by text if it's a link or button
                if role in ("link", "button") and name:
                    locator = self._session._page.get_by_text(name, exact=False)
                    await locator.first.click(timeout=self._timeout_seconds * 1000)
                else:
                    raise

            if keep_refs:
                # Wait for DOM to settle, then refresh snapshot
                try:
                    await self._session._page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass  # Best-effort wait; DOM may already be stable

                refreshed = await self._session._state.snapshot()
                return (
                    f"Clicked: {name} ({role})\n\n"
                    f"--- Refreshed snapshot ---\n{refreshed}"
                )

            # Invalidate refs (page may have changed)
            self._session._ref_map = {}

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
        if not self._session.is_active:
            return "Browser not active. Use browser_navigate first."

        if ref not in self._session._ref_map:
            return (
                f"Invalid element reference: {ref}\n"
                "The page may have changed. Use browser_snapshot to get current refs."
            )

        try:
            node = self._session._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")

            logger.info(f"Typing into element {ref}: {name} ({role})")

            # Locate input element
            locator = self._session._page.get_by_role(role, name=name)

            # Clear and type
            await locator.clear(timeout=self._timeout_seconds * 1000)
            await locator.fill(text, timeout=self._timeout_seconds * 1000)

            # Press Enter if requested
            if press_enter:
                await locator.press("Enter")
                # Invalidate refs (page may have changed)
                self._session._ref_map = {}
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
        if not self._session.is_active:
            return "Browser not active. Use browser_navigate first."

        if ref not in self._session._ref_map:
            return (
                f"Invalid element reference: {ref}\n"
                "The page may have changed. Use browser_snapshot to get current refs."
            )

        try:
            node = self._session._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")

            logger.info(f"Selecting option in element {ref}: {name} ({role})")

            # Locate select element
            locator = self._session._page.get_by_role(role, name=name)

            # Try to select by value, then by label
            try:
                await locator.select_option(value=value, timeout=self._timeout_seconds * 1000)
            except Exception:
                await locator.select_option(label=value, timeout=self._timeout_seconds * 1000)

            return f"Selected '{value}' in: {name}"

        except Exception as e:
            logger.error(f"Select failed: {e}")
            return f"Select failed: {str(e)}\nThe element may not be a dropdown or the option may not exist."

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
        if not self._session.is_active:
            return "Browser not active. Use browser_navigate first."

        try:
            logger.info(f"Executing JS (length={len(script)})")

            if arg is not None:
                result = await self._session._page.evaluate(script, arg)
            else:
                result = await self._session._page.evaluate(script)

            if result is None:
                return "Script executed (returned null/undefined)"

            if isinstance(result, str):
                return result

            return json.dumps(result, default=str, ensure_ascii=False)

        except Exception as e:
            logger.error(f"JS execution failed: {e}")
            return f"JS execution failed: {str(e)}"

    async def screenshot(self, full_page: bool = False) -> str:
        """Take screenshot and save to workspace.

        Args:
            full_page: Capture full scrollable page (default: viewport only).

        Returns:
            Relative path to screenshot file or error.
        """
        if not self._session.is_active:
            return "Browser not active. Use browser_navigate first."

        try:
            # Generate filename with timestamp
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
            file_path = self._screenshots_dir / filename

            # Take screenshot
            await self._session._page.screenshot(path=str(file_path), full_page=full_page)

            # Return relative path from workspace root
            rel_path = file_path.relative_to(self._workspace_path)

            logger.info(f"Screenshot saved: {rel_path}")
            return f"Screenshot saved: {rel_path}"

        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return f"Screenshot failed: {str(e)}"
