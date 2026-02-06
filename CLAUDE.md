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

**`openpaw/main.py`** - `OpenPaw` class orchestrates everything: loads workspace, initializes queue system, sets up channels, and runs the main loop.

**`openpaw/core/agent.py`** - `AgentRunner` wraps DeepAgents' `create_deep_agent()`. It stitches workspace markdown files into a system prompt and passes the skills directory to DeepAgents natively.

**`openpaw/workspace/loader.py`** - Loads agent "workspaces" from `agent_workspaces/<name>/`. Each workspace requires: `AGENT.md`, `USER.md`, `SOUL.md`, `HEARTBEAT.md`. These are combined into XML-tagged sections for the system prompt.

**`openpaw/queue/lane.py`** - Lane-based FIFO queue with configurable concurrency per lane (main, subagent, cron). Supports OpenClaw-style queue modes: `collect`, `steer`, `followup`, `interrupt`.

**`openpaw/channels/telegram.py`** - Telegram bot adapter using `python-telegram-bot`. Converts platform messages to unified `Message` format and handles allowlisting.

### Agent Workspace Structure

```
agent_workspaces/<name>/
├── AGENT.md      # Capabilities, behavior guidelines
├── USER.md       # User context/preferences
├── SOUL.md       # Core personality, values
├── HEARTBEAT.md  # Current state, session notes
└── skills/       # DeepAgents native skills (SKILL.md format)
```

### Configuration

`config.yaml` defines: queue settings, lane concurrency, channel credentials, agent model/temperature, and cron jobs. See `config.example.yaml`.

### Memory & Summarization

- `InMemorySaver` checkpointer enables multi-turn conversation memory (per session, lost on restart)
- DeepAgents includes `SummarizationMiddleware` that auto-compresses context when it grows large (keeps last 20 messages by default)
- For persistent storage across restarts, swap to `SqliteSaver`
