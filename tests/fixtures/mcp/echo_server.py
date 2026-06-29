"""Minimal FastMCP server fixture for integration testing.

Provides three deterministic tools:
  - echo(message)  — returns the input string unchanged
  - add(a, b)      — returns a + b
  - whoami()       — returns a fixed identity string

The server can run via either stdio (default) or streamable-http transport.

Usage
-----
stdio (default):
    python tests/fixtures/mcp/echo_server.py

streamable-http on a specific port:
    python tests/fixtures/mcp/echo_server.py --transport streamable-http --host 127.0.0.1 --port 9876
"""

from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP

IDENTITY = "echo-server-v1"

mcp = FastMCP("echo")


@mcp.tool()
def echo(message: str) -> str:
    """Return the input message unchanged."""
    return message


@mcp.tool()
def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


@mcp.tool()
def whoami() -> str:
    """Return a fixed identity string."""
    return IDENTITY


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenPaw MCP echo server fixture")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport to use (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for streamable-http transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for streamable-http transport (default: 8000)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.transport == "streamable-http":
        # Reconstruct with the requested host/port so settings are baked in.
        server = FastMCP(
            "echo",
            host=args.host,
            port=args.port,
            stateless_http=True,
        )

        @server.tool()
        def echo(message: str) -> str:  # noqa: F811
            """Return the input message unchanged."""
            return message

        @server.tool()
        def add(a: int, b: int) -> int:  # noqa: F811
            """Return the sum of two integers."""
            return a + b

        @server.tool()
        def whoami() -> str:  # noqa: F811
            """Return a fixed identity string."""
            return IDENTITY

        server.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
