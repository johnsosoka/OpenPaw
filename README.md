# OpenPaw

Multi-channel AI agent framework built on [LangGraph](https://langchain-ai.github.io/langgraph/).

## Features

- **Isolated workspaces** -- Each agent runs with its own personality, channel, tools, and conversation history
- **Multi-provider LLM support** -- Anthropic, OpenAI, AWS Bedrock, xAI, and any OpenAI-compatible API
- **Telegram integration** -- Communicate with agents via Telegram bots with allowlist-based access control
- **Scheduled tasks and heartbeats** -- Cron-based scheduling and proactive agent check-ins
- **Sandboxed filesystem** -- Agents read and write files within their workspace with path traversal protection
- **Sub-agent spawning** -- Background workers for concurrent task execution with lifecycle management
- **Browser automation** -- Playwright-based web interaction using accessibility tree navigation

## Quick Start

### 1. Install

```bash
git clone https://github.com/johnsosoka/openpaw.git
cd openpaw
poetry install
```

### 2. Scaffold a workspace

```bash
poetry run openpaw init my_agent \
  --model anthropic:claude-sonnet-4-20250514 \
  --channel telegram
```

### 3. Configure

```bash
cp config.example.yaml config.yaml
```

Add your API keys to `agent_workspaces/my_agent/.env`:

```bash
ANTHROPIC_API_KEY=your-key-here
TELEGRAM_BOT_TOKEN=your-token-here
```

### 4. Run

```bash
poetry run openpaw -c config.yaml -w my_agent
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `openpaw init <name>` | Scaffold a new agent workspace |
| `openpaw init <name> --model <provider:model>` | Scaffold with a pre-configured model |
| `openpaw init <name> --channel telegram` | Scaffold with Telegram channel pre-configured |
| `openpaw list` | List available workspaces |
| `openpaw -c config.yaml -w <name>` | Run a single workspace |
| `openpaw -c config.yaml -w name1,name2` | Run multiple workspaces |
| `openpaw -c config.yaml --all` | Run all discovered workspaces |
| `openpaw -c config.yaml -w <name> -v` | Run with verbose logging |

All commands should be prefixed with `poetry run` when running from the project directory.

## Workspace Structure

Each workspace lives under `agent_workspaces/<name>/` and requires four markdown files that define the agent's identity:

```
agent_workspaces/my_agent/
├── AGENT.md          # Capabilities and behavior guidelines
├── USER.md           # User context and preferences
├── SOUL.md           # Core personality and values
├── HEARTBEAT.md      # Session state scratchpad (can start empty)
├── agent.yaml        # Per-workspace configuration (optional)
├── .env              # API keys and secrets (optional)
├── tools/            # Custom LangChain @tool functions (optional)
└── crons/            # Scheduled task definitions (optional)
```

The `openpaw init` command generates all required files with starter templates. Customize the markdown files to shape your agent's personality and purpose. Configure model, channel, and queue behavior in `agent.yaml`.

## In-Chat Commands

Once running, agents respond to framework commands in Telegram:

| Command | Description |
|---------|-------------|
| `/help` | List available commands |
| `/status` | Show model, context usage, tasks, and token usage |
| `/new` | Archive conversation and start fresh |
| `/compact` | Summarize, archive, and continue with summary |
| `/model <provider:model>` | Switch LLM model at runtime |

## Documentation

- [Getting Started](docs/getting-started.md) -- Installation, first workspace, and troubleshooting
- [Configuration](docs/configuration.md) -- Global and per-workspace configuration reference
- [Workspaces](docs/workspaces.md) -- Workspace structure, custom tools, and cron jobs
- [Architecture](docs/architecture.md) -- System design and component interactions
- [Channels](docs/channels.md) -- Channel system and access control
- [Queue System](docs/queue-system.md) -- Queue modes and message handling
- [Cron Scheduler](docs/cron-scheduler.md) -- Scheduled tasks and heartbeat system
- [Built-ins](docs/builtins.md) -- Web search, browser automation, voice, sub-agents, and more

## Prerequisites

- Python 3.11+
- [Poetry 2.0+](https://python-poetry.org/docs/#installation)
- A Telegram bot token ([via BotFather](https://core.telegram.org/bots#botfather))
- At least one model provider API key (Anthropic, OpenAI, or AWS credentials for Bedrock)

## License

[PolyForm Noncommercial 1.0.0](LICENSE)
