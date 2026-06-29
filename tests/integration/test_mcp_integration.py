"""Integration tests for MCPManager against a real MCP server subprocess.

The same FastMCP fixture (tests/fixtures/mcp/echo_server.py) is used for
both transports — stdio (subprocess) and streamable-http (background server
on an ephemeral port).

Running a subset:
    poetry run pytest tests/integration/test_mcp_integration.py -v

Marker:
    All tests are tagged @pytest.mark.integration so they can be excluded
    with: pytest -m "not integration"
"""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Generator

import httpx
import pytest

from openpaw.core.config.models.mcp import MCPServerConfig, WorkspaceMCPConfig
from openpaw.runtime.mcp.manager import MCPManager


# ---------------------------------------------------------------------------
# MCP tool result helpers
# ---------------------------------------------------------------------------


def _text_from_result(result: object) -> str:
    """Extract the text value from an MCP tool invocation result.

    langchain-mcp-adapters returns tool results as a list of content blocks:
        [{'type': 'text', 'text': '...', 'id': '...'}]

    This helper normalises that to a plain string so tests stay readable.
    """
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict) and first.get("type") == "text":
            return str(first["text"])
    return str(result)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "mcp"
_ECHO_SERVER = _FIXTURE_DIR / "echo_server.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Allocate an ephemeral port that is currently free on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_http(url: str, *, timeout_seconds: float = 10.0) -> None:
    """Poll *url* until it responds (any status) or timeout_seconds elapse.

    A 406 is acceptable — it means the server is alive but the request
    lacks MCP-required headers; that is exactly what we send here.
    Raises RuntimeError if the server never becomes reachable.
    """
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            httpx.get(url, timeout=1.0)
            return  # Any response (including 4xx) means the server is up.
        except httpx.ConnectError as exc:
            last_error = exc
            time.sleep(0.1)
        except httpx.HTTPStatusError:
            return  # Status error = server is alive.
    raise RuntimeError(
        f"Server at {url} did not become reachable within {timeout_seconds}s. "
        f"Last error: {last_error}"
    )


def _stdio_server_config(
    name: str = "echo",
    *,
    tool_prefix: str | None = None,
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
) -> MCPServerConfig:
    """Build an MCPServerConfig for the stdio echo server."""
    return MCPServerConfig(
        name=name,
        transport="stdio",
        command=sys.executable,
        args=[str(_ECHO_SERVER)],
        tool_prefix=tool_prefix,
        allowed_tools=allowed_tools or [],
        denied_tools=denied_tools or [],
    )


def _http_server_config(
    port: int,
    name: str = "echo",
    *,
    tool_prefix: str | None = None,
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> MCPServerConfig:
    """Build an MCPServerConfig for the streamable-http echo server."""
    return MCPServerConfig(
        name=name,
        transport="http",
        url=f"http://127.0.0.1:{port}/mcp",
        tool_prefix=tool_prefix,
        allowed_tools=allowed_tools or [],
        denied_tools=denied_tools or [],
        headers=headers or {},
    )


# ---------------------------------------------------------------------------
# Module-scoped HTTP server fixture
# (started once per file, shared across all http tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def http_server_port() -> Generator[int, None, None]:
    """Start the echo server in streamable-http mode on a free port.

    Yields the port number.  The process is unconditionally killed in teardown
    so it never becomes an orphan even if a test raises.
    """
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(_ECHO_SERVER),
            "--transport",
            "streamable-http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_http(f"http://127.0.0.1:{port}/mcp", timeout_seconds=15.0)
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# ===========================================================================
# stdio tests
# ===========================================================================


@pytest.mark.integration
async def test_stdio_loads_three_tools_with_default_prefix() -> None:
    """stdio connect returns exactly 3 tools, all prefixed with the server name."""
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[_stdio_server_config(name="echo")],
    )
    manager = MCPManager(config, "test_ws")
    await manager.connect()

    tools = manager.get_tools()
    names = {t.name for t in tools}

    assert len(tools) == 3
    assert names == {"echo_echo", "echo_add", "echo_whoami"}

    await manager.close()


