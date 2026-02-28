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

### Package Architecture

OpenPaw follows a layered architecture with clear separation of concerns:

```
openpaw/
├── cli.py            # CLI entry point
├── model/            # Pure business models (stable foundation)
│   ├── message.py    # Message, MessageAttachment
│   ├── task.py       # Task, TaskStatus
│   ├── session.py    # SessionState
│   ├── subagent.py   # SubAgentRequest, SubAgentStatus
│   └── cron.py       # DynamicCronTask (pure dataclass)
├── core/             # Configuration, logging, timezone, utilities
│   ├── config/       # Pydantic config models and loaders
│   │   ├── models.py         # WorkspaceConfig, GlobalConfig, CronDefinition, CronOutputConfig
│   │   ├── loader.py         # Config loading and merging
│   │   └── env_expansion.py  # ${VAR} substitution
│   ├── prompts/      # Centralized prompt text
│   │   ├── commands.py       # Command response templates
│   │   ├── framework.py      # Framework orientation sections
│   │   ├── heartbeat.py      # Heartbeat prompt template
│   │   ├── processors.py     # Processor notification text
│   │   └── system_events.py  # System event messages
│   ├── workspace.py  # AgentWorkspace dataclass (system prompt builder)
│   ├── logging.py    # Structured logging
│   ├── timezone.py   # Workspace timezone utilities
│   └── utils.py      # Generic utilities (sanitization, deduplication, user name resolution)
├── agent/            # Agent execution
│   ├── runner.py     # AgentRunner (LangGraph wrapper)
│   ├── metrics.py    # Token usage tracking
│   ├── session_logger.py  # Session logging for scheduled runs
│   ├── middleware/   # Tool middleware (queue-aware, approval, llm hooks)
│   └── tools/        # Filesystem tools and sandbox
│       ├── filesystem.py  # Sandboxed file operations
│       └── sandbox.py     # Path validation
├── workspace/        # Workspace management
│   ├── loader.py     # WorkspaceLoader: loads workspace files, returns AgentWorkspace
│   ├── runner.py     # WorkspaceRunner (slim orchestrator)
│   ├── message_processor.py  # Message processing loop
│   ├── agent_factory.py      # Agent creation with middleware
│   ├── lifecycle.py          # Startup/shutdown hooks
│   └── tool_loader.py        # Custom tool loading
├── runtime/          # Runtime services
│   ├── orchestrator.py       # OpenPawOrchestrator
│   ├── queue/        # Message queueing
│   │   ├── lane.py           # LaneQueue
│   │   └── manager.py        # QueueManager
│   ├── scheduling/   # Cron and heartbeat schedulers
│   │   ├── cron.py           # CronScheduler
│   │   ├── heartbeat.py      # HeartbeatScheduler
│   │   └── dynamic_cron.py   # DynamicCronStore
│   ├── approval.py   # ApprovalGateManager (in-memory state machine)
│   ├── session/      # Session management and archiving
│   │   ├── manager.py        # SessionManager
│   │   └── archiver.py       # ConversationArchiver
│   └── subagent/     # Background agent coordination
│       └── runner.py         # SubAgentRunner
├── stores/           # Persistence layer
│   ├── task.py       # TaskStore (TASKS.yaml)
│   ├── subagent.py   # SubAgentStore (subagents.yaml)
│   ├── cron.py       # DynamicCronStore (dynamic_crons.json)
│   └── vector/       # Semantic search infrastructure
├── channels/         # External communication
│   ├── factory.py    # Channel factory
│   ├── telegram.py   # Telegram adapter
│   └── commands/     # Slash command handlers
│       ├── router.py         # CommandRouter
│       └── handlers/         # Built-in commands (/new, /status, etc.)
└── builtins/         # Extensible capabilities
    ├── tools/        # Brave search, cron, spawn, browser, etc.
    └── processors/   # Whisper, docling, file persistence
```

**Stability Contract**: Code moves down the stack (agent → workspace → runtime → model), never up. Model classes are pure data, free of framework dependencies.

### Key Components

**`openpaw/cli.py`** - CLI entry point. Parses arguments, supports single workspace (`-w name`), multiple workspaces (`-w name1,name2`), or all workspaces (`--all` or `-w "*"`). Wraps startup with structured error handling: `FileNotFoundError`, `yaml.YAMLError`, `ValueError` (config/env validation), and generic exceptions produce clean stderr messages instead of tracebacks.

**`openpaw/runtime/orchestrator.py`** - `OpenPawOrchestrator` manages multiple `WorkspaceRunner` instances. Handles concurrent startup/shutdown and workspace discovery.

**`openpaw/workspace/runner.py`** - `WorkspaceRunner` manages a single workspace: loads workspace config, merges with global config, initializes queue system, sets up channels via factory, manages `AsyncSqliteSaver` lifecycle, wires command routing, schedules crons, and runs the message loop.

**`openpaw/workspace/message_processor.py`** - Core message processing loop. Handles queue modes (collect, steer, interrupt), invokes agent, manages approval gates, processes system events, and performs pre-run auto-compact checks. Agent errors are sanitized via `sanitize_error_for_user()` before sending to users — internal details never leak to channels.

