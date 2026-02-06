# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
poetry install

# Run the bot
poetry run openpaw -c config.yaml -w <workspace_name>
poetry run openpaw -c config.yaml -w gilfoyle -v  # verbose

# Or via python module
poetry run python -m openpaw.main -c config.yaml -w <workspace_name>

# Lint
poetry run ruff check openpaw/
poetry run ruff check openpaw/ --fix

# Type check
poetry run mypy openpaw/

# Tests
poetry run pytest
poetry run pytest tests/test_specific.py -v
poetry run pytest -k "test_name"
```

## Architecture

OpenPaw is a multi-channel AI agent framework built on DeepAgents (LangGraph). It draws architectural inspiration from OpenClaw's command queue and channel patterns.

### Core Flow

```
Channel (Telegram) → QueueManager → LaneQueue → AgentRunner → DeepAgent
     ↑                                              ↓
     └──────────────── Response ────────────────────┘
```

### Key Components

**`openpaw/main.py`** - `OpenPaw` class orchestrates everything: loads workspace, merges global/workspace config, initializes queue system, sets up channels, schedules crons, and runs the main loop.

**`openpaw/core/agent.py`** - `AgentRunner` wraps DeepAgents' `create_deep_agent()`. It stitches workspace markdown files into a system prompt, passes the skills directory to DeepAgents natively, and configures `FilesystemBackend` for sandboxed workspace file access.

**`openpaw/core/config.py`** - Pydantic models for global and workspace configuration. Handles environment variable expansion (`${VAR}`) and deep-merging workspace config over global defaults.

**`openpaw/workspace/loader.py`** - Loads agent "workspaces" from `agent_workspaces/<name>/`. Each workspace requires: `AGENT.md`, `USER.md`, `SOUL.md`, `HEARTBEAT.md`. Optional `agent.yaml` and `crons/*.yaml` are loaded if present. These are combined into XML-tagged sections for the system prompt.

**`openpaw/queue/lane.py`** - Lane-based FIFO queue with configurable concurrency per lane (main, subagent, cron). Supports OpenClaw-style queue modes: `collect`, `steer`, `followup`, `interrupt`.

**`openpaw/channels/telegram.py`** - Telegram bot adapter using `python-telegram-bot`. Converts platform messages to unified `Message` format and handles allowlisting.

**`openpaw/cron/scheduler.py`** - `CronScheduler` uses APScheduler to execute scheduled tasks. Each job builds a fresh agent instance, injects the cron prompt, and routes output to the configured channel.

### Agent Workspace Structure

```
agent_workspaces/<name>/
├── AGENT.md      # Capabilities, behavior guidelines
├── USER.md       # User context/preferences
├── SOUL.md       # Core personality, values
├── HEARTBEAT.md  # Current state, session notes
├── agent.yaml    # Optional per-workspace configuration (model, channel, queue)
├── crons/        # Scheduled task definitions
│   └── *.yaml    # Individual cron job configurations
└── skills/       # DeepAgents native skills (SKILL.md format)
```

### Configuration

**Global (`config.yaml`)** - Defines defaults for all workspaces: queue settings, lane concurrency, channel credentials, agent model/temperature. See `config.example.yaml`.

**Per-Workspace (`agent.yaml`)** - Optional workspace-specific overrides. Supports environment variable substitution via `${VAR}` syntax. Workspace config inherits from global and overrides specific fields.

#### Workspace Configuration

Place `agent.yaml` in the workspace root to customize behavior:

```yaml
name: Gilfoyle
description: Sarcastic systems architect

model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.5
  max_turns: 50

channel:
  type: telegram
  token: ${TELEGRAM_BOT_TOKEN}
  allowed_users: []
  allowed_groups: []

queue:
  mode: collect
  debounce_ms: 1000
```

**Environment Variables**: Use `${VAR_NAME}` syntax for secrets and dynamic values. OpenPaw expands these from environment at load time.

**Config Merging**: Workspace settings deep-merge over global config. Missing fields inherit from global, present fields override.

### Cron System

Workspaces can define scheduled tasks via YAML files in `crons/` directory.

**Cron File Format (`crons/<name>.yaml`)**:

```yaml
name: daily-summary
schedule: "0 9 * * *"  # Standard cron format
enabled: true

prompt: |
  Generate a daily summary of system status and pending tasks.
  Review workspace files and provide a concise report.

output:
  channel: telegram
  chat_id: 123456789  # Channel-specific routing
```

**Schedule Format**: Standard cron expression `"minute hour day-of-month month day-of-week"`
- `"0 9 * * *"` - Every day at 9:00 AM
- `"*/15 * * * *"` - Every 15 minutes
- `"0 0 * * 0"` - Every Sunday at midnight

**Execution**: CronScheduler builds a fresh agent instance (no checkpointer), injects the prompt, routes output to specified channel.

**Enable/Disable**: Set `enabled: false` to disable a cron without deleting the file.

### Filesystem Access

Agents have sandboxed filesystem access to their workspace directory via DeepAgents `FilesystemBackend`. This enables:
- Reading/writing workspace files
- Persisting state across cron runs
- Organizing workspace-specific data

Access is restricted to the workspace root—agents cannot read/write outside their directory.

### Memory & Summarization

- `InMemorySaver` checkpointer enables multi-turn conversation memory (per session, lost on restart)
- DeepAgents includes `SummarizationMiddleware` that auto-compresses context when it grows large (keeps last 20 messages by default)
- For persistent storage across restarts, swap to `SqliteSaver`
