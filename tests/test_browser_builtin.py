"""Tests for BrowserToolBuiltin."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from openpaw.builtins.base import BuiltinType
from openpaw.builtins.tools.browser import BrowserToolBuiltin


@pytest.fixture
def config(tmp_path: Path) -> dict:
    """Test configuration for browser builtin."""
    return {
        "workspace_path": str(tmp_path),
        "headless": True,
        "viewport_width": 1280,
        "viewport_height": 720,
        "timeout_seconds": 30,
        "allowed_domains": [],
        "blocked_domains": [],
    }


def test_metadata():
    """Test builtin metadata is correct."""
    assert BrowserToolBuiltin.metadata.name == "browser"
    assert BrowserToolBuiltin.metadata.display_name == "Web Browser"
    assert BrowserToolBuiltin.metadata.builtin_type == BuiltinType.TOOL
    assert BrowserToolBuiltin.metadata.group == "browser"
    assert "playwright" in BrowserToolBuiltin.metadata.prerequisites.packages


def test_initialization(config: dict):
    """Test builtin initializes with config."""
    builtin = BrowserToolBuiltin(config)
    assert builtin.config == config
    assert builtin._session is None


def test_get_langchain_tool_returns_list(config: dict):
    """Test get_langchain_tool returns list of 11 tools."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    assert isinstance(tools, list)
    assert len(tools) == 11


def test_tool_names_are_correct(config: dict):
    """Test all tool names follow expected pattern."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    expected_names = [
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_select",
        "browser_scroll",
        "browser_back",
        "browser_screenshot",
        "browser_close",
        "browser_tabs",
        "browser_switch_tab",
    ]

    tool_names = [tool.name for tool in tools]
    assert set(tool_names) == set(expected_names)


def test_tool_descriptions_exist(config: dict):
    """Test all tools have descriptions."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    for tool in tools:
        assert tool.description
        assert len(tool.description) > 20


def test_get_session_lazy_init(config: dict):
    """Test _get_session creates session on first call."""
    builtin = BrowserToolBuiltin(config)
    assert builtin._session is None

    session = builtin._get_session()
    assert session is not None
    assert builtin._session is session

    # Second call returns same session
    session2 = builtin._get_session()
    assert session2 is session


@pytest.mark.asyncio
async def test_cleanup_closes_session(config: dict):
    """Test cleanup delegates to session.close."""
    builtin = BrowserToolBuiltin(config)

    # Create mock session
    mock_session = AsyncMock()
    mock_session.is_active = True
    mock_session.close = AsyncMock()
    builtin._session = mock_session

    await builtin.cleanup()

    mock_session.close.assert_called_once()
    assert builtin._session is None


@pytest.mark.asyncio
async def test_cleanup_handles_no_session(config: dict):
    """Test cleanup works when no session exists."""
    builtin = BrowserToolBuiltin(config)
    await builtin.cleanup()  # Should not raise


@pytest.mark.asyncio
async def test_cleanup_handles_inactive_session(config: dict):
    """Test cleanup works when session is not active."""
    builtin = BrowserToolBuiltin(config)

    # Create mock inactive session
    mock_session = AsyncMock()
    mock_session.is_active = False
    builtin._session = mock_session

    await builtin.cleanup()  # Should not raise


def test_navigate_tool_has_url_parameter(config: dict):
    """Test navigate tool accepts url parameter."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    navigate_tool = next(t for t in tools if t.name == "browser_navigate")
    assert navigate_tool.args_schema is not None
    assert "url" in navigate_tool.args_schema.model_fields


def test_click_tool_has_ref_parameter(config: dict):
    """Test click tool accepts ref parameter."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    click_tool = next(t for t in tools if t.name == "browser_click")
    assert click_tool.args_schema is not None
    assert "ref" in click_tool.args_schema.model_fields


def test_type_tool_has_required_parameters(config: dict):
    """Test type tool has ref, text, and press_enter parameters."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    type_tool = next(t for t in tools if t.name == "browser_type")
    assert type_tool.args_schema is not None
    fields = type_tool.args_schema.model_fields
    assert "ref" in fields
    assert "text" in fields
    assert "press_enter" in fields


def test_scroll_tool_has_direction_and_amount(config: dict):
    """Test scroll tool has direction and amount parameters."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    scroll_tool = next(t for t in tools if t.name == "browser_scroll")
    assert scroll_tool.args_schema is not None
    fields = scroll_tool.args_schema.model_fields
    assert "direction" in fields
    assert "amount" in fields


def test_screenshot_tool_has_full_page_parameter(config: dict):
    """Test screenshot tool has full_page parameter."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    screenshot_tool = next(t for t in tools if t.name == "browser_screenshot")
    assert screenshot_tool.args_schema is not None
    assert "full_page" in screenshot_tool.args_schema.model_fields


def test_switch_tab_tool_has_index_parameter(config: dict):
    """Test switch_tab tool has index parameter."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    switch_tab_tool = next(t for t in tools if t.name == "browser_switch_tab")
    assert switch_tab_tool.args_schema is not None
    assert "index" in switch_tab_tool.args_schema.model_fields


def test_snapshot_tool_has_no_parameters(config: dict):
    """Test snapshot tool has no required parameters."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    snapshot_tool = next(t for t in tools if t.name == "browser_snapshot")
    # Tool should still work with no args
    assert snapshot_tool is not None


def test_back_tool_has_no_parameters(config: dict):
    """Test back tool has no required parameters."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    back_tool = next(t for t in tools if t.name == "browser_back")
    assert back_tool is not None


def test_close_tool_has_no_parameters(config: dict):
    """Test close tool has no required parameters."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    close_tool = next(t for t in tools if t.name == "browser_close")
    assert close_tool is not None


def test_tabs_tool_has_no_parameters(config: dict):
    """Test tabs tool has no required parameters."""
    builtin = BrowserToolBuiltin(config)
    tools = builtin.get_langchain_tool()

    tabs_tool = next(t for t in tools if t.name == "browser_tabs")
    assert tabs_tool is not None


@pytest.mark.asyncio
async def test_config_passes_through_to_session(config: dict):
    """Test builtin config is passed to BrowserSession."""
    builtin = BrowserToolBuiltin(config)

    with patch(
        "openpaw.builtins.tools.browser.BrowserSession"
    ) as MockSession:
        mock_instance = AsyncMock()
        MockSession.return_value = mock_instance

        session = builtin._get_session()

        # Check BrowserSession was called with config
        MockSession.assert_called_once_with(config)
