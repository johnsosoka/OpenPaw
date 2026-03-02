"""Tests for BrowserSession lifecycle and operations."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Mock playwright module before importing BrowserSession
mock_playwright_module = MagicMock()
sys.modules["playwright"] = mock_playwright_module
sys.modules["playwright.async_api"] = MagicMock()

from openpaw.builtins.tools.browser.session import BrowserSession


@pytest.fixture
def config(tmp_path: Path) -> dict:
    """Test configuration for browser session."""
    return {
        "workspace_path": str(tmp_path),
        "headless": True,
        "viewport_width": 1280,
        "viewport_height": 720,
        "timeout_seconds": 30,
        "downloads_dir": "workspace/downloads",
        "screenshots_dir": "workspace/screenshots",
        "persist_cookies": False,
        "allowed_domains": [],
        "blocked_domains": [],
        "max_snapshot_depth": 10,
    }


@pytest.fixture
def mock_playwright():
    """Mock Playwright module and instances."""
    # Mock the playwright module structure
    mock_pw = MagicMock()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()

    # Set up mock relationships
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_context.new_page = AsyncMock(return_value=mock_page)

    # Mock CDP session for accessibility tree (default simple tree)
    mock_cdp_session = AsyncMock()
    mock_cdp_session.send = AsyncMock(
        return_value={
            "nodes": [
                {
                    "nodeId": "1",
                    "role": {"type": "internalRole", "value": "RootWebArea"},
                    "name": {"type": "computedString", "value": "Test Page"},
                    "properties": [],
                    "childIds": [],
                    "ignored": False,
                }
            ]
        }
    )
    mock_cdp_session.detach = AsyncMock()

    # Page methods
    mock_page.set_default_timeout = Mock()  # Changed to Mock (not async)
    mock_page.on = Mock()  # Changed to Mock (not async)
    mock_page.goto = AsyncMock(return_value=Mock(status=200))
    mock_page.title = AsyncMock(return_value="Test Page")
    mock_page.url = "https://example.com"
    mock_page.main_frame = Mock()
    mock_page.get_by_role = Mock()  # Changed to Mock (not async)
    mock_page.go_back = AsyncMock()
    mock_page.evaluate = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_page.close = AsyncMock()
    mock_page.context = mock_context  # Add context property

    # Context CDP session support
    mock_context.new_cdp_session = AsyncMock(return_value=mock_cdp_session)

    # Context methods
    mock_context.pages = [mock_page]
    mock_context.storage_state = AsyncMock(
        return_value={"cookies": [], "origins": []}
    )
    mock_context.close = AsyncMock()

    # Browser methods
    mock_browser.close = AsyncMock()

    # Mock the async_playwright() function
    # It returns an object that has async .start() and .stop() methods
    async_playwright_obj = MagicMock()
    async_playwright_obj.start = AsyncMock(return_value=mock_pw)
    mock_async_playwright = MagicMock(return_value=async_playwright_obj)
    mock_pw.stop = AsyncMock()

    return {
        "playwright": mock_pw,
        "browser": mock_browser,
        "context": mock_context,
        "page": mock_page,
        "async_playwright": mock_async_playwright,
    }


@pytest.mark.asyncio
async def test_session_initialization(config: dict):
    """Test BrowserSession initialization without launching."""
    session = BrowserSession(config)

    assert session.headless is True
    assert session.viewport_width == 1280
    assert session.viewport_height == 720
    assert session.timeout_seconds == 30
    assert not session.is_active
    assert session._browser is None
    assert session._page is None


@pytest.mark.asyncio
async def test_launch_creates_browser(config: dict, mock_playwright):
    """Test browser launch creates all resources."""
    session = BrowserSession(config)

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()

    assert session.is_active
    mock_playwright["playwright"].chromium.launch.assert_called_once()
    mock_playwright["browser"].new_context.assert_called_once()
    mock_playwright["context"].new_page.assert_called_once()


@pytest.mark.asyncio
async def test_launch_is_idempotent(config: dict, mock_playwright):
    """Test launching multiple times doesn't create duplicate browsers."""
    session = BrowserSession(config)

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()
        await session.launch()  # Second launch should be no-op

    # Should only be called once
    mock_playwright["playwright"].chromium.launch.assert_called_once()


