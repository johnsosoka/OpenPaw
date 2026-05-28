"""Tests for BrowserState component."""

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

    # Mock CDP session for accessibility tree
    mock_cdp_session = AsyncMock()
    mock_cdp_session.send = AsyncMock(
        return_value={
            "nodes": [
                {
                    "nodeId": "1",
                    "role": {"type": "internalRole", "value": "RootWebArea"},
                    "name": {"type": "computedString", "value": "Test Page"},
                    "properties": [],
                    "childIds": ["2", "3"],
                    "ignored": False,
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
    )
    mock_cdp_session.detach = AsyncMock()

    mock_context.new_cdp_session = AsyncMock(return_value=mock_cdp_session)
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
async def test_snapshot_transforms_accessibility_tree(config: dict, mock_playwright):
    """Test snapshot calls transformer and stores ref map."""
    session = BrowserSession(config)
    state = session._state

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        result = await state.snapshot()

    # Should have refs for interactive elements
    assert "[1]" in result or "[2]" in result
    assert len(session._ref_map) > 0
    assert "Login" in result or "Username" in result


@pytest.mark.asyncio
async def test_snapshot_returns_error_if_not_active(config: dict):
    """Test snapshot returns error when browser not active."""
    session = BrowserSession(config)
    state = session._state

    result = await state.snapshot()
    assert "not active" in result.lower()


@pytest.mark.asyncio
async def test_get_tabs_lists_all_pages(config: dict, mock_playwright):
    """Test get_tabs lists all open pages."""
    session = BrowserSession(config)
    state = session._state

    # Mock multiple pages
    mock_page2 = AsyncMock()
    mock_page2.title = AsyncMock(return_value="Page 2")
    mock_page2.url = "https://example.com/page2"
    mock_playwright["context"].pages = [mock_playwright["page"], mock_page2]

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await session._lifecycle.launch()
        result = await state.get_tabs()

    assert "[0]" in result and "[1]" in result
    assert "Test Page" in result
    assert "Page 2" in result


@pytest.mark.asyncio
async def test_get_tabs_returns_error_if_not_active(config: dict):
    """Test get_tabs returns error when browser not active."""
    session = BrowserSession(config)
    state = session._state

    result = await state.get_tabs()
    assert "not active" in result.lower()