**`openpaw/workspace/agent_factory.py`** - Agent creation with middleware wiring. Composes queue-aware and approval middleware, configures builtins, initializes checkpointer, and supports runtime model overrides via `RuntimeModelOverride`.

**`openpaw/workspace/lifecycle.py`** - Startup and shutdown hooks. Handles AsyncSqliteSaver initialization, tool requirements, cron/heartbeat scheduling, and graceful cleanup.

**`openpaw/agent/runner.py`** - `AgentRunner` wraps LangGraph's `create_react_agent()`. It stitches workspace markdown files into a system prompt via `init_chat_model()` for multi-provider support, configures sandboxed filesystem tools for workspace access, and tracks per-invocation token usage via `UsageMetadataCallbackHandler`. Supports `extra_model_kwargs` for OpenAI-compatible API endpoints (e.g., `base_url`).

**`openpaw/agent/metrics.py`** - Token usage tracking infrastructure. `InvocationMetrics` dataclass, `extract_metrics_from_callback()` for `UsageMetadataCallbackHandler`, `TokenUsageLogger` (thread-safe JSONL append to `.openpaw/token_usage.jsonl`), and `TokenUsageReader` for aggregation (today/session).

**`openpaw/core/config/models.py`** - Pydantic models for global and workspace configuration. Includes `CronDefinition` and `CronOutputConfig` (cron scheduling config with APScheduler dependency). Handles environment variable expansion (`${VAR}`) and deep-merging workspace config over global defaults.

**`openpaw/core/config/loader.py`** - Configuration loading and merging. Discovers workspace directories, loads global and per-workspace config, and performs deep merge.

**`openpaw/core/workspace.py`** - `AgentWorkspace` dataclass containing loaded workspace content (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md, crons, config). Builds the XML-tagged system prompt via `build_system_prompt()` with dynamic framework orientation sections.

**`openpaw/workspace/loader.py`** - `WorkspaceLoader` loads agent workspaces from `agent_workspaces/<name>/`. Returns an `AgentWorkspace` instance from `core/`. Each workspace requires: `AGENT.md`, `USER.md`, `SOUL.md`, `HEARTBEAT.md`. Optional `agent.yaml` and `crons/*.yaml` are loaded if present.

**`openpaw/workspace/tool_loader.py`** - Dynamically loads LangChain tools from workspace `tools/` directories. Imports Python files and extracts `@tool` decorated functions (BaseTool instances).

**`openpaw/runtime/queue/lane.py`** - Lane-based FIFO queue with configurable concurrency per lane (main, subagent, cron). Supports OpenClaw-style queue modes: `collect`, `steer`, `followup`, `interrupt`.

**`openpaw/runtime/queue/manager.py`** - `QueueManager` coordinates message routing across lanes. Manages debouncing, queue modes, and pending message tracking.

**`openpaw/agent/middleware/queue_aware.py`** - `QueueAwareToolMiddleware` wraps tool calls to inject pending messages (steer mode) or abort execution (interrupt mode) when users send new messages during agent runs. Provides responsive agent behavior via queue awareness.

**`openpaw/stores/subagent.py`** - `SubAgentStore` for YAML-based persistence of sub-agent requests and results at `.openpaw/subagents.yaml`. Thread-safe with status lifecycle tracking (pending → running → completed/failed/cancelled/timed_out).

**`openpaw/runtime/subagent/runner.py`** - `SubAgentRunner` manages spawned background agents with concurrency control (default: 8 concurrent). Creates fresh AgentRunner instances with filtered tools (no recursion, no unsolicited messaging).

**`openpaw/builtins/tools/spawn.py`** - `SpawnToolBuiltin` provides `spawn_agent`, `list_subagents`, `get_subagent_result`, `cancel_subagent` tools for concurrent task execution.

**`openpaw/runtime/approval.py`** - `ApprovalGateManager` state machine for pending approval requests. Manages lifecycle: create → wait → resolve → cleanup, with automatic timeout handling. Includes `ApprovalGatesConfig` Pydantic models.

**`openpaw/agent/middleware/approval.py`** - `ApprovalToolMiddleware` intercepts tool calls requiring user authorization. Raises `ApprovalRequiredError` to pause execution, sends UI to user, and resumes on approval.

**`openpaw/channels/telegram.py`** - Telegram bot adapter using `python-telegram-bot`. Converts platform messages to unified `Message` format, handles allowlisting, and supports voice/audio messages, documents, and photo uploads.

**`openpaw/channels/factory.py`** - Channel factory. Decouples `WorkspaceRunner` from concrete channel types via `create_channel(channel_type, config, workspace_name)`. Currently supports `telegram`; new providers register here.

**`openpaw/runtime/session/manager.py`** - `SessionManager` for tracking conversation threads per session. Thread-safe JSON persistence at `{workspace}/.openpaw/sessions.json`. Provides `get_thread_id()`, `new_conversation()`, `get_state()`, `increment_message_count()`.

**`openpaw/channels/commands/router.py`** - Framework command system. `CommandHandler` ABC + `CommandRouter` registry + `CommandContext` for runtime dependencies. Commands are routed BEFORE inbound processors to avoid content modification breaking `is_command` detection.

