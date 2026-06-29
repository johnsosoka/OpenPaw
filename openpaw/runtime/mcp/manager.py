"""MCPManager — wraps MultiServerMCPClient with namespacing, filtering, and required-flag handling."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from openpaw.core.config.models.mcp import MCPServerConfig, WorkspaceMCPConfig

if TYPE_CHECKING:
    from langchain_mcp_adapters.client import (
        SSEConnection,
        StdioConnection,
        StreamableHttpConnection,
    )

logger = logging.getLogger(__name__)

_MCP_INSTALL_HINT = (
    "MCP support requires the 'mcp' extra. Install with: pip install openpaw-ai[mcp]"
)


class MCPManager:
    """Per-workspace MCP runtime.

    Lifecycle:
        __init__:   stores config only, no I/O
        connect():  async — builds MultiServerMCPClient, fetches tools per server,
                    applies prefix + allow/deny filters. Non-required server failures
                    are logged and skipped; required failures raise.
        get_tools(): list[BaseTool] gathered across all successful servers.
        close():    async — no-op (0.3.x opens a fresh session per get_tools call;
                    there is no persistent connection to close).
    """

    def __init__(self, config: WorkspaceMCPConfig, workspace_name: str) -> None:
        self._config = config
        self._workspace_name = workspace_name
        self._client: Any | None = None
        self._tools: list[Any] = []
        self._connected = False

    @property
    def enabled(self) -> bool:
        return self._config.enabled and any(s.enabled for s in self._config.servers)

    async def connect(self) -> None:
        if self._connected:
            logger.debug(f"[{self._workspace_name}] MCP already connected; skipping.")
            return
        if not self.enabled:
            logger.debug(f"[{self._workspace_name}] MCP disabled or no enabled servers.")
            return

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError as exc:
            raise RuntimeError(_MCP_INSTALL_HINT) from exc

        active_servers = [s for s in self._config.servers if s.enabled]
        # Typed as Any to satisfy mypy dict-invariance; values are always one of
        # StdioConnection | SSEConnection | StreamableHttpConnection.
        client_config: dict[str, Any] = {}
        for server in active_servers:
            client_config[server.name] = self._server_to_connection(server)

        # In 0.3.x, MultiServerMCPClient does not maintain persistent connections.
        # Each get_tools() call opens a fresh MCP session, so no __aenter__ is needed.
        self._client = MultiServerMCPClient(client_config)

        all_tools: list[Any] = []
        for server in active_servers:
            try:
                # get_tools(server_name=...) is supported in 0.3.x (verified).
                server_tools = await self._client.get_tools(server_name=server.name)
            except Exception as exc:
                if server.required:
                    raise RuntimeError(
                        f"MCP server '{server.name}' is required but failed to connect: {exc}"
                    ) from exc
                logger.warning(
                    f"[{self._workspace_name}] MCP server '{server.name}' failed to connect "
                    f"(required=False, skipping): {exc}"
                )
                continue

            filtered = self._apply_filters_and_prefix(server, server_tools)
            logger.info(
                f"[{self._workspace_name}] MCP server '{server.name}' loaded "
                f"{len(filtered)}/{len(server_tools)} tools (transport={server.transport})."
            )
            all_tools.extend(filtered)

        self._tools = all_tools
        self._connected = True

    def get_tools(self) -> list[Any]:
        return list(self._tools)

    async def close(self) -> None:
        # 0.3.x opens fresh sessions per call; no persistent connection to close.
        self._client = None
        self._connected = False
        self._tools = []
        logger.debug(f"[{self._workspace_name}] MCP manager closed.")

    # --- helpers ---

    @staticmethod
    def _server_to_connection(
        server: MCPServerConfig,
    ) -> StdioConnection | SSEConnection | StreamableHttpConnection:
        """Translate MCPServerConfig → a typed connection object for MultiServerMCPClient.

        Only called from connect(), which has already validated that
        langchain-mcp-adapters is installed. Annotation references are
        TYPE_CHECKING-only — no runtime import needed thanks to
        `from __future__ import annotations`.

        Transport mapping:
            "http"  → StreamableHttpConnection  (transport="streamable_http"; "http" is a
                       recognised alias at runtime but the TypedDict literal is "streamable_http")
            "sse"   → SSEConnection
            "stdio" → StdioConnection
        """
        if server.transport == "http":
            # Validator guarantees url is non-None for http transport.
            conn: StreamableHttpConnection = {"transport": "streamable_http", "url": server.url}  # type: ignore[typeddict-item]
            if server.headers:
                conn["headers"] = dict(server.headers)
            return conn
        if server.transport == "sse":
            # Validator guarantees url is non-None for sse transport.
            sse_conn: SSEConnection = {"transport": "sse", "url": server.url}  # type: ignore[typeddict-item]
            if server.headers:
                sse_conn["headers"] = dict(server.headers)
            return sse_conn
        # stdio — validator guarantees command is non-None.
        stdio_conn: StdioConnection = {
            "transport": "stdio",
            "command": server.command,  # type: ignore[typeddict-item]
            "args": list(server.args),
        }
        if server.env:
            stdio_conn["env"] = dict(server.env)
        if server.cwd:
            stdio_conn["cwd"] = server.cwd
        return stdio_conn

    @staticmethod
    def _apply_filters_and_prefix(server: MCPServerConfig, tools: list[Any]) -> list[Any]:
        """Apply allowed/denied lists then prefix tool names."""
        allowed = set(server.allowed_tools)
        denied = set(server.denied_tools)
        prefix = server.resolved_tool_prefix()

        kept: list[Any] = []
        for tool in tools:
            original_name = getattr(tool, "name", None)
            if not original_name:
                continue
            if allowed and original_name not in allowed:
                continue
            if original_name in denied:
                continue
            if prefix:
                # Use model_copy (Pydantic v2) to avoid mutating the shared tool
                # object — double-prefixing would occur if close()/connect() is called again.
                kept.append(tool.model_copy(update={"name": f"{prefix}{original_name}"}))
            else:
                kept.append(tool)
        return kept
