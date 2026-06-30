# MCP Servers

[Model Context Protocol](https://modelcontextprotocol.io) (MCP) is an open standard for exposing tools to LLMs. OpenPaw supports per-workspace MCP server connections via the `mcp:` config block. Each server connects independently and exposes its tools to the agent alongside builtins and workspace tools.

## Installation

MCP support requires an optional extra:

```bash
pip install 'openpaw-ai[mcp]'
# or, if using Poetry:
poetry install -E mcp
```

If MCP is enabled in config but the extra is missing, OpenPaw raises at workspace start:

```
RuntimeError: MCP support requires the 'mcp' extra. Install with: pip install openpaw-ai[mcp]
```

## Quick Start

Add an `mcp:` block to your workspace `agent.yaml`:

```yaml
mcp:
  enabled: true
  servers:
    # Streamable HTTP (preferred transport):
    - name: weather
      transport: http
      url: https://mcp.example.com/weather
      headers:
        Authorization: "Bearer ${MCP_WEATHER_TOKEN}"

    # Local subprocess (stdio):
    - name: math
      transport: stdio
      command: python
      args: ["./mcp_servers/math.py"]
      env:
        PYTHONUNBUFFERED: "1"
```

MCP is per-workspace only — there is no global `mcp:` block in `config.yaml`.

## Field Reference

### `WorkspaceMCPConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `false` | Master toggle. Set to `true` to activate MCP for this workspace. |
| `servers` | `list[MCPServerConfig]` | `[]` | List of server bindings. Each connects independently. |

### `MCPServerConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | required | Unique server name within the workspace. Used for the default tool prefix and log messages. |
| `transport` | `"http" \| "sse" \| "stdio"` | required | Transport type. `http` = Streamable HTTP (preferred); `sse` = legacy SSE; `stdio` = local subprocess. |
| `enabled` | `bool` | `true` | Per-server toggle. Set to `false` to skip a server without removing it. |
| `required` | `bool` | `false` | If `true`, a connection failure aborts workspace start. If `false`, logs a warning and skips the server. |
| `url` | `str \| None` | `None` | Endpoint URL. Required for `http` and `sse` transports. |
| `headers` | `dict[str, str]` | `{}` | Request headers for `http`/`sse`. Supports `${VAR}` env var expansion. |
| `command` | `str \| None` | `None` | Executable to launch. Required for `stdio` transport. |
| `args` | `list[str]` | `[]` | Arguments for the stdio command. |
| `env` | `dict[str, str]` | `{}` | Environment variables for the stdio subprocess. Supports `${VAR}` expansion. |
| `cwd` | `str \| None` | `None` | Working directory for the stdio subprocess. |
| `tool_prefix` | `str \| None` | `None` | Prefix applied to tool names from this server. `None` = default `"{name}_"`. Set to `""` to disable prefixing. |
| `allowed_tools` | `list[str]` | `[]` | If non-empty, only these tool names (pre-prefix) are exposed from this server. |
| `denied_tools` | `list[str]` | `[]` | Tool names (pre-prefix) to exclude. Applied after `allowed_tools`. |

Transport-specific validation is enforced at config load time: `url` is required for `http`/`sse`; `command` is required for `stdio`; mixing fields across transports (e.g., `command` on an `http` server) raises a `ValidationError`.

## Tool Naming and Prefixing

MCP tool names can collide across servers and with existing builtins. OpenPaw applies a prefix at load time to avoid conflicts.

**Default behavior:** prefix is `{server.name}_`. A tool named `get_forecast` from a server named `weather` becomes `weather_get_forecast`.

**Custom prefix:**
```yaml
- name: weather
  transport: http
  url: https://mcp.example.com/weather
  tool_prefix: "wx_"   # → wx_get_forecast
```

**Disable prefixing:**
```yaml
- name: math
  transport: stdio
  command: python
  args: ["./math_server.py"]
  tool_prefix: ""   # tool names unchanged
```

Only disable prefixing when you are certain names will not collide with other tools in the workspace.

## Failure Handling

Each server has a `required` field that controls behavior when a connection fails at workspace startup:

- **`required: false`** (default) — logs a warning and skips that server's tools. The workspace starts normally with whatever servers succeeded.
- **`required: true`** — raises a `RuntimeError` and aborts workspace start. Use this for servers the agent cannot function without.

## Tool Filtering

Two optional lists control which tools are exposed from each server. Both operate on the original tool name (before the prefix is applied).

1. **`allowed_tools`** — if non-empty, only tools in this list are exposed. Anything not listed is dropped.
2. **`denied_tools`** — tools in this list are excluded. Applied after `allowed_tools`.

```yaml
- name: weather
  transport: http
  url: https://mcp.example.com/weather
  allowed_tools:
    - get_forecast
    - get_current
  denied_tools:
    - get_historical   # redundant here but shows ordering
```

## Availability

MCP tools are exposed to the interactive agent **and** to stateless scheduled runs — cron jobs, heartbeats, and profiled sub-agent spawns all receive the workspace's MCP tools alongside builtins and workspace tools. A cron job authored to call an MCP tool when it fires will have that tool available.

## Middleware Integration

MCP tools flow through the existing middleware pipeline unchanged — approval gates and tool timeouts apply to MCP tools exactly as they do to builtins and workspace tools.

## Troubleshooting

**"MCP support requires the 'mcp' extra"**

Install the extra: `pip install 'openpaw-ai[mcp]'`

**Headers with secrets**

Use `${VAR}` syntax in `headers` — the workspace loader expands environment variables before the connection is opened:

```yaml
headers:
  Authorization: "Bearer ${MY_SERVICE_TOKEN}"
```

**Port conflicts with stdio servers**

Some stdio MCP servers (e.g., those built with FastMCP) bind a local port for the MCP transport. If multiple workspaces load the same server, use different ports per server by passing a port argument in `args`:

```yaml
args: ["./server.py", "--port", "9001"]
```

**Server not loading tools**

Run with verbose logging (`-v`) and look for the `MCP server '...' loaded N/M tools` INFO log. If N is 0, check `allowed_tools` and `denied_tools`. If the server failed to connect and `required: false`, look for the WARNING line instead.