**`openpaw/channels/commands/handlers/`** - Built-in command handlers: `/start`, `/new`, `/compact`, `/help`, `/queue`, `/status`, `/model`. See "Command System" section.

**`openpaw/runtime/session/archiver.py`** - `ConversationArchiver` for exporting conversations from the LangGraph checkpointer. Produces dual-format output: markdown (human-readable) + JSON sidecar (machine-readable) at `{workspace}/memory/conversations/`.

**`openpaw/builtins/`** - Optional capabilities (tools and processors) conditionally loaded based on API key availability. See "Builtins System" section.

**`openpaw/builtins/tools/_channel_context.py`** - Shared `contextvars` module for session-safe channel/session state. Used by `send_message` and `send_file` to access the active channel and session key during tool execution.

**`openpaw/builtins/tools/send_message.py`** - Mid-execution messaging tool. Uses shared `_channel_context` for session-safe state. Lets agents push updates to users while continuing to work.

**`openpaw/builtins/tools/send_file.py`** - `SendFileTool` for sending workspace files to users via channel. Validates files within sandbox, infers MIME type, enforces 50MB limit. Uses shared `_channel_context`.

**`openpaw/builtins/tools/followup.py`** - Self-continuation tool. Agents request re-invocation after responding, enabling multi-step autonomous workflows with depth limiting.

**`openpaw/builtins/tools/task.py`** - Task management tools (`create_task`, `update_task`, `list_tasks`, `get_task`). CRUD over `TASKS.yaml` for tracking long-running operations across heartbeats.

**`openpaw/stores/task.py`** - `TaskStore` for YAML-based task persistence. Thread-safe with `_load_unlocked`/`_save_unlocked` pattern for atomic compound operations.

**`openpaw/agent/tools/filesystem.py`** - `FilesystemTools` providing sandboxed file operations: `ls`, `read_file`, `write_file`, `overwrite_file`, `edit_file`, `glob_files`, `grep_files`, `file_info`. Path traversal protection via `resolve_sandboxed_path()`. `read_file` has a 100K character safety valve. `grep_files` supports `context_lines` for surrounding context. Accepts optional `workspace_name` parameter to enrich tool descriptions, output headers, success messages, and error hints with workspace identity for agent spatial orientation.

**`openpaw/agent/tools/sandbox.py`** - Standalone `resolve_sandboxed_path()` utility. Validates paths within workspace root, rejecting absolute paths, `~`, `..`, and `.openpaw/` access. Shared by `FilesystemTools`, `SendFileTool`, and inbound processors (DoclingProcessor, WhisperProcessor).

**`openpaw/core/utils.py`** - Generic utilities. `sanitize_filename()` removes special characters, normalizes spaces, and lowercases. `deduplicate_path()` appends counters (1), (2), etc. for uniqueness. `resolve_user_name()` maps user IDs to display names via aliases/metadata. `sanitize_error_for_user()` maps exceptions to user-friendly messages (prevents internal details leaking to channels).

**`openpaw/builtins/processors/file_persistence.py`** - `FilePersistenceProcessor` saves all uploaded files to `uploads/{YYYY-MM-DD}/` with date partitioning. Sets `attachment.saved_path` for downstream processors.

**`openpaw/builtins/tools/browser.py`** - `BrowserToolBuiltin` provides Playwright-based web automation with accessibility tree navigation. Agents interact with pages via numeric element references instead of selectors. Lazy initialization creates browser instances per session, with lifecycle management tied to conversation resets and workspace shutdown.

**`openpaw/runtime/scheduling/cron.py`** - `CronScheduler` uses APScheduler to execute scheduled tasks. Each job builds a fresh agent instance, injects the cron prompt, and routes output to the configured channel. Also handles dynamic tasks from `CronTool`.

**`openpaw/runtime/scheduling/dynamic_cron.py`** - `DynamicCronStore` for persisting agent-scheduled tasks to workspace-local JSON. Includes `DynamicCronTask` dataclass and factory functions.

**`openpaw/runtime/scheduling/heartbeat.py`** - `HeartbeatScheduler` for proactive agent check-ins. Supports active hours, HEARTBEAT_OK suppression, configurable intervals, pre-flight skip (avoids LLM call when HEARTBEAT.md is empty and no active tasks), task summary injection into heartbeat prompt, and JSONL event logging with token metrics.

