# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
poetry install

# Run single workspace
poetry run openpaw -c config.yaml -w <workspace_name>
poetry run openpaw -c config.yaml -w gilfoyle -v  # verbose

# Run multiple workspaces
poetry run openpaw -c config.yaml -w gilfoyle,assistant

# Run all workspaces
poetry run openpaw -c config.yaml --all
poetry run openpaw -c config.yaml -w "*"

# Or via python module
poetry run python -m openpaw.cli -c config.yaml -w <workspace_name>

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
OpenPawOrchestrator
  ├─ WorkspaceRunner["gilfoyle"]
  │   └─ Channel → QueueManager → LaneQueue → AgentRunner → DeepAgent
  ├─ WorkspaceRunner["assistant"]
  │   └─ (isolated: own channel, queue, agent)
  └─ WorkspaceRunner["scheduler"]
      └─ (isolated: own channel, queue, agent)
```

Each workspace is fully isolated with its own channels, queue, agent runner, and cron scheduler.

### Key Components

**`openpaw/cli.py`** - CLI entry point. Parses arguments, supports single workspace (`-w name`), multiple workspaces (`-w name1,name2`), or all workspaces (`--all` or `-w "*"`).

**`openpaw/orchestrator.py`** - `OpenPawOrchestrator` manages multiple `WorkspaceRunner` instances. Handles concurrent startup/shutdown and workspace discovery.

**`openpaw/main.py`** - `WorkspaceRunner` manages a single workspace: loads workspace config, merges with global config, initializes queue system, sets up channels, schedules crons, and runs the message loop.

**`openpaw/core/agent.py`** - `AgentRunner` wraps DeepAgents' `create_deep_agent()`. It stitches workspace markdown files into a system prompt, passes the skills directory to DeepAgents natively, and configures `FilesystemBackend` for sandboxed workspace file access.

**`openpaw/core/config.py`** - Pydantic models for global and workspace configuration. Handles environment variable expansion (`${VAR}`) and deep-merging workspace config over global defaults.

**`openpaw/workspace/loader.py`** - Loads agent "workspaces" from `agent_workspaces/<name>/`. Each workspace requires: `AGENT.md`, `USER.md`, `SOUL.md`, `HEARTBEAT.md`. Optional `agent.yaml` and `crons/*.yaml` are loaded if present. These are combined into XML-tagged sections for the system prompt.

**`openpaw/queue/lane.py`** - Lane-based FIFO queue with configurable concurrency per lane (main, subagent, cron). Supports OpenClaw-style queue modes: `collect`, `steer`, `followup`, `interrupt`.

**`openpaw/channels/telegram.py`** - Telegram bot adapter using `python-telegram-bot`. Converts platform messages to unified `Message` format, handles allowlisting, and supports voice/audio messages.

**`openpaw/builtins/`** - Optional capabilities (tools and processors) conditionally loaded based on API key availability. See "Builtins System" section.

**`openpaw/cron/scheduler.py`** - `CronScheduler` uses APScheduler to execute scheduled tasks. Each job builds a fresh agent instance, injects the cron prompt, and routes output to the configured channel. Also handles dynamic tasks from `CronTool`.

**`openpaw/cron/dynamic.py`** - `DynamicCronStore` for persisting agent-scheduled tasks to workspace-local JSON. Includes `DynamicCronTask` dataclass and factory functions.

**`openpaw/heartbeat/scheduler.py`** - `HeartbeatScheduler` for proactive agent check-ins. Supports active hours, HEARTBEAT_OK suppression, and configurable intervals.

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

#### AWS Bedrock Configuration

OpenPaw supports AWS Bedrock models via the `bedrock_converse` provider. Available models include Kimi K2 Thinking, Claude, Mistral, and others.

**Global config (`config.yaml`)**:

```yaml
agent:
  model: bedrock_converse:moonshot.kimi-k2-thinking
```

**Per-workspace (`agent.yaml`)**:

```yaml
model:
  provider: bedrock_converse
  model: moonshot.kimi-k2-thinking
  region: us-east-1  # Optional, defaults to AWS_REGION env var
```

**Available Bedrock Models**:
- `moonshot.kimi-k2-thinking` - Moonshot Kimi K2 (1T MoE, 256K context)
- `anthropic.claude-3-sonnet-20240229-v1:0` - Claude 3 Sonnet
- `anthropic.claude-3-haiku-20240307-v1:0` - Claude 3 Haiku
- `mistral.mistral-large-2402-v1:0` - Mistral Large

**AWS Credentials**: Configure via environment variables or AWS CLI profile:

```bash
# Environment variables
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"

# Or use AWS CLI profile
aws configure
```

**Region Availability** (Kimi K2): `us-east-1`, `us-east-2`, `us-west-2`, `ap-northeast-1`, `ap-south-1`, `sa-east-1`

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

### Dynamic Scheduling (CronTool)

Agents can schedule their own follow-up actions at runtime using the CronTool builtin. This enables autonomous workflows like "remind me in 20 minutes" or "check on this PR every hour".

**Available Tools**:
- `schedule_at` - Schedule a one-time action at a specific timestamp
- `schedule_every` - Schedule a recurring action at fixed intervals
- `list_scheduled` - List all pending scheduled tasks
- `cancel_scheduled` - Cancel a scheduled task by ID

**Storage**: Tasks persist to `{workspace}/dynamic_crons.json` and survive restarts. One-time tasks are automatically cleaned up after execution or if expired on startup.

**Routing**: Responses are sent back to the first allowed user in the workspace's channel config.

**Configuration** (optional, in `agent.yaml` or global config):

```yaml
builtins:
  cron:
    enabled: true
    config:
      min_interval_seconds: 300  # Minimum interval for recurring tasks (default: 5 min)
      max_tasks: 50              # Maximum pending tasks per workspace
```

**Example Usage** (by agent):
- User: "Ping me in 10 minutes to check on the deploy"
- Agent calls `schedule_at` with timestamp 10 minutes from now
- Task fires, agent sends reminder to user's chat

### Heartbeat System

The HeartbeatScheduler enables proactive agent check-ins on a configurable schedule. Agents can use this to monitor ongoing tasks, provide status updates, or maintain context without user prompts.

**Configuration** (in `agent.yaml`):

```yaml
heartbeat:
  enabled: true
  interval_minutes: 30           # How often to check in
  active_hours: "09:00-17:00"    # Only run during these hours (optional)
  suppress_ok: true              # Don't send message if agent responds "HEARTBEAT_OK"
  output:
    channel: telegram
    chat_id: 123456789
```

**HEARTBEAT_OK Protocol**: If the agent determines there's nothing to report, it can respond with exactly "HEARTBEAT_OK" and no message will be sent (when `suppress_ok: true`). This prevents noisy "all clear" messages.

**Active Hours**: Heartbeats only fire within the specified window (workspace timezone). Outside active hours, heartbeats are silently skipped.

**Prompt Template**: The heartbeat prompt is defined in the agent's `HEARTBEAT.md` file and can reference the current timestamp.

### Filesystem Access

Agents have sandboxed filesystem access to their workspace directory via DeepAgents `FilesystemBackend`. This enables:
- Reading/writing workspace files
- Persisting state across cron runs
- Organizing workspace-specific data

Access is restricted to the workspace root—agents cannot read/write outside their directory.

### Builtins System

OpenPaw provides optional built-in capabilities that are conditionally available based on API keys. Builtins come in two types:

**Tools** - LangChain-compatible tools the agent can invoke:
- `brave_search` - Web search via Brave API (requires `BRAVE_API_KEY`)
- `elevenlabs` - Text-to-speech for voice responses (requires `ELEVENLABS_API_KEY`)
- `cron` - Agent self-scheduling (no API key required, see "Dynamic Scheduling" section)

**Processors** - Channel-layer message transformers:
- `whisper` - Audio transcription for voice messages (requires `OPENAI_API_KEY`)

**`openpaw/builtins/`** - Package structure:
```
builtins/
├── base.py           # BaseBuiltinTool, BaseBuiltinProcessor, BuiltinMetadata
├── registry.py       # Singleton registry of all builtins
├── loader.py         # Workspace-aware loading with allow/deny
├── tools/            # LangChain tool implementations
│   ├── brave_search.py
│   ├── elevenlabs_tts.py
│   └── cron.py       # Agent self-scheduling
└── processors/       # Message preprocessors
    └── whisper.py
```

**Configuration** (global or per-workspace):

```yaml
builtins:
  allow: []           # Empty = allow all available
  deny:
    - group:voice     # Deny entire groups with "group:" prefix

  brave_search:
    enabled: true
    config:
      count: 5

  whisper:
    enabled: true
    config:
      model: whisper-1

  elevenlabs:
    enabled: true
    config:
      voice_id: 21m00Tcm4TlvDq8ikWAM
```

**Adding New Builtins**: Create a class extending `BaseBuiltinTool` or `BaseBuiltinProcessor`, define `metadata` with prerequisites, and register in `registry.py`.

### Memory & Summarization

- `InMemorySaver` checkpointer enables multi-turn conversation memory (per session, lost on restart)
- DeepAgents includes `SummarizationMiddleware` that auto-compresses context when it grows large (keeps last 20 messages by default)
- For persistent storage across restarts, swap to `SqliteSaver`
