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

OpenPaw is a multi-channel AI agent framework built on LangGraph (`create_react_agent`). It draws architectural inspiration from OpenClaw's command queue and channel patterns.

### Core Flow

```
OpenPawOrchestrator
  ├─ WorkspaceRunner["gilfoyle"]
  │   └─ Channel → QueueManager → LaneQueue → AgentRunner → LangGraph ReAct Agent
  ├─ WorkspaceRunner["assistant"]
  │   └─ (isolated: own channel, queue, agent)
  └─ WorkspaceRunner["scheduler"]
      └─ (isolated: own channel, queue, agent)
```

Each workspace is fully isolated with its own channels, queue, agent runner, and cron scheduler.

### Key Components

**`openpaw/cli.py`** - CLI entry point. Parses arguments, supports single workspace (`-w name`), multiple workspaces (`-w name1,name2`), or all workspaces (`--all` or `-w "*"`).

**`openpaw/orchestrator.py`** - `OpenPawOrchestrator` manages multiple `WorkspaceRunner` instances. Handles concurrent startup/shutdown and workspace discovery.

**`openpaw/main.py`** - `WorkspaceRunner` manages a single workspace: loads workspace config, merges with global config, initializes queue system, sets up channels via factory, manages `AsyncSqliteSaver` lifecycle, wires command routing, schedules crons, and runs the message loop.

**`openpaw/core/agent.py`** - `AgentRunner` wraps LangGraph's `create_react_agent()`. It stitches workspace markdown files into a system prompt via `init_chat_model()` for multi-provider support, configures sandboxed filesystem tools for workspace access, and tracks per-invocation token usage via `UsageMetadataCallbackHandler`. Supports `extra_model_kwargs` for OpenAI-compatible API endpoints (e.g., `base_url`).

**`openpaw/core/metrics.py`** - Token usage tracking infrastructure. `InvocationMetrics` dataclass, `extract_metrics_from_callback()` for `UsageMetadataCallbackHandler`, `TokenUsageLogger` (thread-safe JSONL append to `.openpaw/token_usage.jsonl`), and `TokenUsageReader` for aggregation (today/session).

**`openpaw/core/config.py`** - Pydantic models for global and workspace configuration. Handles environment variable expansion (`${VAR}`) and deep-merging workspace config over global defaults.

**`openpaw/workspace/loader.py`** - Loads agent "workspaces" from `agent_workspaces/<name>/`. Each workspace requires: `AGENT.md`, `USER.md`, `SOUL.md`, `HEARTBEAT.md`. Optional `agent.yaml` and `crons/*.yaml` are loaded if present. These are combined into XML-tagged sections for the system prompt.

**`openpaw/workspace/tool_loader.py`** - Dynamically loads LangChain tools from workspace `tools/` directories. Imports Python files and extracts `@tool` decorated functions (BaseTool instances).

**`openpaw/queue/lane.py`** - Lane-based FIFO queue with configurable concurrency per lane (main, subagent, cron). Supports OpenClaw-style queue modes: `collect`, `steer`, `followup`, `interrupt`.

**`openpaw/channels/telegram.py`** - Telegram bot adapter using `python-telegram-bot`. Converts platform messages to unified `Message` format, handles allowlisting, and supports voice/audio messages, documents, and photo uploads.

**`openpaw/channels/factory.py`** - Channel factory. Decouples `WorkspaceRunner` from concrete channel types via `create_channel(channel_type, config, workspace_name)`. Currently supports `telegram`; new providers register here.

**`openpaw/session/manager.py`** - `SessionManager` for tracking conversation threads per session. Thread-safe JSON persistence at `{workspace}/.openpaw/sessions.json`. Provides `get_thread_id()`, `new_conversation()`, `get_state()`, `increment_message_count()`.

**`openpaw/commands/`** - Framework command system. `CommandHandler` ABC + `CommandRouter` registry + `CommandContext` for runtime dependencies. Commands are routed BEFORE inbound processors to avoid content modification breaking `is_command` detection.