**`openpaw/core/prompts/`** - Centralized prompt text modules. Separates presentation layer from business logic. Includes `framework.py` (dynamic framework orientation sections), `heartbeat.py` (heartbeat prompt template), `processors.py` (file processor notification text), `commands.py` (command response templates), and `system_events.py` (system event messages).

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
│   ├── token_usage.jsonl # Token usage metrics (append-only)
│   └── subagents.yaml    # Sub-agent requests and results
├── uploads/      # User-uploaded files (from FilePersistenceProcessor)
│   └── {YYYY-MM-DD}/  # Date-partitioned file storage
│       ├── report.pdf        # Original uploaded file
│       ├── report.md         # Docling-converted markdown (sibling)
│       ├── voice_123.ogg     # Original audio file
│       └── voice_123.txt     # Whisper transcript (sibling)
├── downloads/    # Browser-downloaded files (from browser builtin)
├── screenshots/  # Browser screenshots (from browser_screenshot)
├── heartbeat_log.jsonl   # Heartbeat event log (outcomes, metrics, task counts)
├── memory/
│   ├── conversations/    # Archived conversation exports
│   │   ├── conv_*.md     # Markdown archives (human-readable)
│   │   └── conv_*.json   # JSON sidecars (machine-readable)
│   └── sessions/         # Scheduled agent session logs
│       ├── heartbeat/    # Heartbeat session JSONL files
│       ├── cron/         # Cron session JSONL files
│       └── subagent/     # Sub-agent session JSONL files
├── crons/        # Scheduled task definitions
│   └── *.yaml / *.yml    # Individual cron job configurations
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

# Shorthand format also accepted (auto-split on first colon):
# model: "anthropic:claude-sonnet-4-20250514"

channel:
  type: telegram
  token: ${TELEGRAM_BOT_TOKEN}
  allowed_users: []
  allowed_groups: []
  user_aliases:             # Map user IDs to display names (optional)
    123456789: "John"
    987654321: "Sarah"

queue:
  mode: collect
  debounce_ms: 1000
```

**Environment Variables**: Use `${VAR_NAME}` syntax for secrets and dynamic values. OpenPaw expands these from environment at load time. Unresolved `${VAR}` patterns cause a startup error naming the missing variable(s) and source file — set the variable or remove the reference.

**Config Merging**: Workspace settings deep-merge over global config. Missing fields inherit from global, present fields override.

**User Identity**: When `user_aliases` is configured, messages from multiple users are prefixed with `[Name]: ` so the agent can distinguish speakers. Falls back to Telegram `first_name` → `username` if a user is not in the aliases map. System messages and single-user workspaces without aliases are unaffected.

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

#### xAI (Grok) Configuration

OpenPaw supports xAI Grok models via the dedicated `langchain-xai` package (`ChatXAI`).

**Per-workspace (`agent.yaml`)**:

```yaml
model:
  provider: xai
  model: grok-3-mini
  api_key: ${XAI_API_KEY}
  temperature: 0.7
```

**Available xAI Models**:
- `grok-3` - Grok 3 (full reasoning)
- `grok-3-mini` - Grok 3 Mini (lightweight, fast)
- `grok-2-1212` - Grok 2

**Credentials**: Set `XAI_API_KEY` in environment or workspace `.env`.

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

**Components**: `InvocationMetrics` (dataclass), `TokenUsageLogger` (thread-safe JSONL writer), `TokenUsageReader` (aggregation). All in `openpaw/agent/metrics.py`.

**Integration**: `AgentRunner.run()` creates a `UsageMetadataCallbackHandler` per invocation. After completion, metrics are extracted via `extract_metrics_from_callback()` and exposed via `agent_runner.last_metrics`. `WorkspaceRunner` (message processor), `CronScheduler`, and `HeartbeatScheduler` pass the logger to record each invocation.

### Runtime Model Switching

The `/model` command enables live model switching without restarting the workspace or losing conversation history.

**Architecture**: `AgentFactory` manages a `RuntimeModelOverride` that takes precedence over the configured model. Overrides are ephemeral — lost on workspace restart. Stateless agents (cron, heartbeat, subagent) always use the configured model, ignoring any runtime override.

**Components**:
- `RuntimeModelOverride` dataclass (`model`, `temperature` fields) in `openpaw/workspace/agent_factory.py`
- `AgentFactory.validate_model()` — tests instantiation via `create_chat_model()` before mutating state
- `AgentFactory._resolve_api_key()` — maps provider to environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.)
- `AgentRunner.update_model()` — rebuilds the LangGraph agent with a new model while preserving checkpointer state
- `create_chat_model()` — standalone module-level function extracted from `AgentRunner._create_model()` for reuse

**Command Usage**:
- `/model` — Show active model (and configured model if overridden)
- `/model provider:model` — Validate and switch to a new model (e.g., `/model openai:gpt-4o`)
- `/model reset` — Revert to the configured model from agent.yaml

**API Key Resolution**: When switching providers at runtime, the factory resolves API keys from environment variables. Supported mappings: `anthropic` → `ANTHROPIC_API_KEY`, `openai` → `OPENAI_API_KEY`, `xai` → `XAI_API_KEY`, `bedrock_converse` → no key required (uses AWS credentials).

### Auto-Compact

Automatic conversation compaction when context window utilization exceeds a threshold. Fires as a pre-run check before each agent invocation — not middleware.

**Configuration** (in `agent.yaml` or global config):

```yaml
auto_compact:
  enabled: false          # Default off
  trigger: 0.8            # Fraction of context window (0.0-1.0)
  summary_model: null     # Model for summaries (null = use workspace model)
