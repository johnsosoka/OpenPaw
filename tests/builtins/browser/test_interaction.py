"""Tests for BrowserInteraction component."""

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
async def test_click_resolves_ref_from_ref_map(config: dict, mock_playwright):
    """Test click uses ref map to locate element."""
    session = BrowserSession(config)
    interaction = session._interaction

    # Set up ref map manually (simulating snapshot result)
    session._ref_map = {1: {"role": "button", "name": "Login"}}

    # Mock locator
    mock_locator = AsyncMock()
    mock_playwright["page"].get_by_role.return_value = mock_locator

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        result = await interaction.click(1)

    assert "clicked" in result.lower() or "login" in result.lower()
    mock_locator.click.assert_called_once()


@pytest.mark.asyncio
async def test_click_with_invalid_ref_returns_error(config: dict, mock_playwright):
    """Test click with invalid ref returns helpful error."""
    session = BrowserSession(config)
    interaction = session._interaction
    session._ref_map = {}

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        result = await interaction.click(999)

    assert "invalid" in result.lower()
    assert "snapshot" in result.lower()


@pytest.mark.asyncio
async def test_click_returns_error_if_not_active(config: dict):
    """Test click returns error when browser not active."""
    session = BrowserSession(config)
    interaction = session._interaction

    result = await interaction.click(1)
    assert "not active" in result.lower()


@pytest.mark.asyncio
async def test_type_text_fills_input(config: dict, mock_playwright):
    """Test type_text fills element with text."""
    session = BrowserSession(config)
    interaction = session._interaction
    session._ref_map = {1: {"role": "textbox", "name": "Username"}}

    mock_locator = AsyncMock()
    mock_playwright["page"].get_by_role.return_value = mock_locator

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        result = await interaction.type_text(1, "testuser")

    assert "typed" in result.lower()
    mock_locator.clear.assert_called_once()
    mock_locator.fill.assert_called_once_with("testuser", timeout=30000)


@pytest.mark.asyncio
async def test_type_text_with_enter_invalidates_refs(config: dict, mock_playwright):
    """Test type with press_enter invalidates ref map."""
    session = BrowserSession(config)
    interaction = session._interaction
    session._ref_map = {1: {"role": "textbox", "name": "Search"}}

    mock_locator = AsyncMock()
    mock_playwright["page"].get_by_role.return_value = mock_locator

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        await interaction.type_text(1, "query", press_enter=True)

    # Refs should be cleared after pressing Enter
    assert len(session._ref_map) == 0
    mock_locator.press.assert_called_once_with("Enter")


@pytest.mark.asyncio
async def test_type_text_returns_error_if_not_active(config: dict):
    """Test type_text returns error when browser not active."""
    session = BrowserSession(config)
    interaction = session._interaction

    result = await interaction.type_text(1, "test")
    assert "not active" in result.lower()


@pytest.mark.asyncio
async def test_select_option(config: dict, mock_playwright):
    """Test select_option selects dropdown value."""
    session = BrowserSession(config)
    interaction = session._interaction
    session._ref_map = {1: {"role": "combobox", "name": "Country"}}

    mock_locator = AsyncMock()
    mock_playwright["page"].get_by_role.return_value = mock_locator

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        result = await interaction.select_option(1, "USA")

    assert "selected" in result.lower()
    mock_locator.select_option.assert_called()


@pytest.mark.asyncio
async def test_select_option_returns_error_if_not_active(config: dict):
    """Test select_option returns error when browser not active."""
    session = BrowserSession(config)
    interaction = session._interaction

    result = await interaction.select_option(1, "USA")
    assert "not active" in result.lower()


@pytest.mark.asyncio
async def test_screenshot_saves_to_workspace(config: dict, tmp_path: Path, mock_playwright):
    """Test screenshot saves to correct path."""
    session = BrowserSession(config)
    interaction = session._interaction

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        result = await interaction.screenshot()

    assert "screenshot" in result.lower()
    assert "workspace/screenshots/" in result
    mock_playwright["page"].screenshot.assert_called_once()


@pytest.mark.asyncio
async def test_screenshot_returns_error_if_not_active(config: dict):
    """Test screenshot returns error when browser not active."""
    session = BrowserSession(config)
    interaction = session._interaction

    result = await interaction.screenshot()
    assert "not active" in result.lower()


@pytest.mark.asyncio
async def test_execute_js_evaluates_script(config: dict, mock_playwright):
    """Test execute_js evaluates script in page context."""
    session = BrowserSession(config)
    interaction = session._interaction

    mock_playwright["page"].evaluate = AsyncMock(return_value="result")

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        result = await interaction.execute_js("document.title")

    assert result == "result"
    mock_playwright["page"].evaluate.assert_called_once()


@pytest.mark.asyncio
async def test_execute_js_returns_error_if_not_active(config: dict):
    """Test execute_js returns error when browser not active."""
    session = BrowserSession(config)
    interaction = session._interaction

    result = await interaction.execute_js("document.title")
    assert "not active" in result.lower()