**`openpaw/commands/handlers/`** - Built-in command handlers: `/start`, `/new`, `/compact`, `/help`, `/queue`, `/status`. See "Command System" section.

**`openpaw/memory/archiver.py`** - `ConversationArchiver` for exporting conversations from the LangGraph checkpointer. Produces dual-format output: markdown (human-readable) + JSON sidecar (machine-readable) at `{workspace}/memory/conversations/`.

**`openpaw/builtins/`** - Optional capabilities (tools and processors) conditionally loaded based on API key availability. See "Builtins System" section.

**`openpaw/builtins/tools/_channel_context.py`** - Shared `contextvars` module for session-safe channel/session state. Used by `send_message` and `send_file` to access the active channel and session key during tool execution.

**`openpaw/builtins/tools/send_message.py`** - Mid-execution messaging tool. Uses shared `_channel_context` for session-safe state. Lets agents push updates to users while continuing to work.

**`openpaw/builtins/tools/send_file.py`** - `SendFileTool` for sending workspace files to users via channel. Validates files within sandbox, infers MIME type, enforces 50MB limit. Uses shared `_channel_context`.

**`openpaw/builtins/tools/followup.py`** - Self-continuation tool. Agents request re-invocation after responding, enabling multi-step autonomous workflows with depth limiting.

**`openpaw/builtins/tools/task.py`** - Task management tools (`create_task`, `update_task`, `list_tasks`, `get_task`). CRUD over `TASKS.yaml` for tracking long-running operations across heartbeats.

**`openpaw/task/store.py`** - `TaskStore` for YAML-based task persistence. Thread-safe with `_load_unlocked`/`_save_unlocked` pattern for atomic compound operations.

**`openpaw/tools/filesystem.py`** - `FilesystemTools` providing sandboxed file operations: `ls`, `read_file`, `write_file`, `overwrite_file`, `edit_file`, `glob_files`, `grep_files`, `file_info`. Path traversal protection via `resolve_sandboxed_path()`. `read_file` has a 100K character safety valve. `grep_files` supports `context_lines` for surrounding context.

**`openpaw/tools/sandbox.py`** - Standalone `resolve_sandboxed_path()` utility. Validates paths within workspace root, rejecting absolute paths, `~`, `..`, and `.openpaw/` access. Shared by `FilesystemTools`, `SendFileTool`, and inbound processors (DoclingProcessor, WhisperProcessor).

**`openpaw/utils/filename.py`** - Filename sanitization and deduplication utilities. `sanitize_filename()` removes special characters, normalizes spaces, and lowercases. `deduplicate_path()` appends counters (1), (2), etc. for uniqueness.

**`openpaw/builtins/processors/file_persistence.py`** - `FilePersistenceProcessor` saves all uploaded files to `uploads/{YYYY-MM-DD}/` with date partitioning. Sets `attachment.saved_path` for downstream processors.

**`openpaw/cron/scheduler.py`** - `CronScheduler` uses APScheduler to execute scheduled tasks. Each job builds a fresh agent instance, injects the cron prompt, and routes output to the configured channel. Also handles dynamic tasks from `CronTool`.

**`openpaw/cron/dynamic.py`** - `DynamicCronStore` for persisting agent-scheduled tasks to workspace-local JSON. Includes `DynamicCronTask` dataclass and factory functions.

**`openpaw/heartbeat/scheduler.py`** - `HeartbeatScheduler` for proactive agent check-ins. Supports active hours, HEARTBEAT_OK suppression, configurable intervals, pre-flight skip (avoids LLM call when HEARTBEAT.md is empty and no active tasks), task summary injection into heartbeat prompt, and JSONL event logging with token metrics.

### Agent Workspace Structure