```

**Flow**: Before each agent run, `MessageProcessor._check_auto_compact()` calls `AgentRunner.get_context_info()` to check utilization. If over threshold: archive full transcript → generate summary via agent → rotate to new conversation → inject summary into new thread → notify user via channel.

**Context Info**: `AgentRunner.get_context_info(thread_id)` returns `max_input_tokens` (from `model.profile` or 200K fallback), `approximate_tokens` (via `count_tokens_approximately()`), `utilization` (float 0-1), and `message_count`. Uses LangGraph checkpoint state introspection.

**Graceful Degradation**: If auto-compact fails for any reason (checkpointer unavailable, archiver error), the error is logged and the agent run proceeds with the original thread.

### Lifecycle Notifications

Best-effort notifications to users on workspace lifecycle events.

**Configuration** (in `agent.yaml` or global config):

```yaml
lifecycle:
  notify_startup: false     # Default off
  notify_shutdown: true     # Default on
  notify_auto_compact: true # Default on
```

**Implementation**: `WorkspaceRunner._notify_lifecycle(event, detail)` sends to the first allowed user in each channel. Notifications are best-effort — failures are logged at debug level and do not affect workspace operation.

**Events**: Startup (after setup complete), shutdown (before channel teardown), auto-compact (when context rotation occurs).

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

**Cron File Format (`crons/<name>.yaml` or `crons/<name>.yml`)**:

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
  delivery: channel   # Where to deliver: channel, agent, or both (default: channel)
```

**Schedule Format**: Standard cron expression `"minute hour day-of-month month day-of-week"`
- `"0 9 * * *"` - Every day at 9:00 AM
- `"*/15 * * * *"` - Every 15 minutes
- `"0 0 * * 0"` - Every Sunday at midnight

**Note:** Cron schedule expressions fire in the workspace timezone.

**Execution**: CronScheduler builds a fresh agent instance (no checkpointer), injects the prompt, routes output based on delivery mode, and writes session logs to `memory/sessions/cron/`.

**Enable/Disable**: Set `enabled: false` to disable a cron without deleting the file.

**Delivery Modes**: The `delivery` field in `output` controls where cron results go:
- `channel` (default) — Send directly to the configured channel (existing behavior)
- `agent` — Inject into the main agent's message queue via `[SYSTEM]` event. The main agent receives the output with a reference to the full session log file.
- `both` — Send to channel AND inject into agent queue

**Session Logging**: Every cron execution writes a JSONL session log to `memory/sessions/cron/`. Each log contains the prompt, response, tools used, and token metrics. These files are readable by the main agent via `read_file()`.

**File Extensions**: Both `.yaml` and `.yml` extensions are supported for cron definition files.

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

### Web Browsing

Agents can interact with websites via Playwright-based browser automation. The browser builtin provides accessibility tree snapshots where elements are numbered, allowing agents to reference elements by numeric ID instead of writing CSS selectors.

**Available Tools**:
- `browser_navigate` - Navigate to a URL (respects domain allowlist/blocklist)
- `browser_snapshot` - Get current page state as numbered accessibility tree
- `browser_click` - Click an element by numeric reference
- `browser_type` - Type text into an input field by numeric reference
- `browser_select` - Select dropdown option by numeric reference
- `browser_scroll` - Scroll the page (up/down/top/bottom)
- `browser_back` - Navigate back in browser history
- `browser_screenshot` - Capture page screenshot (saved to `screenshots/`)
- `browser_close` - Close current page/tab
- `browser_tabs` - List all open tabs
- `browser_switch_tab` - Switch to a different tab by index

**Security Model**: Domain allowlist and blocklist prevent unauthorized navigation. If `allowed_domains` is non-empty, only those domains (and subdomains with `*.` prefix) are permitted. The `blocked_domains` list takes precedence and denies specific domains even if allowed by the allowlist.

**Lifecycle**: Browser instances are lazily initialized (no browser created until first use). Each session gets its own browser context. Browsers are automatically cleaned up on `/new`, `/compact`, and workspace shutdown.

**Cookie Persistence**: When `persist_cookies: true`, authentication state and cookies survive across agent runs within the same session. Cookies are cleared on conversation reset.

**Downloads**: Files downloaded by the browser are saved to `{workspace}/downloads/` with sanitized filenames. Agents can access downloaded files via filesystem tools.

**Screenshots**: Page screenshots are saved to `{workspace}/screenshots/` with sanitized filenames and returned as relative paths for agent reference.

**Configuration** (optional, in `agent.yaml` or global config):

```yaml
builtins:
  browser:
    enabled: true
    config:
      headless: true                # Run browser without GUI
      allowed_domains:              # Allowlist (empty = allow all)
        - "calendly.com"
        - "*.google.com"            # Subdomain wildcard
      blocked_domains: []           # Blocklist (takes precedence)
      timeout_seconds: 30           # Default timeout for operations
      persist_cookies: false        # Persist cookies across agent runs
      downloads_dir: "downloads"    # Where to save downloaded files
      screenshots_dir: "screenshots"  # Where to save screenshots
```

**Prerequisites**: Requires optional `playwright` package and browser installation:

```bash
poetry add playwright
poetry run playwright install chromium
```

