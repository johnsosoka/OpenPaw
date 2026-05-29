"""Tests for BrowserNavigation component."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Mock playwright module before importing BrowserSession
mock_playwright_module = MagicMock()
sys.modules["playwright"] = mock_playwright_module
sys.modules["playwright.async_api"] = MagicMock()

from openpaw.builtins.tools.browser.session import BrowserSession  # noqa: E402


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
    mock_pw = MagicMock()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()

    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_page.set_default_timeout = Mock()
    mock_page.on = Mock()
    mock_page.goto = AsyncMock(return_value=Mock(status=200))
    mock_page.title = AsyncMock(return_value="Test Page")
    mock_page.url = "https://example.com"
    mock_page.main_frame = Mock()
    mock_page.get_by_role = Mock()
    mock_page.go_back = AsyncMock()
    mock_page.evaluate = AsyncMock()
    mock_page.screenshot = AsyncMock()
    mock_page.close = AsyncMock()
    mock_page.context = mock_context

    mock_context.new_cdp_session = AsyncMock()
    mock_context.pages = [mock_page]
    mock_context.storage_state = AsyncMock(
        return_value={"cookies": [], "origins": []}
    )
    mock_context.close = AsyncMock()

    mock_browser.close = AsyncMock()

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
async def test_navigate_validates_domain_policy(config: dict, mock_playwright):
    """Test navigate validates domain before going."""
    config["allowed_domains"] = ["example.com"]
    session = BrowserSession(config)
    navigation = session._navigation

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        # Allowed domain should succeed
        result = await navigation.navigate("https://example.com/page")
        assert "example.com" in result or "Test Page" in result

        # Blocked domain should fail
        result = await navigation.navigate("https://blocked.com")
        assert "blocked" in result.lower()


@pytest.mark.asyncio
async def test_navigate_auto_launches_browser(config: dict, mock_playwright):
    """Test navigate auto-launches browser on first call."""
    session = BrowserSession(config)
    navigation = session._navigation

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await navigation.navigate("https://example.com")

    assert session.is_active
    mock_playwright["page"].goto.assert_called_once()


@pytest.mark.asyncio
async def test_navigate_checks_redirect_domain(config: dict, mock_playwright):
    """Test navigate checks domain after redirect."""
    config["allowed_domains"] = ["example.com"]
    session = BrowserSession(config)
    navigation = session._navigation

    # Mock a redirect to blocked domain
    mock_playwright["page"].url = "https://blocked.com"

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        result = await navigation.navigate("https://example.com")
        assert "blocked" in result.lower() or "disallowed" in result.lower()


@pytest.mark.asyncio
async def test_back_navigation_invalidates_refs(config: dict, mock_playwright):
    """Test back navigation clears ref map."""
    session = BrowserSession(config)
    navigation = session._navigation
    session._ref_map = {1: {"role": "button", "name": "Test"}}

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        await navigation.back()

    assert len(session._ref_map) == 0
    mock_playwright["page"].go_back.assert_called_once()


@pytest.mark.asyncio
async def test_back_returns_error_if_not_active(config: dict):
    """Test back returns error when browser not active."""
    session = BrowserSession(config)
    navigation = session._navigation

    result = await navigation.back()
    assert "not active" in result.lower()


@pytest.mark.asyncio
async def test_scroll_executes_javascript(config: dict, mock_playwright):
    """Test scroll executes page evaluation."""
    session = BrowserSession(config)
    navigation = session._navigation

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        await navigation.scroll("down", "page")

    mock_playwright["page"].evaluate.assert_called_once()
    call_arg = mock_playwright["page"].evaluate.call_args[0][0]
    assert "scrollBy" in call_arg
    assert "720" in call_arg  # viewport height


@pytest.mark.asyncio
async def test_scroll_returns_error_if_not_active(config: dict):
    """Test scroll returns error when browser not active."""
    session = BrowserSession(config)
    navigation = session._navigation

    result = await navigation.scroll("down", "page")
    assert "not active" in result.lower()


@pytest.mark.asyncio
async def test_switch_tab_changes_active_page(config: dict, mock_playwright):
    """Test switch tab changes active page."""
    session = BrowserSession(config)
    navigation = session._navigation

    # Mock multiple pages
    mock_page2 = AsyncMock()
    mock_page2.title = AsyncMock(return_value="Page 2")
    mock_page2.url = "https://example.com/page2"
    mock_page2.set_default_timeout = Mock()
    mock_page2.on = Mock()
    mock_playwright["context"].pages = [mock_playwright["page"], mock_page2]

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()

        # Switch to second tab
        result = await navigation.switch_tab(1)
        assert session._page == mock_page2
        assert "page 2" in result.lower() or "switched" in result.lower()


@pytest.mark.asyncio
async def test_switch_tab_invalid_index(config: dict, mock_playwright):
    """Test switch tab with invalid index returns error."""
    session = BrowserSession(config)
    navigation = session._navigation

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        result = await navigation.switch_tab(99)

    assert "invalid" in result.lower()


@pytest.mark.asyncio
async def test_switch_tab_returns_error_if_not_active(config: dict):
    """Test switch tab returns error when browser not active."""
    session = BrowserSession(config)
    navigation = session._navigation

    result = await navigation.switch_tab(0)
    assert "not active" in result.lower()