```
agent_workspaces/<name>/
├── AGENT.md      # Capabilities, behavior guidelines
├── USER.md       # User context/preferences
├── SOUL.md       # Core personality, values
├── HEARTBEAT.md  # Current state, session notes
├── agent.yaml    # Optional per-workspace configuration (model, channel, queue)
├── .env          # Workspace-specific environment variables (auto-loaded)
├── .openpaw/     # Framework internals (protected from agent access)
│   ├── conversations.db  # AsyncSqliteSaver checkpoint database
│   ├── sessions.json     # Session/conversation thread state
│   └── token_usage.jsonl # Token usage metrics (append-only)
├── uploads/      # User-uploaded files (from FilePersistenceProcessor)
│   └── {YYYY-MM-DD}/  # Date-partitioned file storage
│       ├── report.pdf        # Original uploaded file
│       ├── report.md         # Docling-converted markdown (sibling)
│       ├── voice_123.ogg     # Original audio file
│       └── voice_123.txt     # Whisper transcript (sibling)
├── heartbeat_log.jsonl   # Heartbeat event log (outcomes, metrics, task counts)
├── memory/
│   └── conversations/    # Archived conversation exports
│       ├── conv_*.md     # Markdown archives (human-readable)
│       └── conv_*.json   # JSON sidecars (machine-readable)
├── crons/        # Scheduled task definitions
│   └── *.yaml    # Individual cron job configurations
├── skills/       # LangChain skill directories (SKILL.md format)
└── tools/        # LangChain tools (Python files with @tool decorated functions)
```

### Configuration

**Global (`config.yaml`)** - Defines defaults for all workspaces: queue settings, lane concurrency, channel credentials, agent model/temperature. See `config.example.yaml`.

**Per-Workspace (`agent.yaml`)** - Optional workspace-specific overrides. Supports environment variable substitution via `${VAR}` syntax. Workspace config inherits from global and overrides specific fields.

#### Workspace Configuration

Place `agent.yaml` in the workspace root to customize behavior:

```yaml
name: Gilfoyle
description: Sarcastic systems architect
timezone: America/Denver  # IANA timezone identifier (default: UTC)

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
- `us.anthropic.claude-haiku-4-5-20251001-v1:0` - Claude Haiku 4.5
- `amazon.nova-pro-v1:0` - Amazon Nova Pro
- `amazon.nova-lite-v1:0` - Amazon Nova Lite
- `mistral.mistral-large-2402-v1:0` - Mistral Large

**Note**: Newer Bedrock models may require inference profile IDs (prefixed with `us.` or `global.`) instead of bare model IDs. Use `aws bedrock list-inference-profiles` to discover available profiles. The `api_key` field is automatically excluded for Bedrock providers.

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

#### OpenAI-Compatible APIs

Any OpenAI-compatible provider can be used by specifying `base_url` in the workspace model config. Extra kwargs beyond the standard set (`provider`, `model`, `api_key`, `temperature`, `max_turns`, `timeout_seconds`, `region`) are passed through to `init_chat_model()`.

```yaml
model:
  provider: openai
  model: kimi-k2.5
  api_key: ${MOONSHOT_API_KEY}
  base_url: https://api.moonshot.ai/v1
  temperature: 1.0