**Example Usage** (by agent):
- User: "Book a meeting on my Calendly for tomorrow at 2pm"
- Agent calls `browser_navigate("https://calendly.com/myaccount")`
- Agent calls `browser_snapshot()` to see page elements
- Agent calls `browser_click(42)` to click the "Schedule" button (element #42)
- Agent fills in meeting details and confirms booking

### Sub-Agent Spawning

Agents can spawn background workers for concurrent task execution using the `spawn` builtin. Sub-agents run in isolated contexts with filtered tools to prevent recursion and unsolicited messaging.

**Available Tools**:
- `spawn_agent` - Spawn a background sub-agent with a task prompt and label
- `list_subagents` - List all sub-agents (active and recently completed)
- `get_subagent_result` - Retrieve result of a completed sub-agent by ID
- `cancel_subagent` - Cancel a running sub-agent

**Storage**: Sub-agent state persists to `{workspace}/.openpaw/subagents.yaml` and survives restarts. Completed/failed/cancelled requests older than 24 hours are automatically cleaned up on initialization.

**Tool Exclusions**: Sub-agents cannot spawn sub-agents (no `spawn_agent`), send unsolicited messages (no `send_message`/`send_file`), self-continue (no `request_followup`), or schedule tasks (no cron tools). This prevents recursion and ensures sub-agents are single-purpose workers.

**Lifecycle**: `pending` → `running` → `completed`/`failed`/`cancelled`/`timed_out`. Running sub-agents exceeding their timeout are marked as `timed_out` during cleanup.

**Notifications**: When `notify: true` (default), sub-agent completion results are injected into the message queue via `WorkspaceRunner._inject_system_event()` using `QueueMode.COLLECT`. This triggers a new agent turn where the main agent processes the `[SYSTEM]` notification and responds naturally. Notifications are truncated (500 chars) with a prompt to use `get_subagent_result` for full output. If no `result_callback` is configured, falls back to direct channel messaging.

**Session Logging**: Every sub-agent execution writes a JSONL session log to `memory/sessions/subagent/`, including prompt, response, tools used, and metrics. Logs are written for all outcomes (success, timeout, failure).

**Configuration** (optional, in `agent.yaml` or global config):

```yaml
builtins:
  spawn:
    enabled: true
    config:
      max_concurrent: 8  # Maximum simultaneous sub-agents (default: 8)
```

**Limits**: Maximum 8 concurrent sub-agents (configurable), timeout defaults to 30 minutes (1-120 range). Results are truncated at 50K characters to match `read_file` safety valve pattern.

**Example Usage** (by agent):
- User: "Research topic X in the background while I work on Y"
- Agent calls `spawn_agent(task="Research topic X...", label="research-x")`
- Sub-agent runs concurrently, agent continues working on Y
- When complete, user receives notification with result summary

### Queue-Aware Tool Middleware

`QueueAwareToolMiddleware` enables responsive agent behavior by checking for pending user messages during tool execution. The middleware composes with approval middleware in `create_agent(middleware=[queue_middleware, approval_middleware])`.

**Queue Modes**:

- **Collect mode** (default): No middleware behavior. Messages queue normally and are processed after the current run completes.
- **Steer mode**: When pending messages are detected during tool execution, remaining tools are skipped and pending messages are injected as the next agent input. The agent sees `[Skipped: user sent new message — redirecting]` for skipped tools and processes the new message context.
- **Interrupt mode**: When pending messages are detected, the current tool raises `InterruptSignalError`, the agent's response is discarded, and the new message is processed immediately. More aggressive than steer — aborts mid-run rather than redirecting.
- **Followup mode**: No middleware behavior (reserved for followup tool chaining).

**Implementation**: Middleware calls `queue_manager.peek_pending(session_key)` before each tool execution. `peek_pending()` checks both the session's pre-debounce buffer AND the lane queue (steer-mode messages bypass the session buffer). In steer mode, first detection triggers `queue_manager.consume_pending()` and stores messages for post-run injection. In interrupt mode, detection raises exception immediately.

**Post-Run Detection**: After the agent run completes, `_process_messages()` performs a final `peek_pending()` check to catch messages that arrived after the last tool call (or during tool-free runs). This ensures steer/interrupt responsiveness even when the middleware didn't fire.

**Integration**: `WorkspaceRunner` captures steer state before middleware reset via local variables. Interrupt exceptions are caught in `_process_messages()`, where pending messages become the new `combined_content` for re-entry into the processing loop.

### Approval Gates

Human-in-the-loop authorization for dangerous tools. When a gated tool is called, execution pauses while the user approves or denies via channel UI (e.g., Telegram inline keyboard).

**Configuration** (in `agent.yaml` or global config):

```yaml
approval_gates:
  enabled: true
  timeout_seconds: 120            # Seconds to wait for user response
  default_action: deny            # Action on timeout: "deny" or "approve"
  tools:
    overwrite_file:
      require_approval: true
      show_args: true             # Show tool arguments in approval prompt
    delete_task:
      require_approval: true
```

**Lifecycle**:
1. Middleware detects gated tool call → creates `PendingApproval`
2. Raises `ApprovalRequiredError` → `MessageProcessor` catches exception
3. Channel sends approval request with inline buttons (Approve/Deny)
4. User responds → `ApprovalGateManager.resolve()` called
5. `AgentRunner.resolve_orphaned_tool_calls()` injects synthetic `ToolMessage`s for the interrupted tool_calls (required because LangGraph checkpoints the `AIMessage(tool_calls=[...])` before the middleware raises)
6. On approval: agent re-runs with same message, middleware lets tool through via `check_recent_approval()` bypass
7. On denial: agent receives `[SYSTEM] The tool 'X' was denied by the user. Do not retry this action.`

**Timeout Behavior**: If user doesn't respond within `timeout_seconds`, `default_action` is applied automatically (`approve` or `deny`). This prevents agents from hanging indefinitely.

**Bypass Mechanism**: After approval, the middleware checks `check_recent_approval()` to allow tool execution without re-prompting. Approval is cleared after successful tool execution via `clear_recent_approval()`.

**Exclusions**: Cron and heartbeat agents (stateless, no checkpointer) do not have approval gates. Approval middleware is only active for main lane user-triggered runs.

**Channel Integration**: Channels implement `send_approval_request()` and register approval callbacks via `on_approval()`. Telegram uses inline keyboards; other channels can implement their own UI patterns.

### Heartbeat System

The HeartbeatScheduler enables proactive agent check-ins on a configurable schedule. Agents can use this to monitor ongoing tasks, provide status updates, or maintain context without user prompts.

**Configuration** (in `agent.yaml`):

```yaml
heartbeat:
  enabled: true
  interval_minutes: 30           # How often to check in
  active_hours: "09:00-17:00"    # Only run during these hours (optional)
  suppress_ok: true              # Don't send message if agent responds "HEARTBEAT_OK"
  delivery: channel              # Where to deliver: channel, agent, or both (default: channel)
  output:
    channel: telegram
    chat_id: 123456789
```

**HEARTBEAT_OK Protocol**: If the agent determines there's nothing to report, it can respond with exactly "HEARTBEAT_OK" and no message will be sent (when `suppress_ok: true`). This prevents noisy "all clear" messages.

**Active Hours**: Heartbeats only fire within the specified window (workspace timezone). Outside active hours, heartbeats are silently skipped. **Note:** `active_hours` are interpreted in the workspace timezone.

**Pre-flight Skip**: Before invoking the LLM, the scheduler checks HEARTBEAT.md and TASKS.yaml. If HEARTBEAT.md is empty/trivial and no active tasks exist, the heartbeat is skipped entirely — saving API costs for idle workspaces.

**Task Summary Injection**: When active tasks exist, a compact summary is injected into the heartbeat prompt as `<active_tasks>` XML tags. This avoids an extra LLM tool call to `list_tasks()`.

**Event Logging**: Every heartbeat event is logged to `{workspace}/heartbeat_log.jsonl` with outcome, duration, token metrics, and active task count.

**Delivery Modes**: The `delivery` field controls where heartbeat results go:
- `channel` (default) — Send directly to the configured channel (existing behavior)
- `agent` — Inject into the main agent's message queue as a `[SYSTEM]` event with a reference to the full session log
- `both` — Send to channel AND inject into agent queue

HEARTBEAT_OK responses are always suppressed from both channel delivery and agent injection, regardless of delivery mode.

**Session Logging**: Every heartbeat execution (including HEARTBEAT_OK and errors) writes a JSONL session log to `memory/sessions/heartbeat/`. These serve as an audit trail and are readable by the main agent via `read_file()`.

**Prompt Template**: The heartbeat prompt is built dynamically from a structured template. `HEARTBEAT.md` serves as a scratchpad for agent-maintained notes on what to check during heartbeats.

### Session Logging

Scheduled agent runs (heartbeat, cron, sub-agent) write JSONL session logs to `{workspace}/memory/sessions/{type}/`. Each run produces a file with three records: prompt, response, and metadata (tools used, token metrics, duration).

**File Format** (`memory/sessions/{type}/{name}_{timestamp}.jsonl`):
```jsonl
{"type": "prompt", "content": "Check Hacker News for AI stories...", "timestamp": "2026-02-22T08:15:00+00:00"}
{"type": "response", "content": "Here are today's top stories...", "timestamp": "2026-02-22T08:15:45+00:00"}
{"type": "metadata", "tools_used": ["brave_search"], "metrics": {"input_tokens": 1234, "output_tokens": 567, "total_tokens": 1801, "llm_calls": 3}, "duration_ms": 4500.0, "timestamp": "2026-02-22T08:15:45+00:00"}
```

**Storage**: `memory/sessions/heartbeat/`, `memory/sessions/cron/`, `memory/sessions/subagent/` — inside the workspace root where the main agent can `read_file()` them.

**Integration with Delivery Routing**: When `delivery` is set to `"agent"` or `"both"`, the injected `[SYSTEM]` message includes the session log path so the main agent can use `read_file()` to access the full session context. Output is truncated at 2000 characters in the injection message.

**Implementation**: `SessionLogger` in `openpaw/agent/session_logger.py`. Each scheduler creates its own instance (no shared state, no locking needed).

### Filesystem Access

Agents have sandboxed filesystem access to their workspace directory via `FilesystemTools` (`openpaw/agent/tools/filesystem.py`). Available operations: `ls`, `read_file`, `write_file`, `overwrite_file`, `edit_file`, `glob_files`, `grep_files`, `file_info`. Path traversal protection via `resolve_sandboxed_path()` in `openpaw/agent/tools/sandbox.py`.

- `file_info`: Lightweight metadata (size, line count, binary detection, read strategy hints) without reading content
- `grep_files`: Supports `context_lines` parameter for surrounding context (maps to ripgrep `-C`)
- `read_file`: 100K character safety valve prevents context window exhaustion on large files

Access is restricted to the workspace root — agents cannot read/write outside their directory. The `.openpaw/` directory is additionally protected; agents cannot read or write framework internals (checkpoint DB, session state, token logs). Agents are encouraged to organize their workspace (subdirectories, notes, state files) for continuity across conversations.

**Workspace Identity**: `FilesystemTools` accepts a `workspace_name` parameter (passed automatically by `AgentRunner`). When set, it enriches all tool interactions with workspace context:
- `ls` output is prefixed with `[Workspace: {name}] Contents of {path}/:`
- Tool descriptions are prefixed with `[{name} workspace]` so the LLM schema includes identity
- Write/overwrite success messages include `(workspace: {name})`
- Sandbox errors include hints with workspace name and example relative paths
- "Not found" errors suggest `ls('.')` to discover available files

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
- `spawn` - Sub-agent spawning for background tasks (no API key required, see "Sub-Agent Spawning" section)
- `plan` - Session-scoped planning tool for multi-step work externalization (no API key required)
- `browser` - Web automation via Playwright with accessibility tree navigation (requires `playwright` package, see "Web Browsing" section)

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
│   ├── spawn.py      # Sub-agent spawning (spawn_agent, list, get_result, cancel)
│   ├── browser.py    # Web automation with Playwright + accessibility tree
│   ├── _channel_context.py # Shared contextvars for channel/session state
│   ├── send_message.py  # Mid-execution messaging
│   ├── send_file.py     # Send workspace files to users
│   ├── followup.py      # Self-continuation with depth limiting
│   ├── task.py          # TASKS.yaml CRUD operations
│   └── plan.py          # Session-scoped planning (write_plan, read_plan)
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

Agents automatically receive a dynamic system prompt section (`<framework>`) explaining the OpenPaw framework philosophy, followed by a `<workspace_context>` block providing spatial orientation. Sections are conditionally included based on enabled builtins:
- **Always**: Workspace identity (name injected via `build_framework_orientation()`), workspace filesystem guidance, conversation memory
- **Always**: `<workspace_context>` block with workspace name and live top-level directory listing
- **Workspace Filesystem**: Always included — explains sandbox model, relative paths, `ls('.')` discovery
- **Heartbeat System**: If HEARTBEAT.md has content — heartbeat protocol, HEARTBEAT_OK convention
- **Task Management**: If `task_tracker` enabled — TASKS.yaml usage, cross-session continuity
- **Self-Continuation**: If `followup` enabled — completion rule self-check, multi-step workflow chaining
- **Progress Updates**: If `send_message` enabled — mid-execution user communication (not final answer)
- **File Sharing**: If `send_file` enabled — sending workspace files to users
- **Self-Scheduling**: If `cron` enabled — future action scheduling
- **Operational Work Ethic**: If `shell` enabled — 5-step ops cycle (diagnose, plan, execute, verify, report)
- **Planning**: If `plan` enabled — session-scoped task planning for multi-step work
- **Autonomous Planning**: If 2+ key capabilities enabled — full task lifecycle, "do not stop after diagnosis"

This explains HOW the agent exists in the framework (philosophy), not WHAT tools are available (LangChain handles that).

### Command System

Framework commands are handled by `CommandRouter` before messages reach the agent. Commands bypass the inbound processor pipeline to avoid content modification (e.g., `TimestampProcessor`) breaking detection.

**Built-in Commands**:
- `/start` - Welcome message (hidden from `/help`, for Telegram onboarding)
- `/new` - Archive current conversation and start fresh (bypasses queue)
- `/compact` - Summarize current conversation, archive it, start new with summary injected (bypasses queue)
- `/help` - List available commands with descriptions
- `/queue <mode>` - Change queue mode (`collect`, `steer`, `followup`, `interrupt`)
- `/status` - Show workspace info: model, context utilization, conversation stats, active tasks/subagents, token usage (today + session)
- `/model [provider:model | reset]` - Show or switch the active LLM model at runtime (ephemeral, lost on restart)

**Adding Commands**: Extend `CommandHandler` ABC, implement `definition` property and `handle()` method, register in `get_framework_commands()`.

**Command Flow**: `Channel._handle_command()` → `WorkspaceRunner._handle_inbound_message()` → `CommandRouter.route()` (from `openpaw/channels/commands/router.py`) → `CommandHandler.handle()` → `CommandResult`

### Channel Abstraction

Channels are created via the factory pattern in `openpaw/channels/factory.py`. `WorkspaceRunner` is fully decoupled from concrete channel types.

```python
# Adding a new channel provider:
# 1. Create adapter extending ChannelAdapter in openpaw/channels/
# 2. Register in create_channel() factory in openpaw/channels/factory.py
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
