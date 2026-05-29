"""Tests for BrowserLifecycle component."""

import json
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
async def test_lifecycle_launch_creates_browser(config: dict, mock_playwright):
    """Test lifecycle launch creates browser resources."""
    session = BrowserSession(config)
    lifecycle = session._lifecycle

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await lifecycle.launch()

    assert session.is_active
    mock_playwright["playwright"].chromium.launch.assert_called_once()
    mock_playwright["browser"].new_context.assert_called_once()
    mock_playwright["context"].new_page.assert_called_once()


@pytest.mark.asyncio
async def test_launch_is_idempotent(config: dict, mock_playwright):
    """Test launching multiple times doesn't create duplicate browsers."""
    session = BrowserSession(config)
    lifecycle = session._lifecycle

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await lifecycle.launch()
        await lifecycle.launch()  # Second launch should be no-op

    mock_playwright["playwright"].chromium.launch.assert_called_once()


@pytest.mark.asyncio
async def test_lifecycle_close_cleans_up(config: dict, mock_playwright):
    """Test lifecycle close cleans up browser resources."""
    session = BrowserSession(config)
    lifecycle = session._lifecycle

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await lifecycle.launch()
        await lifecycle.close()

    assert not session.is_active
    mock_playwright["page"].close.assert_called_once()
    mock_playwright["context"].close.assert_called_once()
    mock_playwright["browser"].close.assert_called_once()


@pytest.mark.asyncio
async def test_cookie_persistence_saves_on_close(config: dict, tmp_path: Path, mock_playwright):
    """Test cookie persistence saves to file on close."""
    config["persist_cookies"] = True
    session = BrowserSession(config)
    lifecycle = session._lifecycle

    storage_state = {"cookies": [{"name": "test", "value": "123"}], "origins": []}
    mock_playwright["context"].storage_state.return_value = storage_state

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await lifecycle.launch()
        await lifecycle.close()

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
    lifecycle = session._lifecycle

    with patch(
        "playwright.async_api.async_playwright",
        mock_playwright["async_playwright"],
    ):
        await lifecycle.launch()

    # Check context was created with storage state
    mock_playwright["browser"].new_context.assert_called_once()
    call_kwargs = mock_playwright["browser"].new_context.call_args.kwargs
    assert "storage_state" in call_kwargs