@pytest.mark.asyncio
async def test_close_cleans_up_resources(config: dict, mock_playwright):
    """Test close cleans up browser/context/page."""
    session = BrowserSession(config)

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()
        await session.close()

    assert not session.is_active
    mock_playwright["page"].close.assert_called_once()
    mock_playwright["context"].close.assert_called_once()
    mock_playwright["browser"].close.assert_called_once()


@pytest.mark.asyncio
async def test_navigate_validates_domain_policy(config: dict, mock_playwright):
    """Test navigate validates domain before going."""
    config["allowed_domains"] = ["example.com"]
    session = BrowserSession(config)

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        # Allowed domain should succeed
        result = await session.navigate("https://example.com/page")
        assert "example.com" in result or "Test Page" in result

        # Blocked domain should fail
        result = await session.navigate("https://blocked.com")
        assert "blocked" in result.lower()


@pytest.mark.asyncio
async def test_navigate_launches_browser_if_needed(config: dict, mock_playwright):
    """Test navigate auto-launches browser on first call."""
    session = BrowserSession(config)

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.navigate("https://example.com")

    assert session.is_active
    mock_playwright["page"].goto.assert_called_once()


@pytest.mark.asyncio
async def test_navigate_checks_redirect_domain(config: dict, mock_playwright):
    """Test navigate checks domain after redirect."""
    config["allowed_domains"] = ["example.com"]
    session = BrowserSession(config)

    # Mock a redirect to blocked domain
    mock_playwright["page"].url = "https://blocked.com"

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        result = await session.navigate("https://example.com")
        assert "blocked" in result.lower() or "disallowed" in result.lower()


@pytest.mark.asyncio
async def test_snapshot_transforms_accessibility_tree(config: dict, mock_playwright):
    """Test snapshot calls transformer and stores ref map."""
    session = BrowserSession(config)

    # Mock CDP response with accessibility tree nodes
    mock_cdp_response = {
        "nodes": [
            {
                "nodeId": "1",
                "role": {"type": "internalRole", "value": "RootWebArea"},
                "name": {"type": "computedString", "value": "Test Page"},
                "childIds": ["2", "3"],
                "ignored": False,
                "properties": [],
            },
            {
                "nodeId": "2",
                "role": {"type": "role", "value": "button"},
                "name": {"type": "computedString", "value": "Login"},
                "childIds": [],
                "ignored": False,
                "properties": [],
            },
            {
                "nodeId": "3",
                "role": {"type": "role", "value": "textbox"},
                "name": {"type": "computedString", "value": "Username"},
                "childIds": [],
                "ignored": False,
                "properties": [],
            },
        ]
    }

    # Mock CDP session
    mock_cdp_session = AsyncMock()
    mock_cdp_session.send = AsyncMock(return_value=mock_cdp_response)
    mock_cdp_session.detach = AsyncMock()
    mock_playwright["context"].new_cdp_session = AsyncMock(return_value=mock_cdp_session)

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()
        result = await session.snapshot()

    # Should have refs for interactive elements
    assert "[1]" in result or "[2]" in result
    assert len(session._ref_map) > 0
    assert "Login" in result or "Username" in result


@pytest.mark.asyncio
async def test_snapshot_returns_error_if_not_active(config: dict):
    """Test snapshot returns error when browser not active."""
    session = BrowserSession(config)
    result = await session.snapshot()
    assert "not active" in result.lower()


@pytest.mark.asyncio
async def test_click_resolves_ref_from_ref_map(config: dict, mock_playwright):
    """Test click uses ref map to locate element."""
    session = BrowserSession(config)

    # Set up ref map manually (simulating snapshot result)
    session._ref_map = {1: {"role": "button", "name": "Login"}}

    # Mock locator
    mock_locator = AsyncMock()
    mock_playwright["page"].get_by_role.return_value = mock_locator

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()
        result = await session.click(1)

    assert "clicked" in result.lower() or "login" in result.lower()
    mock_locator.click.assert_called_once()


@pytest.mark.asyncio
async def test_click_with_invalid_ref_returns_error(config: dict, mock_playwright):
    """Test click with invalid ref returns helpful error."""
    session = BrowserSession(config)
    session._ref_map = {}

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()
        result = await session.click(999)

    assert "invalid" in result.lower()
    assert "snapshot" in result.lower()