```

### Token Usage Tracking

Every agent invocation (user messages, cron jobs, heartbeats) logs token counts to `{workspace}/.openpaw/token_usage.jsonl`. The `/status` command displays tokens today and tokens this session.

**Components**: `InvocationMetrics` (dataclass), `TokenUsageLogger` (thread-safe JSONL writer), `TokenUsageReader` (aggregation). All in `openpaw/core/metrics.py`.

**Integration**: `AgentRunner.run()` creates a `UsageMetadataCallbackHandler` per invocation. After completion, metrics are extracted via `extract_metrics_from_callback()` and exposed via `agent_runner.last_metrics`. `WorkspaceRunner`, `CronScheduler`, and `HeartbeatScheduler` pass the logger to record each invocation.

### Timezone Handling

OpenPaw uses a "store in UTC, display in workspace timezone" pattern. The `timezone` field in `agent.yaml` (IANA identifier, default `"UTC"`) controls all time-related display and scheduling.

**What uses workspace timezone:**
- Heartbeat active hours window (`active_hours: "09:00-17:00"`)
- Cron schedule expressions (APScheduler `CronTrigger`)
- Agent-created scheduled tasks (`schedule_at` timestamp parsing)
- File upload date partitions (`uploads/{YYYY-MM-DD}/`)
- `/status` "tokens today" day boundary
- Display timestamps in conversation archives, task notes, and filesystem listings

**What remains UTC (internal storage):**
- JSONL logs (token_usage.jsonl, heartbeat_log.jsonl)
- Session state (sessions.json)
- Task internal timestamps (created_at, started_at, completed_at in TASKS.yaml)
- Conversation archive JSON sidecar files
- LangGraph checkpoint data

**Utilities** (`openpaw/core/timezone.py`):
- `workspace_now(timezone_str)` — Current time in workspace timezone
- `format_for_display(dt, timezone_str, fmt)` — Convert UTC datetime to display string

**Validation:** `WorkspaceConfig.timezone` has a Pydantic validator that rejects invalid IANA identifiers at config load time.

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

**Note:** Cron schedule expressions fire in the workspace timezone.

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

**Active Hours**: Heartbeats only fire within the specified window (workspace timezone). Outside active hours, heartbeats are silently skipped. **Note:** `active_hours` are interpreted in the workspace timezone.

**Pre-flight Skip**: Before invoking the LLM, the scheduler checks HEARTBEAT.md and TASKS.yaml. If HEARTBEAT.md is empty/trivial and no active tasks exist, the heartbeat is skipped entirely — saving API costs for idle workspaces.

**Task Summary Injection**: When active tasks exist, a compact summary is injected into the heartbeat prompt as `<active_tasks>` XML tags. This avoids an extra LLM tool call to `list_tasks()`.

**Event Logging**: Every heartbeat event is logged to `{workspace}/heartbeat_log.jsonl` with outcome, duration, token metrics, and active task count.

**Prompt Template**: The heartbeat prompt is built dynamically from a structured template. `HEARTBEAT.md` serves as a scratchpad for agent-maintained notes on what to check during heartbeats.

### Filesystem Access

Agents have sandboxed filesystem access to their workspace directory via `FilesystemTools` (`openpaw/tools/filesystem.py`). Available operations: `ls`, `read_file`, `write_file`, `overwrite_file`, `edit_file`, `glob_files`, `grep_files`, `file_info`. Path traversal protection via `resolve_sandboxed_path()` in `openpaw/tools/sandbox.py`.

- `file_info`: Lightweight metadata (size, line count, binary detection, read strategy hints) without reading content
- `grep_files`: Supports `context_lines` parameter for surrounding context (maps to ripgrep `-C`)
- `read_file`: 100K character safety valve prevents context window exhaustion on large files

Access is restricted to the workspace root — agents cannot read/write outside their directory. The `.openpaw/` directory is additionally protected; agents cannot read or write framework internals (checkpoint DB, session state, token logs). Agents are encouraged to organize their workspace (subdirectories, notes, state files) for continuity across conversations.

### Workspace Tools

Workspaces can define custom LangChain tools in a `tools/` directory. These are Python files containing `@tool` decorated functions that are automatically loaded and made available to the agent.

**Example** (`tools/calendar.py`):

```python
from langchain_core.tools import tool

@tool
def get_upcoming_events(days_ahead: int = 7) -> str:
    """Get upcoming calendar events.

    Args:
        days_ahead: Number of days to look ahead

    Returns:
        Formatted list of events.
    """
    # Implementation here
    return fetch_events(days_ahead)

@tool
def check_availability(date: str) -> str:
    """Check if a specific date is free."""
    return check_date(date)
