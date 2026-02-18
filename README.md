# OpenPaw

**A LangGraph-native framework for building autonomous AI personal assistants.**

OpenPaw gives your AI agents real agency -- they can spawn sub-agents, browse the web, schedule their own follow-ups, process documents, manage persistent tasks, and ask for human approval before taking dangerous actions. Built on [LangGraph](https://langchain-ai.github.io/langgraph/) and [LangChain](https://www.langchain.com/), it plays natively with the `@tool` ecosystem you already know.

Each agent runs in an isolated workspace with its own personality, communication channel, scheduled tasks, filesystem, and tool loadout. Run one assistant or a dozen -- they stay completely independent.

## What Makes OpenPaw Different

- **Agents that act, not just respond.** Sub-agent spawning, self-scheduling, self-continuation, and persistent task tracking let your agents work autonomously across sessions. They pick up where they left off.

- **Native `@tool` compatibility.** Drop any LangChain `@tool` function into a workspace `tools/` directory and it works at next startup. No wrappers, no adapters -- just standard LangChain tools. Dependencies auto-install from `requirements.txt`.

- **Document intelligence built in.** [Docling](https://github.com/docling-project/docling) converts uploaded PDFs, DOCX, and PPTX to markdown with OCR. [Whisper](https://openai.com/index/whisper/) transcribes voice messages. Files are persisted with date partitioning and sibling output files -- your agent has a searchable filing cabinet.

- **Human-in-the-loop when it matters.** Approval gates pause execution and ask the user before the agent overwrites files, deletes tasks, or takes any action you configure. Timeout policies prevent agents from hanging indefinitely.

- **Multi-provider, multi-model.** Anthropic, OpenAI, AWS Bedrock, or any OpenAI-compatible API endpoint. Switch models per workspace without changing agent code.

## Features

### Agent Autonomy
- **Sub-agent spawning** — Agents spawn up to 8 concurrent background workers for parallel tasks
- **Self-scheduling** — Agents create their own cron jobs (`schedule_at`, `schedule_every`) that persist across restarts
- **Self-continuation** — Multi-step autonomous workflows via followup tool with depth limiting
- **Task management** — Persistent TASKS.yaml for tracking long-running work across sessions and heartbeats
- **Mid-execution messaging** — Agents send progress updates and files to users while working

### Web and Browser
- **Browser automation** — Playwright-based web interaction with accessibility tree navigation (11 tools: navigate, snapshot, click, type, select, scroll, screenshot, tabs, etc.)
- **Web search** — Brave Search API integration
- **Domain security** — Per-workspace allowlists and blocklists with wildcard support

### Document Intelligence
- **Docling processor** — Automatic PDF/DOCX/PPTX to markdown conversion with OCR (macOS native + EasyOCR)
- **Whisper processor** — Voice and audio message transcription
- **File persistence** — All uploads saved to `uploads/{YYYY-MM-DD}/` with sibling output convention (report.pdf → report.md)

### Framework
- **Multi-workspace orchestration** — Run multiple isolated agents simultaneously
- **Personality system** — Define agent identity via AGENT.md, USER.md, SOUL.md, HEARTBEAT.md
- **Conversation persistence** — Durable conversations via AsyncSqliteSaver that survive restarts
- **Conversation archiving** — Markdown + JSON exports on `/new`, `/compact`, and shutdown
- **Lane-based queue** — FIFO queue with separate lanes for main, subagent, and cron traffic
- **Queue-aware middleware** — Steer and interrupt modes redirect or abort agent runs when users send new messages
- **Approval gates** — Human-in-the-loop authorization for configurable tool calls (Telegram inline keyboards)
- **Heartbeat system** — Proactive agent check-ins with active hours, HEARTBEAT_OK suppression, and pre-flight skip
- **Static cron scheduler** — YAML-defined scheduled tasks per workspace
- **Token tracking** — Per-invocation JSONL metrics with today/session aggregation via `/status`
- **Timezone awareness** — Per-workspace IANA timezone for scheduling, display, and file partitioning
- **Slash commands** — `/new`, `/compact`, `/status`, `/queue`, `/help` (intercepted before the agent)
- **Sandboxed filesystem** — read, write, edit, glob, grep, file_info with path traversal protection
- **Custom workspace tools** — LangChain `@tool` functions per workspace with auto-dependency installation
- **Per-workspace `.env`** — Automatic environment variable loading for workspace-specific secrets
- **Dynamic framework prompt** — Agents automatically understand their capabilities based on loaded builtins

### Builtins

Tools and processors conditionally loaded based on available packages and API keys:

| Builtin | Type | Requires | Description |
|---------|------|----------|-------------|
| `browser` | Tool | `playwright` (core dep) | Web automation via Playwright with accessibility tree |
| `brave_search` | Tool | `BRAVE_API_KEY` | Web search via Brave API |
| `spawn` | Tool | — | Sub-agent spawning for concurrent background tasks |
| `cron` | Tool | — | Agent self-scheduling (one-time and recurring) |
| `task_tracker` | Tool | — | Persistent task management via TASKS.yaml |
| `send_message` | Tool | — | Mid-execution user messaging |
| `send_file` | Tool | — | Send workspace files to users |
| `followup` | Tool | — | Self-continuation for multi-step workflows |
| `memory_search` | Tool | `sqlite-vec` | Semantic search over past conversations |
| `shell` | Tool | — | Local shell command execution |
| `ssh` | Tool | `asyncssh` | Remote SSH execution |
| `elevenlabs` | Tool | `ELEVENLABS_API_KEY` | Text-to-speech voice responses |
| `file_persistence` | Processor | — | Universal file upload handling with date partitions |
| `docling` | Processor | `docling` (core dep) | PDF/DOCX/PPTX to markdown with OCR |
| `whisper` | Processor | `OPENAI_API_KEY` | Audio/voice transcription |
| `timestamp` | Processor | — | Message timestamp injection |

## Quick Start

### Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/) 2.0+
- A Telegram bot token ([create one via BotFather](https://core.telegram.org/bots#botfather))
- At least one model provider credential (Anthropic, OpenAI, or AWS Bedrock)

### Installation

```bash
# Clone the repository
git clone https://github.com/jsosoka/OpenPaw.git
cd OpenPaw

# Install core dependencies (includes Docling + Playwright)
poetry install

# Install Playwright browser
poetry run playwright install chromium

# Optional extras for additional builtins
poetry install -E voice          # Whisper transcription + ElevenLabs TTS
poetry install -E web            # Brave Search
poetry install -E system         # SSH remote execution
poetry install -E memory         # Semantic memory search (sqlite-vec)
poetry install -E all-builtins   # Everything above
```

### Configuration

1. Copy the example configuration:

```bash
cp config.example.yaml config.yaml
```

2. Set required environment variables:

```bash
# Channel
export TELEGRAM_BOT_TOKEN="your-telegram-token"

# Model provider (choose one or more)
export ANTHROPIC_API_KEY="your-key"         # Anthropic Claude
export OPENAI_API_KEY="your-openai-key"     # OpenAI GPT (also used by Whisper)
# AWS Bedrock (Kimi K2, Claude, Mistral, Nova, etc.)
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"

# Optional builtin API keys
export BRAVE_API_KEY="your-brave-key"       # Brave Search
export ELEVENLABS_API_KEY="your-key"        # Text-to-speech
```

3. Edit `config.yaml` with your model, channel, and builtin preferences. See `config.example.yaml` for all options.

### Create Your First Workspace

Each workspace requires four markdown files that define the agent's identity:

```bash
mkdir -p agent_workspaces/my-agent
touch agent_workspaces/my-agent/{AGENT,USER,SOUL,HEARTBEAT}.md
```

| File | Purpose |
|------|---------|
| `AGENT.md` | Capabilities and behavior guidelines |
| `USER.md` | User context and preferences |
| `SOUL.md` | Core personality and values |
| `HEARTBEAT.md` | Scratchpad for proactive check-ins (can start empty) |

Optional workspace files:

```
agent_workspaces/my-agent/
├── agent.yaml        # Per-workspace config overrides (model, channel, timezone)
├── .env              # Workspace-specific environment variables
├── tools/            # Custom LangChain @tool functions
│   ├── calendar.py
│   └── requirements.txt
└── crons/            # Scheduled task definitions
    └── daily-summary.yaml
```

### Custom Tools

Drop any LangChain `@tool` into the `tools/` directory:

```python
# agent_workspaces/my-agent/tools/weather.py
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    # Your implementation here
    return fetch_weather(city)
```

Add tool-specific dependencies to `tools/requirements.txt` — they auto-install at startup.

### Run

```bash
# Single workspace
poetry run openpaw -c config.yaml -w my-agent

# Multiple workspaces
poetry run openpaw -c config.yaml -w agent1,agent2

# All workspaces
poetry run openpaw -c config.yaml --all

# Verbose logging
poetry run openpaw -c config.yaml -w my-agent -v
```

## Architecture

```
OpenPawOrchestrator
  ├─ WorkspaceRunner["agent1"]
  │   └─ Channel → QueueManager → LaneQueue → Middleware → AgentRunner → LangGraph Agent
  ├─ WorkspaceRunner["agent2"]
  │   └─ (fully isolated: own channel, queue, agent, cron, heartbeat)
  └─ WorkspaceRunner["agent3"]
      └─ (fully isolated: own channel, queue, agent, cron, heartbeat)
```

Each workspace is fully isolated with its own channel adapter, queue manager, agent runner, cron scheduler, heartbeat scheduler, session manager, and conversation archiver. See [Architecture](docs/architecture.md) for the full component breakdown.

### Package Layout

```
openpaw/
├── domain/           # Pure business models (Message, Task, Session, etc.)
├── core/             # Configuration, logging, timezone, queue
├── agent/            # Agent execution, metrics, middleware, filesystem tools
├── workspace/        # Workspace management, message processing, agent factory
├── runtime/          # Orchestrator, scheduling, session management
├── stores/           # Persistence (tasks, sub-agents, dynamic crons, approval state)
├── channels/         # Channel adapters (Telegram) and slash command handlers
├── builtins/         # Extensible tools and processors (browser, spawn, docling, etc.)
├── subagent/         # Background agent coordination and lifecycle
└── utils/            # Filename sanitization and shared utilities
```

## Workspace Configuration

Place `agent.yaml` in the workspace root to customize behavior:

```yaml
name: My Assistant
description: A helpful personal assistant
timezone: America/Denver  # IANA timezone (default: UTC)

model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.7

channel:
  type: telegram
  token: ${TELEGRAM_BOT_TOKEN}
  allowed_users: []

heartbeat:
  enabled: true
  interval_minutes: 30
  active_hours: "09:00-22:00"
  suppress_ok: true
```

Environment variables use `${VAR}` syntax. Workspace config deep-merges over global defaults. See [Configuration](docs/configuration.md) for the full reference including approval gates, browser domain policies, builtin overrides, and queue settings.

## Slash Commands

Commands are intercepted before reaching the agent and handled by the framework directly.

| Command | Description |
|---------|-------------|
| `/new` | Archive current conversation and start fresh |
| `/compact` | Summarize conversation, archive it, start new with summary |
| `/status` | Show model, conversation stats, active tasks, token usage |
| `/queue <mode>` | Change queue mode (collect, steer, followup, interrupt) |
| `/help` | List available commands |

## Documentation

- [Getting Started](docs/getting-started.md) — Installation and first workspace setup
- [Configuration](docs/configuration.md) — Global and workspace configuration reference
- [Workspaces](docs/workspaces.md) — Workspace structure and personality files
- [Channels](docs/channels.md) — Channel system and Telegram setup
- [Queue System](docs/queue-system.md) — Queue modes, lanes, and concurrency
- [Cron Scheduler](docs/cron-scheduler.md) — Scheduled task configuration
- [Builtins](docs/builtins.md) — Available tools, processors, and adding custom ones
- [Architecture](docs/architecture.md) — System design and component interactions

## Development

```bash
# Run the full test suite (1,000+ tests)
poetry run pytest

# Lint
poetry run ruff check openpaw/
poetry run ruff check openpaw/ --fix

# Type check
poetry run mypy openpaw/
```

## License

[MIT](LICENSE)

## Credits

OpenPaw draws architectural inspiration from [OpenClaw](https://github.com/openclaw)'s command queue and channel patterns. Built on [LangGraph](https://langchain-ai.github.io/langgraph/) and [LangChain](https://www.langchain.com/).
