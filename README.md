<div align="center">
  <img src="https://raw.githubusercontent.com/johnsosoka/OpenPaw/main/docs/assets/images/logo.png" alt="OpenPaw" width="400">
  <p><strong>A Friendly <a href="https://langchain-ai.github.io/langgraph/">LangChain/LangGraph</a> Multi-Agent Runner</strong></p>
  <p>
    <a href="https://github.com/johnsosoka/OpenPaw/actions/workflows/ci.yml"><img src="https://github.com/johnsosoka/OpenPaw/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
    <a href="https://github.com/johnsosoka/OpenPaw/actions/workflows/docs.yml"><img src="https://github.com/johnsosoka/OpenPaw/actions/workflows/docs.yml/badge.svg?branch=main" alt="Docs"></a>
    <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
    <img src="https://img.shields.io/badge/license-PolyForm%20Noncommercial-green" alt="License">
  </p>
</div>

---

> **Alpha Software** -- OpenPaw is in active development and should be considered an alpha release. APIs, configuration formats, and behavior may change between versions. Contributions and feedback are welcome, but expect rough edges.

OpenPaw gives each agent its own workspace -- personality files, custom tools, scheduled tasks -- then gets out of the way. It handles the orchestration so you can focus on what your agents actually do.

Agents can ingest documents, browse the web, search the internet, delegate to specialist sub-agents, and manage their own files -- making them well-suited for research, information processing, and long-running autonomous workflows. Give them a schedule and they'll check in on their own.

