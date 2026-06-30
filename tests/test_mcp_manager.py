"""Unit tests for MCPManager — MultiServerMCPClient mocked to avoid network/subprocess."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.core.config.models.mcp import MCPServerConfig, WorkspaceMCPConfig
from openpaw.runtime.mcp.manager import MCPManager, _MCP_INSTALL_HINT

# Sentinel used to identify StreamableHttpConnection transport value.
_STREAMABLE_HTTP = "streamable_http"


# --- helpers ---


def _http_server(
    name: str = "svc",
    url: str = "http://example.com/mcp",
    *,
    enabled: bool = True,
    required: bool = False,
    tool_prefix: str | None = None,
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
) -> MCPServerConfig:
    return MCPServerConfig(
        name=name,
        transport="http",
        url=url,
        enabled=enabled,
        required=required,
        tool_prefix=tool_prefix,
        allowed_tools=allowed_tools or [],
        denied_tools=denied_tools or [],
    )


def _fake_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name

    def _model_copy(*, update: dict[str, Any] | None = None, deep: bool = False) -> MagicMock:
        copy = MagicMock()
        copy.name = (update or {}).get("name", name)
        copy.model_copy = MagicMock(side_effect=lambda **kw: _model_copy(**kw))
        return copy

    tool.model_copy = MagicMock(side_effect=lambda **kw: _model_copy(**kw))
    return tool


def _workspace_mcp(enabled: bool = True, servers: list[MCPServerConfig] | None = None) -> WorkspaceMCPConfig:
    return WorkspaceMCPConfig(enabled=enabled, servers=servers or [])


# --- disabled config ---


@pytest.mark.asyncio
async def test_disabled_config_is_noop() -> None:
    cfg = _workspace_mcp(enabled=False, servers=[_http_server()])
    manager = MCPManager(cfg, "test")

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient:
        await manager.connect()
        MockClient.assert_not_called()

    assert manager.get_tools() == []


@pytest.mark.asyncio
async def test_no_enabled_servers_is_noop() -> None:
    cfg = _workspace_mcp(enabled=True, servers=[_http_server(enabled=False)])
    manager = MCPManager(cfg, "test")

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient") as MockClient:
        await manager.connect()
        MockClient.assert_not_called()

    assert manager.get_tools() == []


# --- prefix behavior ---


@pytest.mark.asyncio
async def test_default_prefix_uses_server_name() -> None:
    tool = _fake_tool("get_forecast")
    server = _http_server(name="weather")
    cfg = _workspace_mcp(servers=[server])
    manager = MCPManager(cfg, "ws")

    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(return_value=[tool])

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
        await manager.connect()

    tools = manager.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "weather_get_forecast"


@pytest.mark.asyncio
async def test_empty_prefix_leaves_names_unchanged() -> None:
    tool = _fake_tool("search")
    server = _http_server(name="tools", tool_prefix="")
    cfg = _workspace_mcp(servers=[server])
    manager = MCPManager(cfg, "ws")

    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(return_value=[tool])

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
        await manager.connect()

    assert manager.get_tools()[0].name == "search"


@pytest.mark.asyncio
async def test_custom_prefix() -> None:
    tool = _fake_tool("calculate")
    server = _http_server(name="math", tool_prefix="mx_")
    cfg = _workspace_mcp(servers=[server])
    manager = MCPManager(cfg, "ws")

    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(return_value=[tool])

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
        await manager.connect()

    assert manager.get_tools()[0].name == "mx_calculate"


# --- allow/deny filters ---


@pytest.mark.asyncio
async def test_allowed_tools_filters_by_allowlist() -> None:
    tools = [_fake_tool("search"), _fake_tool("delete"), _fake_tool("list")]
    server = _http_server(name="svc", allowed_tools=["search", "list"], tool_prefix="")
    cfg = _workspace_mcp(servers=[server])
    manager = MCPManager(cfg, "ws")

    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(return_value=tools)

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
        await manager.connect()

    names = {t.name for t in manager.get_tools()}
    assert names == {"search", "list"}
    assert "delete" not in names


@pytest.mark.asyncio
async def test_denied_tools_excludes_tool() -> None:
    tools = [_fake_tool("read"), _fake_tool("write"), _fake_tool("delete")]
    server = _http_server(name="svc", denied_tools=["delete"], tool_prefix="")
    cfg = _workspace_mcp(servers=[server])
    manager = MCPManager(cfg, "ws")

    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(return_value=tools)

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
        await manager.connect()

    names = {t.name for t in manager.get_tools()}
    assert "delete" not in names
    assert {"read", "write"} == names


@pytest.mark.asyncio
async def test_allowed_applied_before_denied() -> None:
    """allowed_tools filters first; denied_tools then excludes from the allowed subset."""
    tools = [_fake_tool("a"), _fake_tool("b"), _fake_tool("c")]
    server = _http_server(name="svc", allowed_tools=["a", "b"], denied_tools=["b"], tool_prefix="")
    cfg = _workspace_mcp(servers=[server])
    manager = MCPManager(cfg, "ws")

    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(return_value=tools)

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
        await manager.connect()

    names = {t.name for t in manager.get_tools()}
    assert names == {"a"}


# --- required vs non-required failure ---


@pytest.mark.asyncio
async def test_required_server_failure_raises() -> None:
    server = _http_server(name="critical", required=True)
    cfg = _workspace_mcp(servers=[server])
    manager = MCPManager(cfg, "ws")

    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(side_effect=ConnectionError("refused"))

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="required but failed to connect"):
            await manager.connect()


@pytest.mark.asyncio
async def test_non_required_server_failure_skipped(caplog: Any) -> None:
    """Failed non-required server is skipped; other servers still load."""
    good_tool = _fake_tool("ok_tool")
    failing = _http_server(name="bad", url="http://bad.com/mcp", required=False)
    good = _http_server(name="good", url="http://good.com/mcp", required=False, tool_prefix="")
    cfg = _workspace_mcp(servers=[failing, good])
    manager = MCPManager(cfg, "ws")

    async def get_tools_side_effect(*, server_name: str | None = None) -> list[Any]:
        if server_name == "bad":
            raise ConnectionError("timeout")
        return [good_tool]

    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(side_effect=get_tools_side_effect)

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
        import logging
        with caplog.at_level(logging.WARNING):
            await manager.connect()

    tools = manager.get_tools()
    assert len(tools) == 1
    assert tools[0].name == "ok_tool"
    assert "bad" in caplog.text
    assert "skipping" in caplog.text


# --- missing extra raises actionable error ---


@pytest.mark.asyncio
async def test_missing_extra_raises_with_install_hint() -> None:
    server = _http_server()
    cfg = _workspace_mcp(servers=[server])
    manager = MCPManager(cfg, "ws")

    with patch.dict("sys.modules", {"langchain_mcp_adapters": None, "langchain_mcp_adapters.client": None}):
        with pytest.raises(RuntimeError) as exc_info:
            await manager.connect()

    assert "mcp" in str(exc_info.value).lower() or _MCP_INSTALL_HINT in str(exc_info.value)


# --- get_tools returns copy ---


@pytest.mark.asyncio
async def test_get_tools_returns_independent_copy() -> None:
    tool = _fake_tool("t")
    server = _http_server(tool_prefix="")
    cfg = _workspace_mcp(servers=[server])
    manager = MCPManager(cfg, "ws")

    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(return_value=[tool])

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
        await manager.connect()

    copy1 = manager.get_tools()
    copy1.clear()
    assert len(manager.get_tools()) == 1


# --- close resets state ---


@pytest.mark.asyncio
async def test_close_resets_state() -> None:
    tool = _fake_tool("t")
    server = _http_server(tool_prefix="")
    cfg = _workspace_mcp(servers=[server])
    manager = MCPManager(cfg, "ws")

    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(return_value=[tool])

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client):
        await manager.connect()

    assert len(manager.get_tools()) == 1
    await manager.close()
    assert manager.get_tools() == []
    assert manager._client is None
    assert manager._connected is False


# --- _server_to_connection ---
#
# These tests call the static method directly with a mock for the
# langchain_mcp_adapters import so no extra is required at test time.
# Note: http transport maps to transport="streamable_http" in the TypedDict.


def _patch_mcp_types() -> Any:
    """Return a context manager that stubs the langchain_mcp_adapters TypedDicts."""
    # The static method imports SSEConnection / StdioConnection / StreamableHttpConnection
    # from langchain_mcp_adapters.client.  We supply plain dicts as stand-ins so that
    # the method can still build and return a dict without the mcp extra installed.
    import sys
    from unittest.mock import MagicMock

    fake_module = MagicMock()
    # TypedDicts behave as plain dicts at runtime, so returning dict subclasses is fine.
    fake_module.StreamableHttpConnection = dict
    fake_module.SSEConnection = dict
    fake_module.StdioConnection = dict
    return patch.dict(
        "sys.modules",
        {
            "langchain_mcp_adapters": fake_module,
            "langchain_mcp_adapters.client": fake_module,
        },
    )


def test_server_to_connection_http_with_headers() -> None:
    server = MCPServerConfig(
        name="s", transport="http", url="http://x.com/mcp", headers={"Auth": "tok"}
    )
    with _patch_mcp_types():
        result = MCPManager._server_to_connection(server)
    assert result["transport"] == _STREAMABLE_HTTP
    assert result["url"] == "http://x.com/mcp"
    assert result["headers"] == {"Auth": "tok"}


def test_server_to_connection_http_no_headers() -> None:
    server = MCPServerConfig(name="s", transport="http", url="http://x.com/mcp")
    with _patch_mcp_types():
        result = MCPManager._server_to_connection(server)
    assert result["transport"] == _STREAMABLE_HTTP
    assert result["url"] == "http://x.com/mcp"
    assert "headers" not in result


def test_server_to_connection_stdio_full() -> None:
    server = MCPServerConfig(
        name="s",
        transport="stdio",
        command="python",
        args=["./srv.py"],
        env={"FOO": "bar"},
        cwd="/tmp",
    )
    with _patch_mcp_types():
        result = MCPManager._server_to_connection(server)
    assert result == {
        "transport": "stdio",
        "command": "python",
        "args": ["./srv.py"],
        "env": {"FOO": "bar"},
        "cwd": "/tmp",
    }


def test_server_to_connection_stdio_minimal() -> None:
    server = MCPServerConfig(name="s", transport="stdio", command="node")
    with _patch_mcp_types():
        result = MCPManager._server_to_connection(server)
    assert result["transport"] == "stdio"
    assert result["command"] == "node"
    assert result["args"] == []
    assert "env" not in result
    assert "cwd" not in result


# --- idempotent connect ---


@pytest.mark.asyncio
async def test_connect_is_idempotent() -> None:
    """Calling connect() twice must not accumulate tools or re-enter the client."""
    tool = _fake_tool("t")
    server = _http_server(tool_prefix="")
    cfg = _workspace_mcp(servers=[server])
    manager = MCPManager(cfg, "ws")

    mock_client = MagicMock()
    mock_client.get_tools = AsyncMock(return_value=[tool])

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client) as MockClient:
        await manager.connect()
        await manager.connect()  # second call must be a no-op
        MockClient.assert_called_once()

    assert len(manager.get_tools()) == 1