@pytest.mark.integration
async def test_stdio_invoke_echo_returns_input() -> None:
    """Invoking echo_echo via stdio returns the original message."""
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[_stdio_server_config(name="echo")],
    )
    manager = MCPManager(config, "test_ws")
    await manager.connect()

    tools = {t.name: t for t in manager.get_tools()}
    result = await tools["echo_echo"].ainvoke({"message": "hello"})

    assert _text_from_result(result) == "hello"

    await manager.close()


@pytest.mark.integration
async def test_stdio_invoke_add_returns_sum() -> None:
    """Invoking echo_add via stdio returns a + b."""
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[_stdio_server_config(name="echo")],
    )
    manager = MCPManager(config, "test_ws")
    await manager.connect()

    tools = {t.name: t for t in manager.get_tools()}
    result = await tools["echo_add"].ainvoke({"a": 2, "b": 3})

    assert _text_from_result(result) == "5"

    await manager.close()


@pytest.mark.integration
async def test_stdio_allowed_tools_restricts_to_one_tool() -> None:
    """allowed_tools=["echo"] exposes only echo_echo."""
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[_stdio_server_config(name="echo", allowed_tools=["echo"])],
    )
    manager = MCPManager(config, "test_ws")
    await manager.connect()

    tools = manager.get_tools()
    names = {t.name for t in tools}

    assert names == {"echo_echo"}

    await manager.close()


@pytest.mark.integration
async def test_stdio_denied_tools_excludes_whoami() -> None:
    """denied_tools=["whoami"] strips echo_whoami; other two remain."""
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[_stdio_server_config(name="echo", denied_tools=["whoami"])],
    )
    manager = MCPManager(config, "test_ws")
    await manager.connect()

    tools = manager.get_tools()
    names = {t.name for t in tools}

    assert "echo_whoami" not in names
    assert {"echo_echo", "echo_add"} == names

    await manager.close()


@pytest.mark.integration
async def test_stdio_empty_prefix_leaves_names_unprefixed() -> None:
    """tool_prefix="" returns raw tool names from the server."""
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[_stdio_server_config(name="echo", tool_prefix="")],
    )
    manager = MCPManager(config, "test_ws")
    await manager.connect()

    tools = manager.get_tools()
    names = {t.name for t in tools}

    assert names == {"echo", "add", "whoami"}

    await manager.close()


# ===========================================================================
# streamable-http tests
# ===========================================================================


@pytest.mark.integration
async def test_http_loads_three_tools(http_server_port: int) -> None:
    """streamable-http connect returns exactly 3 tools with default prefix."""
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[_http_server_config(http_server_port, name="echo")],
    )
    manager = MCPManager(config, "test_ws")
    await manager.connect()

    tools = manager.get_tools()
    names = {t.name for t in tools}

    assert len(tools) == 3
    assert names == {"echo_echo", "echo_add", "echo_whoami"}

    await manager.close()


@pytest.mark.integration
async def test_http_invoke_echo_returns_input(http_server_port: int) -> None:
    """Invoking echo_echo via http returns the original message."""
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[_http_server_config(http_server_port, name="echo")],
    )
    manager = MCPManager(config, "test_ws")
    await manager.connect()

    tools = {t.name: t for t in manager.get_tools()}
    result = await tools["echo_echo"].ainvoke({"message": "hello"})

    assert _text_from_result(result) == "hello"

    await manager.close()


@pytest.mark.integration
async def test_http_invoke_add_returns_sum(http_server_port: int) -> None:
    """Invoking echo_add via http returns a + b."""
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[_http_server_config(http_server_port, name="echo")],
    )
    manager = MCPManager(config, "test_ws")
    await manager.connect()

    tools = {t.name: t for t in manager.get_tools()}
    result = await tools["echo_add"].ainvoke({"a": 7, "b": 8})

    assert _text_from_result(result) == "15"

    await manager.close()