```

**Key Points**:
- Files must be in `{workspace}/tools/*.py`
- Use LangChain's `@tool` decorator from `langchain_core.tools`
- Tools are merged with framework builtins (brave_search, cron, etc.)
- Environment variables from workspace `.env` are available
- Multiple tools per file are supported
- Files starting with `_` are ignored

**Dependencies**: Add a `tools/requirements.txt` for tool-specific packages:

```
# tools/requirements.txt
icalendar>=5.0.0
caldav>=1.0.0
```

Missing dependencies are auto-installed at workspace startup.

**Loading**: Tools are dynamically imported at workspace startup. The tool loader checks requirements.txt first, installs missing packages, then extracts all `BaseTool` instances from each Python file in the tools directory.

### Builtins System

OpenPaw provides optional built-in capabilities that are conditionally available based on API keys. Builtins come in two types:

**Tools** - LangChain-compatible tools the agent can invoke:
- `brave_search` - Web search via Brave API (requires `BRAVE_API_KEY`)
- `elevenlabs` - Text-to-speech for voice responses (requires `ELEVENLABS_API_KEY`)
- `cron` - Agent self-scheduling (no API key required, see "Dynamic Scheduling" section)
- `send_message` - Mid-execution messaging to keep users informed during long operations (no API key required)
- `followup` - Self-continuation for multi-step autonomous workflows with depth limiting (no API key required)
- `task_tracker` - Task management via TASKS.yaml for persistent cross-session work tracking (no API key required)
- `send_file` - Send workspace files to users (no API key required)

**Processors** - Channel-layer message transformers:
- `file_persistence` - Saves all uploaded files to workspace uploads/ directory (no API key required)
- `whisper` - Audio transcription for voice messages (requires `OPENAI_API_KEY`)
- `docling` - Document conversion (PDF, DOCX, PPTX, etc.) to markdown. Saves to `{workspace}/inbox/{date}/{filename}/`. Requires `docling` package.

**`openpaw/builtins/`** - Package structure:
```
builtins/
├── base.py           # BaseBuiltinTool, BaseBuiltinProcessor, BuiltinMetadata
├── registry.py       # Singleton registry of all builtins
├── loader.py         # Workspace-aware loading with allow/deny
├── tools/            # LangChain tool implementations
│   ├── brave_search.py
│   ├── elevenlabs_tts.py
│   ├── cron.py       # Agent self-scheduling
│   ├── _channel_context.py # Shared contextvars for channel/session state
│   ├── send_message.py  # Mid-execution messaging
│   ├── send_file.py     # Send workspace files to users
│   ├── followup.py      # Self-continuation with depth limiting
│   └── task.py          # TASKS.yaml CRUD operations
└── processors/       # Message preprocessors
    ├── whisper.py     # Audio transcription
    └── docling.py     # Document → markdown conversion
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

  file_persistence:
    enabled: true
    config:
      max_file_size: 52428800  # 50 MB default
      clear_data_after_save: false
```

**Adding New Builtins**: Create a class extending `BaseBuiltinTool` or `BaseBuiltinProcessor`, define `metadata` with prerequisites, and register in `registry.py`.

### Inbound File Handling

OpenPaw provides universal file persistence for all uploaded files, with optional content enrichment via downstream processors.

**Processor Pipeline Order**: `file_persistence` → `whisper` → `timestamp` → `docling`

**FilePersistenceProcessor** - First processor in the pipeline. Saves all uploaded files to `{workspace}/uploads/{YYYY-MM-DD}/` with date partitioning. Sets `attachment.saved_path` (relative to workspace root) so downstream processors can read from disk. Enriches message content with file receipt notifications:

```
[File received: report.pdf (2.3 MB, application/pdf)]
[Saved to: uploads/2026-02-07/report.pdf]
```

**Content Enrichment** - Downstream processors add content summaries as sibling files:

- **WhisperProcessor**: Transcribes audio/voice messages, saves transcript as `.txt` sibling to the audio file (e.g., `voice_123.ogg` → `voice_123.txt`)
- **DoclingProcessor**: Converts documents (PDF, DOCX, PPTX, etc.) to markdown, saves as `.md` sibling file (e.g., `report.pdf` → `report.md`)

**Agent View** - The agent receives the enriched message content with file metadata and any transcripts/conversions appended inline. Original files remain in `uploads/` for agent filesystem access.

**Configuration** - File persistence is enabled by default. Configure via `builtins.file_persistence`:

```yaml
builtins:
  file_persistence:
    enabled: true
    config:
      max_file_size: 52428800  # 50 MB default
      clear_data_after_save: false  # Free memory after saving
```

**Filename Handling** - `sanitize_filename()` normalizes filenames (lowercases, removes special chars, replaces spaces with underscores). `deduplicate_path()` appends counters (1), (2), etc. to prevent overwrites.

**Security** - All processors use `resolve_sandboxed_path()` for defense-in-depth path validation. Files cannot escape the workspace root.

### Framework Orientation Prompt

Agents automatically receive a dynamic system prompt section (`<framework>`) explaining the OpenPaw framework philosophy. Sections are conditionally included based on enabled builtins:
- **Always**: Workspace persistence, self-organization encouragement, conversation memory
- **Heartbeat System**: If HEARTBEAT.md has content — heartbeat protocol, HEARTBEAT_OK convention
- **Task Management**: If `task_tracker` enabled — TASKS.yaml usage, cross-session continuity
- **Self-Continuation**: If `followup` enabled — multi-step workflow chaining
- **Progress Updates**: If `send_message` enabled — mid-execution user communication
- **File Sharing**: If `send_file` enabled — sending workspace files to users
- **Self-Scheduling**: If `cron` enabled — future action scheduling

This explains HOW the agent exists in the framework (philosophy), not WHAT tools are available (LangChain handles that).

### Command System

Framework commands are handled by `CommandRouter` before messages reach the agent. Commands bypass the inbound processor pipeline to avoid content modification (e.g., `TimestampProcessor`) breaking detection.

**Built-in Commands**:
- `/start` - Welcome message (hidden from `/help`, for Telegram onboarding)
- `/new` - Archive current conversation and start fresh (bypasses queue)
- `/compact` - Summarize current conversation, archive it, start new with summary injected (bypasses queue)
- `/help` - List available commands with descriptions
- `/queue <mode>` - Change queue mode (`collect`, `steer`, `followup`, `interrupt`)
- `/status` - Show workspace info: model, conversation stats, active tasks, token usage (today + session)

**Adding Commands**: Extend `CommandHandler` ABC, implement `definition` property and `handle()` method, register in `get_framework_commands()`.

**Command Flow**: `Channel._handle_command()` → `WorkspaceRunner._handle_inbound_message()` → `CommandRouter.route()` → `CommandHandler.handle()` → `CommandResult`

### Channel Abstraction

Channels are created via the factory pattern in `openpaw/channels/factory.py`. `WorkspaceRunner` is fully decoupled from concrete channel types.

```python
# Adding a new channel provider:
# 1. Create adapter extending ChannelAdapter in openpaw/channels/
# 2. Register in create_channel() factory
# 3. Use channel type string in workspace config
```

Channels register bot commands (e.g., Telegram's command menu) via `register_commands()` using the command router's definition list. Channels also support `send_file(session_key, file_path, filename, caption)` for delivering files to users (used by `SendFileTool`).

### Conversation Persistence

Conversations persist across restarts via `AsyncSqliteSaver` (from `langgraph-checkpoint-sqlite`).

**Lifecycle**:
1. `WorkspaceRunner.start()` opens `aiosqlite` connection, creates `AsyncSqliteSaver`, calls `setup()`, rebuilds agent with checkpointer
2. Messages are routed with thread ID `"{session_key}:{conversation_id}"` (e.g., `telegram:123456:conv_2026-02-07T14-30-00-123456`)
3. `/new` and `/compact` rotate to new conversation IDs while archiving the old
4. `WorkspaceRunner.stop()` archives all active conversations, then closes the DB connection

**SessionManager**: Tracks which conversation each session is in. Thread-safe, persists to `.openpaw/sessions.json`. Conversation IDs use format `conv_{ISO_timestamp_with_microseconds}`.

**ConversationArchiver**: On `/new`, `/compact`, or shutdown, exports the conversation from the checkpointer to `memory/conversations/` as markdown + JSON. Agents can reference archived conversations for long-term context.

**Storage**: All framework state lives in `{workspace}/.openpaw/` (protected from agent filesystem access). Archives go to `{workspace}/memory/conversations/` (readable by agents).