@pytest.mark.asyncio
async def test_type_text_fills_input(config: dict, mock_playwright):
    """Test type_text fills element with text."""
    session = BrowserSession(config)
    session._ref_map = {1: {"role": "textbox", "name": "Username"}}

    mock_locator = AsyncMock()
    mock_playwright["page"].get_by_role.return_value = mock_locator

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()
        result = await session.type_text(1, "testuser")

    assert "typed" in result.lower()
    mock_locator.clear.assert_called_once()
    mock_locator.fill.assert_called_once_with("testuser", timeout=30000)


@pytest.mark.asyncio
async def test_type_text_with_enter_invalidates_refs(config: dict, mock_playwright):
    """Test type with press_enter invalidates ref map."""
    session = BrowserSession(config)
    session._ref_map = {1: {"role": "textbox", "name": "Search"}}

    mock_locator = AsyncMock()
    mock_playwright["page"].get_by_role.return_value = mock_locator

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()
        await session.type_text(1, "query", press_enter=True)

    # Refs should be cleared after pressing Enter
    assert len(session._ref_map) == 0
    mock_locator.press.assert_called_once_with("Enter")


@pytest.mark.asyncio
async def test_cookie_persistence_saves_on_close(config: dict, tmp_path: Path, mock_playwright):
    """Test cookie persistence saves to file on close."""
    config["persist_cookies"] = True
    session = BrowserSession(config)

    storage_state = {"cookies": [{"name": "test", "value": "123"}], "origins": []}
    mock_playwright["context"].storage_state.return_value = storage_state

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()
        await session.close()

    # Check cookie file was created
    cookie_file = tmp_path / "data" / "browser_cookies.json"
    assert cookie_file.exists()

    with open(cookie_file) as f:
        saved_state = json.load(f)
        assert saved_state["cookies"][0]["name"] == "test"


@pytest.mark.asyncio
async def test_cookie_persistence_loads_on_launch(config: dict, tmp_path: Path, mock_playwright):
    """Test cookie persistence loads from file on launch."""
    config["persist_cookies"] = True

    # Create cookie file
    cookie_file = tmp_path / "data" / "browser_cookies.json"
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    storage_state = {"cookies": [{"name": "test", "value": "456"}], "origins": []}
    with open(cookie_file, "w") as f:
        json.dump(storage_state, f)

    session = BrowserSession(config)

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()

    # Check context was created with storage state
    mock_playwright["browser"].new_context.assert_called_once()
    call_kwargs = mock_playwright["browser"].new_context.call_args.kwargs
    assert "storage_state" in call_kwargs


@pytest.mark.asyncio
async def test_tab_management(config: dict, mock_playwright):
    """Test tab listing and switching."""
    session = BrowserSession(config)

    # Mock multiple pages
    mock_page2 = AsyncMock()
    mock_page2.title = AsyncMock(return_value="Page 2")
    mock_page2.url = "https://example.com/page2"
    mock_page2.set_default_timeout = Mock()  # Non-async method
    mock_page2.on = Mock()  # Non-async method
    mock_playwright["context"].pages = [mock_playwright["page"], mock_page2]

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()

        # List tabs
        result = await session.get_tabs()
        assert "[0]" in result and "[1]" in result

        # Switch to second tab
        result = await session.switch_tab(1)
        assert session._page == mock_page2
        assert "page 2" in result.lower() or "switched" in result.lower()


@pytest.mark.asyncio
async def test_screenshot_saves_to_workspace(config: dict, tmp_path: Path, mock_playwright):
    """Test screenshot saves to correct path."""
    session = BrowserSession(config)

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()
        result = await session.screenshot()

    assert "screenshot" in result.lower()
    assert "workspace/screenshots/" in result
    mock_playwright["page"].screenshot.assert_called_once()


@pytest.mark.asyncio
async def test_scroll_executes_javascript(config: dict, mock_playwright):
    """Test scroll executes page evaluation."""
    session = BrowserSession(config)

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()
        await session.scroll("down", "page")

    mock_playwright["page"].evaluate.assert_called_once()
    call_arg = mock_playwright["page"].evaluate.call_args[0][0]
    assert "scrollBy" in call_arg
    assert "720" in call_arg  # viewport height


@pytest.mark.asyncio
async def test_back_navigation_invalidates_refs(config: dict, mock_playwright):
    """Test back navigation clears ref map."""
    session = BrowserSession(config)
    session._ref_map = {1: {"role": "button", "name": "Test"}}

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session.launch()
        await session.back()

    assert len(session._ref_map) == 0
    mock_playwright["page"].go_back.assert_called_once()