@pytest.mark.integration
async def test_http_custom_header_is_accepted_without_error(http_server_port: int) -> None:
    """Passing a custom header in config does not cause a connection error.

    The echo server does not validate headers; this test confirms MCPManager
    propagates the header without raising.
    """
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[
            _http_server_config(
                http_server_port,
                name="echo",
                headers={"X-Custom-Token": "test-value-abc"},
            )
        ],
    )
    manager = MCPManager(config, "test_ws")
    await manager.connect()

    tools = manager.get_tools()
    assert len(tools) == 3  # All tools loaded despite custom header being present

    await manager.close()


# ===========================================================================
# Multi-server scenario
# ===========================================================================


@pytest.mark.integration
async def test_multi_server_returns_six_tools(http_server_port: int) -> None:
    """A workspace with stdio + http servers exposes 6 tools (3 per server)."""
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[
            _stdio_server_config(name="echo_local"),
            _http_server_config(http_server_port, name="echo_remote"),
        ],
    )
    manager = MCPManager(config, "test_ws")
    await manager.connect()

    tools = manager.get_tools()
    names = {t.name for t in tools}

    assert len(tools) == 6
    # Each server contributes 3 tools under its own prefix.
    assert {"echo_local_echo", "echo_local_add", "echo_local_whoami"}.issubset(names)
    assert {"echo_remote_echo", "echo_remote_add", "echo_remote_whoami"}.issubset(names)

    await manager.close()


@pytest.mark.integration
async def test_unreachable_non_required_server_does_not_block_others(
    http_server_port: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unreachable required=False server is skipped; the healthy servers still load.

    Three servers are configured:
      1. echo_local  — stdio, healthy
      2. echo_remote — http, healthy
      3. echo_broken — http, unreachable port, required=False

    Expected outcome: 6 tools (3 + 3) loaded, warning logged for echo_broken.
    """
    dead_port = _free_port()  # Grab a port; nothing listens on it.

    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[
            _stdio_server_config(name="echo_local"),
            _http_server_config(http_server_port, name="echo_remote"),
            MCPServerConfig(
                name="echo_broken",
                transport="http",
                url=f"http://127.0.0.1:{dead_port}/mcp",
                required=False,
            ),
        ],
    )
    manager = MCPManager(config, "test_ws")

    with caplog.at_level(logging.WARNING):
        await manager.connect()

    tools = manager.get_tools()
    names = {t.name for t in tools}

    assert len(tools) == 6
    assert {"echo_local_echo", "echo_local_add", "echo_local_whoami"}.issubset(names)
    assert {"echo_remote_echo", "echo_remote_add", "echo_remote_whoami"}.issubset(names)
    # No echo_broken tools (server was unreachable).
    assert not any("echo_broken" in n for n in names)
    # Warning logged for the failed server.
    assert "echo_broken" in caplog.text

    await manager.close()


# ===========================================================================
# Regression: tool name mutation guard
# ===========================================================================


@pytest.mark.integration
async def test_close_then_reconnect_does_not_double_prefix() -> None:
    """close() followed by connect() must not produce double-prefixed tool names.

    Regression for the bug where _apply_filters_and_prefix mutated tool.name in
    place on a shared adapter object, causing a second connect() call after close()
    to prefix an already-prefixed name (e.g. "echo_echo_echo").
    """
    config = WorkspaceMCPConfig(
        enabled=True,
        servers=[_stdio_server_config(name="echo")],
    )
    manager = MCPManager(config, "test_ws")

    await manager.connect()
    first_names = {t.name for t in manager.get_tools()}

    await manager.close()

    # Second connect — must produce identical names, not double-prefixed ones.
    await manager.connect()
    second_names = {t.name for t in manager.get_tools()}

    assert first_names == second_names
    assert first_names == {"echo_echo", "echo_add", "echo_whoami"}

    await manager.close()
