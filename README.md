# OpenPaw

OpenPaw is a multi-channel AI agent framework built on [LangGraph](https://langchain-ai.github.io/langgraph/) (`create_react_agent`). It enables running multiple isolated AI agent "workspaces," each with its own personality, communication channels, scheduled tasks, and optional capabilities.

## Features

- **Multi-Workspace Orchestration** - Run multiple isolated agents simultaneously, each with their own configuration
- **Agent Workspaces** - Define agent personalities through structured markdown files (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
- **Custom Workspace Tools** - Define LangChain `@tool` functions per workspace with auto-dependency installation
- **Channel Support** - Currently supports Telegram with extensible architecture for additional platforms
- **Lane-Based Queue System** - FIFO queue with configurable concurrency and multiple queue modes (collect, steer, followup, interrupt)
- **Cron Scheduler** - Define scheduled tasks per workspace via YAML configuration
- **Optional Builtins** - Conditionally loaded capabilities based on API key availability (web search, voice transcription, TTS)
- **Sandboxed Filesystem Access** - Per-workspace file operations (read, write, edit, glob, grep) with path traversal protection
- **Per-Workspace Environment** - Automatic `.env` loading for workspace-specific secrets and configuration
- **Agent Autonomy** - Self-continuation (followup), mid-execution messaging, and persistent task tracking across sessions
- **Heartbeat System** - Proactive agent check-ins with HEARTBEAT_OK suppression and active hours
- **Dynamic Framework Prompt** - Agents automatically understand their capabilities based on loaded builtins
- **Conversation Persistence** - Durable conversations via SQLite checkpointing with archival to markdown + JSON
- **Sub-Agent Spawning** - Spawn background agents for concurrent task execution with semaphore concurrency control
- **Web Browsing** - Playwright-based browser automation with accessibility tree navigation (agents interact via numbered element references)
- **Approval Gates** - Human-in-the-loop authorization for dangerous tool calls with configurable timeout and default actions
- **Queue-Aware Middleware** - Responsive agent behavior: steer, interrupt, and redirect mid-execution based on new user messages
- **Document Processing** - Inbound file handling with Docling (PDF/DOCX to markdown) and Whisper (audio transcription)
- **Timezone Awareness** - Per-workspace timezone configuration with "store UTC, display local" pattern
- **Token Usage Tracking** - Per-invocation token logging with daily/session aggregation via /status command

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/OpenPaw.git
cd OpenPaw

# Install dependencies
poetry install

# Optional: Install builtin extras
poetry install --extras voice      # Whisper + ElevenLabs
poetry install --extras web        # Brave Search
poetry install --extras all-builtins  # Everything

# Install browser automation (optional, for web browsing builtin)
poetry run playwright install chromium
```

### Configuration

1. Copy the example configuration:

```bash
cp config.example.yaml config.yaml
```

2. Set required environment variables:

```bash
export TELEGRAM_BOT_TOKEN="your-telegram-token"

# Model provider (choose one)
export ANTHROPIC_API_KEY="your-key-here"      # For Anthropic models
export OPENAI_API_KEY="your-openai-key"        # For OpenAI models

# For AWS Bedrock models (Kimi K2, Claude, Mistral, etc.)
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"

# Optional builtins
export BRAVE_API_KEY="your-brave-key"
export ELEVENLABS_API_KEY="your-elevenlabs-key"
```

3. Edit `config.yaml` to configure channels, queue behavior, and builtins.

### Create Your First Workspace

Each workspace requires four markdown files:

```bash
mkdir -p agent_workspaces/my-agent
cd agent_workspaces/my-agent

# Create required files
touch AGENT.md USER.md SOUL.md HEARTBEAT.md
```

See [docs/workspaces.md](docs/workspaces.md) for detailed workspace structure.

### Workspace Tools

Workspaces can define custom LangChain tools in a `tools/` directory:

```python
# agent_workspaces/my-agent/tools/calendar.py
from langchain_core.tools import tool

@tool
def get_events(days: int = 7) -> str:
    """Get upcoming calendar events."""
    return fetch_calendar_events(days)
```

Dependencies are auto-installed from `tools/requirements.txt` at startup:

```
# agent_workspaces/my-agent/tools/requirements.txt
icalendar>=5.0.0
caldav>=1.0.0
```

Workspace-specific secrets go in `.env` (auto-loaded):

```bash
# agent_workspaces/my-agent/.env
CALENDAR_API_KEY=your-key
```

### Run OpenPaw

```bash
# Run a single workspace
poetry run openpaw -c config.yaml -w my-agent

# Run multiple workspaces
poetry run openpaw -c config.yaml -w agent1,agent2

# Run all workspaces
poetry run openpaw -c config.yaml --all

# Enable verbose logging
poetry run openpaw -c config.yaml -w my-agent -v
```

## Architecture

```
OpenPawOrchestrator
  ├─ WorkspaceRunner["agent1"]
  │   └─ Channel → QueueManager → LaneQueue → AgentRunner → LangGraph ReAct Agent
  ├─ WorkspaceRunner["agent2"]
  │   └─ (isolated: own channel, queue, agent)
  └─ WorkspaceRunner["agent3"]
      └─ (isolated: own channel, queue, agent)
```

Each workspace is fully isolated with its own channels, queue manager, agent runner, and cron scheduler.

## Documentation

- [Getting Started](docs/getting-started.md) - Detailed installation and first workspace setup
- [Configuration](docs/configuration.md) - Global and workspace configuration reference
- [Workspaces](docs/workspaces.md) - Workspace structure, personality files, and skills
- [Channels](docs/channels.md) - Channel system and Telegram setup
- [Queue System](docs/queue-system.md) - Queue modes, lanes, and concurrency
- [Cron Scheduler](docs/cron-scheduler.md) - Scheduled task configuration
- [Builtins](docs/builtins.md) - Available tools/processors and adding custom ones
- [Architecture](docs/architecture.md) - System design and component interactions

## Development

```bash
# Run tests
poetry run pytest

# Lint
poetry run ruff check openpaw/
poetry run ruff check openpaw/ --fix

# Type check
poetry run mypy openpaw/
```

## Deployment

### Running as a Service (macOS)

A launchd plist template is provided at `deploy/launchd/com.openpaw.agent.plist`.

```bash
# 1. Copy and customize the plist
cp deploy/launchd/com.openpaw.agent.plist ~/Library/LaunchAgents/

# 2. Edit paths in the plist to match your installation
#    - WorkingDirectory: your OpenPaw project root
#    - StandardOutPath/StandardErrorPath: log file paths
#    - ProgramArguments: path to poetry binary

# 3. Load the service
launchctl load ~/Library/LaunchAgents/com.openpaw.agent.plist

# 4. Check status
launchctl list | grep openpaw

# 5. Unload (to stop)
launchctl unload ~/Library/LaunchAgents/com.openpaw.agent.plist
```

### Browser Automation

For workspaces using the `browser` builtin, install Chromium on the target machine:

```bash
poetry run playwright install chromium
```

The browser runs headless by default. On macOS, you may need to grant accessibility permissions for full functionality.

## Requirements

- Python 3.11+ (3.12+ recommended)
- Poetry for dependency management
- Telegram Bot Token (for Telegram channel)
- Model provider credentials (one of):
  - Anthropic API key (for Claude models via Anthropic)
  - OpenAI API key (for GPT models)
  - AWS credentials (for Bedrock models: Kimi K2, Claude, Mistral, etc.)

## License

MIT

## Credits

OpenPaw draws architectural inspiration from OpenClaw's command queue and channel patterns.