> **[Read the full documentation](https://johnsosoka.github.io/OpenPaw/)**

## Highlights

### Composable sub-agent teams

Every primary agent is a team lead. Drop a YAML into `agent/team/` and your agent gains a teammate it can dispatch with `spawn_agent(profile="researcher")`:

```yaml
name: researcher
description: "Web research specialist — searches, cross-references, and cites sources."
system_prompt: |
  You are a focused research specialist. Search, cross-reference, and
  summarize findings with source citations.
model: anthropic:claude-sonnet-4-20250514
allowed_tools: [brave_search, read_file, write_file]
timeout_minutes: 10
max_turns: 20
```

Each teammate gets its own model, tool loadout, skill set, and lifecycle budget. Run several in parallel -- the parent dispatches, they work, results route back when they finish.

### Live in-place status updates

Both your primary agent **and every sub-agent** maintain a single status message that edits in place as work progresses. No chat flood, no scroll-back -- just a live, current view of who's doing what right now. Get actionable insight into your agent teams at a glance. Agents can also call `report_progress` to announce structured milestones with their own emoji.

```
🚀 Starting work...
🔎 Running tool: brave_search (langgraph release notes)...
🤖 Dispatched sub-agent: researcher

🤖 Sub-agent: researcher
🔎 Running tool: brave_search (recent papers)...
📝 Running tool: write_file (notes.md)...
✅ Completed
```

<!-- TODO: replace this block with a demo GIF -->

### Mid-run responsiveness

Send a follow-up while the agent is mid-task and it sees it. Steer the run ("🔄 Redirecting..."), interrupt completely ("🛑 Stopping..."), or let messages batch quietly ("📨 New messages received..."). One-line emoji notifications keep you in the loop without breaking the agent's flow.

Typing indicators run while the agent is processing; emoji reactions on your original message track success (👍) or failure (👎).

### Channels

**Telegram + Discord, simultaneously** -- One workspace, multiple channels. Trigger-based activation (mentions, keywords, or both) lets agents respond appropriately in group chats. On-demand channel history gives them awareness of recent conversation when triggered.

### Workspace identity

Each agent gets its own SOUL (personality), AGENT (capabilities), USER (context), and HEARTBEAT (agent-writable scratchpad) files, plus a sandboxed filesystem. `config/` and `data/` are write-protected from the agent itself; everything else lives under `workspace/`.

**Skills** -- Reusable knowledge blocks (`SKILL.md`) drop into the workspace and can be selectively granted to specific team members.

### Tools that do real work

- **Document processing** -- Docling OCR/ICR turns scanned PDFs, DOCX, and PPTX into markdown automatically. Whisper transcribes voice messages on arrival.
- **Browser automation** -- Playwright-driven web interaction via the accessibility tree. Agents reference elements by number, not CSS selectors.
- **Email integration** -- Send and receive via Gmail with safe-by-default recipient policies. Search, reply with threading, manage attachments.
- **MCP servers** -- Connect any MCP-compatible service (local stdio or remote Streamable HTTP) per workspace. Tools flow into the agent alongside builtins.
- **Deep research** -- Connect to a self-hosted GPT-Researcher instance for multi-source reports with citations.
- **Web search** -- Brave Search and other providers for direct search-and-summarize.
- **Drop-in custom tools** -- Write a `@tool` function, save it to `agent/tools/`, restart. Auto-discovered, no wiring needed.

### Scheduling & autonomy

- **Cron and heartbeats** -- Recurring jobs from YAML, plus proactive check-ins agents can configure themselves.
- **Dynamic scheduling** -- `schedule_at`, `schedule_every`, `request_followup`. Your agent can plan its own future.
- **Auto-compact** -- When the context window fills, the framework summarizes old turns and continues without missing a beat.
- **Runtime model switching** -- `/model anthropic:claude-opus-4-20250514` mid-conversation. No restart.

### Safe by default

- **Approval gates** -- Human-in-the-loop authorization for sensitive operations with configurable timeouts and channel-native UI.
- **Recipient policies** -- Email defaults to deny-all sends; only addresses on your allowlist go through.
- **Sandboxed filesystem** -- Custom tools write to `workspace/` by default; `config/` and `data/` are read-only to agents.

### Multi-provider LLMs

Anthropic, OpenAI, AWS Bedrock, xAI, Fireworks, and any OpenAI-compatible endpoint. Define providers once in global config and reference by name from any workspace.

## Quick Start

> **Fastest first run:** scaffold with `--channel stdio` to chat with your agent right in the terminal — no Telegram or Discord token required (you still need one LLM provider API key). Swap in `--channel telegram` or `--channel discord` when you're ready to go live.

### Install from PyPI

The quickest path — no clone required:

```bash
pip install openpaw-ai
openpaw init my_agent --model anthropic:claude-sonnet-4-20250514 --channel stdio
openpaw -c config.yaml -w my_agent
```

`openpaw init` scaffolds the workspace **and** a starter `config.yaml`, so `run` works right away. Add your LLM provider key to `agent_workspaces/my_agent/config/.env` (e.g. `ANTHROPIC_API_KEY=...`) before running.

Optional capabilities install as extras: `pip install 'openpaw-ai[documents]'` (Docling OCR/PDF), plus `[voice]`, `[web]`, `[memory]`, `[email]`, `[mcp]`, or `[all-builtins]`.

### Install from source (Poetry)

The steps below use the from-source workflow; prefix commands with `poetry run`.

#### 1. Install

```bash
git clone https://github.com/johnsosoka/OpenPaw.git
cd OpenPaw
poetry install
```

#### 2. Scaffold a workspace

```bash
poetry run openpaw init my_agent \
  --model anthropic:claude-sonnet-4-20250514 \
  --channel telegram
```

This also writes a starter `config.yaml` in the current directory (it won't overwrite an existing one). To start from the fully-commented reference instead, copy it first: `cp config.example.yaml config.yaml`.

#### 3. Configure

Add your API keys to `agent_workspaces/my_agent/config/.env`:

```bash
ANTHROPIC_API_KEY=your-key-here
TELEGRAM_BOT_TOKEN=your-token-here
```

#### 4. Run

```bash
poetry run openpaw -c config.yaml -w my_agent
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `openpaw init <name>` | Scaffold a new agent workspace |
| `openpaw init <name> --model <provider:model>` | Scaffold with a pre-configured model |
| `openpaw init <name> --channel stdio` | Scaffold with the local terminal channel (no channel token needed) |
| `openpaw init <name> --channel telegram` | Scaffold with channel pre-configured (`stdio`, `telegram`, or `discord`) |
| `openpaw list` | List available workspaces |
| `openpaw -c config.yaml -w <name>` | Run a single workspace |
| `openpaw -c config.yaml -w name1,name2` | Run multiple workspaces |
| `openpaw -c config.yaml --all` | Run all discovered workspaces |
| `openpaw -c config.yaml -w <name> -v` | Run with verbose logging |

All commands should be prefixed with `poetry run` when running from the project directory.

## Agent Workspace Structure

Each workspace lives under `agent_workspaces/<name>/` and is organized into five directories:

```
agent_workspaces/my_agent/
├── agent/              # Identity and extensions
│   ├── AGENT.md        # Capabilities and behavior guidelines
│   ├── USER.md         # User context and preferences
│   ├── SOUL.md         # Core personality and values
│   ├── HEARTBEAT.md    # Session state scratchpad (agent-writable)
│   ├── tools/          # Custom LangChain @tool functions
│   ├── team/           # Sub-agent profiles (YAML)
│   └── skills/         # Skill directories
├── config/             # Configuration (write-protected)
│   ├── agent.yaml      # Per-workspace settings (model, channel, queue)
│   ├── .env            # API keys and secrets
│   └── crons/          # Scheduled task definitions
├── data/               # Framework-managed state (write-protected)
│   ├── TASKS.yaml      # Persistent task tracking
│   ├── uploads/        # User-uploaded files
│   └── ...             # Conversations DB, session state, token logs
├── memory/             # Archived conversations and session logs
│   ├── conversations/  # Conversation exports (markdown + JSON)
│   └── logs/           # Session logs and channel history
│       ├── channel/    # Persistent channel message logs (JSONL)
│       └── sessions/   # Heartbeat, cron, and sub-agent session logs
└── workspace/          # Agent work area (default write target)
    ├── downloads/      # Browser-downloaded files
    └── screenshots/    # Browser screenshots
```

The `openpaw init` command scaffolds this structure with starter templates. Customize the identity files in `agent/` to shape your agent's personality and purpose. Configure model, channel, and queue behavior in `config/agent.yaml`.

The `data/` and `config/` directories are write-protected from agent filesystem tools. Write operations default to the `workspace/` directory unless an explicit path is provided.

## In-Chat Commands

Once running, agents respond to framework commands in chat:

| Command | Description |
|---------|-------------|
| `/help` | List available commands |
| `/status` | Show model, context usage, tasks, and token usage |
| `/new` | Archive conversation and start fresh |
| `/compact` | Summarize, archive, and continue with summary |
| `/model <provider:model>` | Switch LLM model at runtime |

## Documentation

- [Getting Started](docs/getting-started.md) -- Installation, first workspace, and troubleshooting
- [Concepts](docs/concepts.md) -- How workspaces, scheduling, queues, and tools fit together
- [Configuration](docs/configuration.md) -- Global and per-workspace configuration reference
- [Workspaces](docs/workspaces.md) -- Workspace structure, identity files, and custom tools
- [Scheduling](docs/scheduling.md) -- Cron jobs, heartbeats, and dynamic scheduling
- [Built-ins](docs/builtins.md) -- Web search, browser automation, email, voice, sub-agents, and more
- [MCP Servers](docs/mcp.md) -- Per-workspace MCP server connections (HTTP and stdio)
- [Channels](docs/channels.md) -- Channel adapters and access control
- [Queue System](docs/queue-system.md) -- Queue modes and message handling
- [Architecture](docs/architecture.md) -- System design, data flows, and architectural decisions

## Contributing

Development follows a GitFlow branching model:

- **`main`** -- Stable releases only. Protected branch, requires CI to pass.
- **`develop`** -- Integration branch. Feature and bugfix PRs target `develop`.
- **Feature branches** -- Branch from `develop` as `feature/`, `bugfix/`, `docs/`, or `chore/`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development guide.

## Prerequisites

- Python 3.11+
- [Poetry 2.0+](https://python-poetry.org/docs/#installation)
- At least one channel bot token: [Telegram](https://core.telegram.org/bots#botfather) or [Discord](https://discord.com/developers/applications)
- At least one model provider API key (Anthropic, OpenAI, or AWS credentials for Bedrock)

## License

[PolyForm Noncommercial 1.0.0](LICENSE)
