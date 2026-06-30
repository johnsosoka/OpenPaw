"""Unit tests for MCP Pydantic config models."""

import pytest
from pydantic import ValidationError

from openpaw.core.config.models.mcp import MCPServerConfig, WorkspaceMCPConfig
from openpaw.core.config.models.workspace import WorkspaceConfig


# --- MCPServerConfig: http/sse transport ---


def test_http_server_requires_url() -> None:
    with pytest.raises(ValidationError, match="'url' is required"):
        MCPServerConfig(name="s", transport="http")


def test_sse_server_requires_url() -> None:
    with pytest.raises(ValidationError, match="'url' is required"):
        MCPServerConfig(name="s", transport="sse")


def test_http_server_rejects_command() -> None:
    with pytest.raises(ValidationError, match="stdio-only"):
        MCPServerConfig(name="s", transport="http", url="http://example.com/mcp", command="python")


def test_http_server_rejects_args() -> None:
    with pytest.raises(ValidationError, match="stdio-only"):
        MCPServerConfig(name="s", transport="http", url="http://example.com/mcp", args=["foo"])


def test_http_server_rejects_env() -> None:
    with pytest.raises(ValidationError, match="stdio-only"):
        MCPServerConfig(name="s", transport="http", url="http://example.com/mcp", env={"FOO": "bar"})


def test_http_server_rejects_cwd() -> None:
    with pytest.raises(ValidationError, match="stdio-only"):
        MCPServerConfig(name="s", transport="http", url="http://example.com/mcp", cwd="/tmp")


def test_sse_server_rejects_env() -> None:
    with pytest.raises(ValidationError, match="stdio-only"):
        MCPServerConfig(name="s", transport="sse", url="http://example.com/sse", env={"FOO": "bar"})


def test_sse_server_rejects_cwd() -> None:
    with pytest.raises(ValidationError, match="stdio-only"):
        MCPServerConfig(name="s", transport="sse", url="http://example.com/sse", cwd="/tmp")


def test_valid_http_server() -> None:
    s = MCPServerConfig(name="weather", transport="http", url="http://example.com/mcp")
    assert s.name == "weather"
    assert s.transport == "http"
    assert s.enabled is True
    assert s.required is False


def test_valid_sse_server_with_headers() -> None:
    s = MCPServerConfig(
        name="svc",
        transport="sse",
        url="http://example.com/sse",
        headers={"Authorization": "Bearer tok"},
    )
    assert s.headers == {"Authorization": "Bearer tok"}


# --- MCPServerConfig: stdio transport ---


def test_stdio_server_requires_command() -> None:
    with pytest.raises(ValidationError, match="'command' is required"):
        MCPServerConfig(name="s", transport="stdio")


def test_stdio_server_rejects_url() -> None:
    with pytest.raises(ValidationError, match="http/sse-only"):
        MCPServerConfig(name="s", transport="stdio", command="python", url="http://x.com")


def test_stdio_server_rejects_headers() -> None:
    with pytest.raises(ValidationError, match="http/sse-only"):
        MCPServerConfig(
            name="s", transport="stdio", command="python", headers={"X-Foo": "bar"}
        )


def test_valid_stdio_server() -> None:
    s = MCPServerConfig(
        name="math",
        transport="stdio",
        command="python",
        args=["./server.py"],
        env={"PYTHONUNBUFFERED": "1"},
    )
    assert s.command == "python"
    assert s.args == ["./server.py"]
    assert s.env == {"PYTHONUNBUFFERED": "1"}


def test_stdio_server_cwd() -> None:
    s = MCPServerConfig(name="s", transport="stdio", command="node", cwd="/tmp/mcp")
    assert s.cwd == "/tmp/mcp"


# --- MCPServerConfig: extra fields rejected ---


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        MCPServerConfig(name="s", transport="http", url="http://x.com", typo_field="oops")


# --- resolved_tool_prefix ---


def test_prefix_default_uses_name() -> None:
    s = MCPServerConfig(name="weather", transport="http", url="http://x.com")
    assert s.resolved_tool_prefix() == "weather_"


def test_prefix_empty_string_opts_out() -> None:
    s = MCPServerConfig(name="weather", transport="http", url="http://x.com", tool_prefix="")
    assert s.resolved_tool_prefix() == ""


def test_prefix_custom_value() -> None:
    s = MCPServerConfig(name="w", transport="http", url="http://x.com", tool_prefix="wx_")
    assert s.resolved_tool_prefix() == "wx_"


# --- WorkspaceMCPConfig ---


def test_duplicate_server_names_rejected() -> None:
    with pytest.raises(ValidationError, match="Duplicate MCP server names"):
        WorkspaceMCPConfig(
            enabled=True,
            servers=[
                {"name": "dup", "transport": "http", "url": "http://a.com"},
                {"name": "dup", "transport": "http", "url": "http://b.com"},
            ],
        )


def test_unique_server_names_accepted() -> None:
    cfg = WorkspaceMCPConfig(
        enabled=True,
        servers=[
            {"name": "a", "transport": "http", "url": "http://a.com"},
            {"name": "b", "transport": "http", "url": "http://b.com"},
        ],
    )
    assert len(cfg.servers) == 2


def test_workspace_mcp_config_defaults() -> None:
    cfg = WorkspaceMCPConfig()
    assert cfg.enabled is False
    assert cfg.servers == []


def test_workspace_mcp_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkspaceMCPConfig(enabled=False, unknown_key="oops")


# --- WorkspaceConfig YAML round-trip ---


def test_workspace_config_mcp_field_defaults() -> None:
    ws = WorkspaceConfig()
    assert ws.mcp.enabled is False
    assert ws.mcp.servers == []


def test_workspace_config_mcp_block_parsed() -> None:
    ws = WorkspaceConfig(
        mcp={
            "enabled": True,
            "servers": [
                {
                    "name": "tools",
                    "transport": "http",
                    "url": "http://localhost:8000/mcp",
                    "tool_prefix": "tools_",
                    "allowed_tools": ["search"],
                    "denied_tools": [],
                    "required": True,
                }
            ],
        }
    )
    assert ws.mcp.enabled is True
    assert len(ws.mcp.servers) == 1
    srv = ws.mcp.servers[0]
    assert srv.name == "tools"
    assert srv.transport == "http"
    assert srv.url == "http://localhost:8000/mcp"
    assert srv.tool_prefix == "tools_"
    assert srv.allowed_tools == ["search"]
    assert srv.required is True


def test_workspace_config_mcp_disabled_by_default() -> None:
    """A workspace with no mcp block behaves identically to pre-feature."""
    ws = WorkspaceConfig()
    assert ws.mcp.enabled is False
    assert ws.mcp.servers == []
