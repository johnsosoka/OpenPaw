# Architecture

OpenPaw is a multi-workspace AI agent framework built on [LangGraph](https://langchain-ai.github.io/langgraph/) (`create_react_agent`) and [LangChain](https://www.langchain.com/). This document describes the system design, component interactions, and architectural decisions.

<div align="center">
  <img src="../assets/images/features.png" alt="OpenPaw Architecture Overview" width="650">
</div>

## System Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    OpenPawOrchestrator                       │
│                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐ │
│  │ WorkspaceRunner│  │ WorkspaceRunner│  │ WorkspaceRunner│ │
│  │   "gilfoyle"   │  │  "assistant"   │  │  "scheduler"   │ │
│  │                │  │                │  │                │ │
│  │ Channel        │  │ Channel        │  │ Channel        │ │
│  │   ↓            │  │   ↓            │  │   ↓            │ │
│  │ QueueManager   │  │ QueueManager   │  │ QueueManager   │ │
│  │   ↓            │  │   ↓            │  │   ↓            │ │
│  │ Middleware     │  │ Middleware     │  │ Middleware     │ │
│  │   ↓            │  │   ↓            │  │   ↓            │ │
│  │ AgentRunner    │  │ AgentRunner    │  │ AgentRunner    │ │
│  │   ↓            │  │   ↓            │  │   ↓            │ │
│  │ LangGraph      │  │ LangGraph      │  │ LangGraph      │ │
│  └────────────────┘  └────────────────┘  └────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

Each `WorkspaceRunner` is an isolated agent with its own:
- Communication channel (Telegram, etc.)
- Message queue and lane-based concurrency controls
- Agent instance with LangGraph ReAct loop
- Conversation persistence (AsyncSqliteSaver)
- Scheduled tasks (cron and heartbeat)
- Sandboxed filesystem
- Session state and conversation archiving

## Package Architecture

OpenPaw follows a **layered architecture** with clear separation of concerns. The **stability contract** is: code moves down the stack (agent → workspace → runtime → domain), never up. Domain models are pure data, free of framework dependencies.

```
openpaw/
├── domain/           # Pure business models (stable foundation)
│   ├── message.py    # Message, MessageAttachment
│   ├── task.py       # Task, TaskStatus
│   ├── session.py    # SessionState
│   ├── subagent.py   # SubAgentRequest, SubAgentStatus
│   └── cron.py       # CronJobDefinition, DynamicCronTask
├── core/             # Configuration, logging, timezone, queue
│   ├── config/       # Pydantic config models and loaders
│   │   ├── models.py         # WorkspaceConfig, GlobalConfig
│   │   ├── loader.py         # Config loading and merging
│   │   └── env_expansion.py  # ${VAR} substitution
│   ├── logging.py    # Structured logging
│   ├── timezone.py   # Workspace timezone utilities
│   └── queue/        # Message queueing
│       ├── lane.py           # LaneQueue (FIFO with concurrency limits)
│       └── manager.py        # QueueManager (routing across lanes)
├── agent/            # Agent execution
│   ├── runner.py     # AgentRunner (LangGraph wrapper)
│   ├── metrics.py    # Token usage tracking (InvocationMetrics, TokenUsageLogger)
│   ├── middleware/   # Tool middleware (queue-aware, approval)
│   │   ├── queue_aware.py    # QueueAwareToolMiddleware
│   │   └── approval.py       # ApprovalToolMiddleware
│   └── tools/        # Filesystem tools and sandbox
│       ├── filesystem.py  # Sandboxed file operations
│       └── sandbox.py     # resolve_sandboxed_path() utility
├── workspace/        # Workspace management
│   ├── loader.py     # Load AGENT.md, USER.md, SOUL.md, HEARTBEAT.md
│   ├── runner.py     # WorkspaceRunner (workspace orchestrator)
│   ├── message_processor.py  # Message processing loop
│   ├── agent_factory.py      # Agent creation with middleware
│   ├── lifecycle.py          # Startup/shutdown hooks
│   └── tool_loader.py        # Custom tool loading from workspace tools/
├── runtime/          # Runtime services
│   ├── orchestrator.py       # OpenPawOrchestrator (multi-workspace manager)
│   ├── scheduling/   # Cron and heartbeat schedulers
│   │   ├── cron.py           # CronScheduler (APScheduler wrapper)
│   │   ├── heartbeat.py      # HeartbeatScheduler (proactive check-ins)
│   │   └── dynamic_cron.py   # DynamicCronStore (agent-scheduled tasks)
│   └── session/      # Session management and archiving
│       ├── manager.py        # SessionManager (thread tracking)
│       └── archiver.py       # ConversationArchiver (markdown + JSON export)
├── stores/           # Persistence layer
│   ├── task.py       # TaskStore (TASKS.yaml persistence)
│   ├── subagent.py   # SubAgentStore (subagents.yaml persistence)
│   ├── cron.py       # DynamicCronStore (dynamic_crons.json)
│   └── approval.py   # ApprovalGateManager (in-memory state machine)
├── channels/         # External communication
│   ├── factory.py    # Channel factory (create_channel)
│   ├── telegram.py   # Telegram adapter (python-telegram-bot)
│   └── commands/     # Slash command handlers
│       ├── router.py         # CommandRouter (command dispatch)
│       └── handlers/         # Built-in commands (/new, /status, etc.)
├── builtins/         # Extensible capabilities
│   ├── base.py       # BaseBuiltinTool, BaseBuiltinProcessor
│   ├── registry.py   # Singleton registry of all builtins
│   ├── loader.py     # Workspace-aware loading with allow/deny
│   ├── tools/        # LangChain tool implementations
│   │   ├── brave_search.py   # Web search
│   │   ├── browser.py        # Playwright web automation
│   │   ├── spawn.py          # Sub-agent spawning
│   │   ├── cron.py           # Agent self-scheduling
│   │   ├── task.py           # Task management (TASKS.yaml CRUD)
│   │   ├── send_message.py   # Mid-execution messaging
│   │   ├── send_file.py      # Send workspace files to users
│   │   ├── followup.py       # Self-continuation
│   │   ├── elevenlabs_tts.py # Text-to-speech
│   │   └── _channel_context.py # Shared contextvars
│   └── processors/   # Message transformers
│       ├── file_persistence.py # Universal file upload handling
│       ├── whisper.py          # Audio transcription
│       └── docling.py          # Document → markdown conversion
├── subagent/         # Background agent coordination
│   └── runner.py     # SubAgentRunner (lifecycle and concurrency)
└── utils/            # Generic utilities
    └── filename.py   # Sanitization and deduplication
```

## Core Components

### CLI (`openpaw/cli.py`)

Command-line entry point. Parses arguments and delegates to the orchestrator.

**Supported invocation patterns:**

```bash
# Single workspace
poetry run openpaw -c config.yaml -w gilfoyle

# Multiple workspaces
poetry run openpaw -c config.yaml -w gilfoyle,assistant

# All workspaces
poetry run openpaw -c config.yaml --all
poetry run openpaw -c config.yaml -w "*"

# Verbose logging
poetry run openpaw -c config.yaml -w gilfoyle -v
```

### OpenPawOrchestrator (`openpaw/runtime/orchestrator.py`)

Manages multiple `WorkspaceRunner` instances concurrently.

**Responsibilities:**
- Discover workspaces from `workspaces_path`
- Launch requested workspace runners as asyncio tasks
- Handle graceful shutdown across all workspaces
- Coordinate startup/shutdown sequencing

**Startup flow:**
```python
orchestrator = OpenPawOrchestrator(config)
await orchestrator.run(workspace_names=["gilfoyle", "assistant"])
```

### WorkspaceRunner (`openpaw/workspace/runner.py`)

Manages a single workspace from start to shutdown.

**Responsibilities:**
- Load workspace files (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
- Merge workspace config over global config (deep merge)
- Initialize channel adapter via factory pattern
- Create queue manager with lane configuration
- Set up `AsyncSqliteSaver` for conversation persistence
- Wire command routing and slash command handlers
- Load and configure builtins (tools and processors)
- Schedule static cron jobs and heartbeat (if enabled)
- Run message processing loop via `message_processor.py`
- Clean up on shutdown (archive conversations, close DB, close browser sessions)

**Lifecycle:**
```
Load workspace → Merge config → Init channel → Setup queue →
Load builtins → Schedule crons → Initialize checkpointer →
Start message loop → (run) → Shutdown hooks → Archive conversations
```

### Message Processor (`openpaw/workspace/message_processor.py`)

Core message processing loop. Handles queue modes, agent invocation, and system events.

**Responsibilities:**
- Dequeue messages from lanes (main, subagent, cron)
- Handle queue modes (collect, steer, interrupt, followup)
- Invoke agent via `AgentRunner.run()`
- Manage approval gates (catch `ApprovalRequiredError`, send UI, await response)
- Handle interrupt signals (abort run on new message)
- Inject steer-mode messages after agent run
- Process system events (sub-agent completion notifications)
- Track followup depth and enforce limits

**Queue mode behaviors:**
- **Collect mode** (default): Debounce messages briefly, process in batch
- **Steer mode**: Inject pending messages mid-run to redirect agent
- **Interrupt mode**: Abort agent run immediately when new message arrives
- **Followup mode**: Support self-continuation via `request_followup` tool

### Agent Factory (`openpaw/workspace/agent_factory.py`)

Creates agent instances with middleware composition.

**Responsibilities:**
- Build `AgentRunner` with workspace system prompt
- Compose middleware stack: `[QueueAwareToolMiddleware, ApprovalToolMiddleware]`
- Configure builtins (tools and processors)
- Initialize checkpointer (`AsyncSqliteSaver`)
- Filter tools for sub-agents (exclude `spawn_agent`, `send_message`, etc.)

**Middleware ordering matters:** Queue-aware middleware must fire before approval middleware to ensure responsiveness.

### AgentRunner (`openpaw/agent/runner.py`)

Wraps LangGraph's `create_react_agent()` from `langchain.agents`.

**Responsibilities:**
- Stitch workspace markdown files into system prompt (XML-tagged sections)
- Use `init_chat_model()` for multi-provider support (Anthropic, OpenAI, Bedrock)
- Configure sandboxed filesystem tools for workspace access
- Track per-invocation token usage via `UsageMetadataCallbackHandler`
- Support `extra_model_kwargs` for OpenAI-compatible endpoints (e.g., `base_url`)
- Expose `last_metrics` for token tracking

**System prompt structure:**
```xml
<agent>
[Content of AGENT.md]
</agent>

<user>
[Content of USER.md]
</user>

<soul>
[Content of SOUL.md]
</soul>

<heartbeat>
[Content of HEARTBEAT.md]
</heartbeat>

<framework>
[Dynamic framework orientation: workspace persistence, builtins, heartbeat protocol]
</framework>
```

### Configuration System (`openpaw/core/config/`)

Pydantic-based configuration with deep merging and environment variable expansion.

**Components:**
- **`models.py`** - `WorkspaceConfig`, `GlobalConfig`, Pydantic validation
- **`loader.py`** - Configuration loading, workspace discovery, deep merge
- **`env_expansion.py`** - `${VAR}` environment variable substitution

**Hierarchy:**
```
Global config.yaml
  ↓ (deep merge)
Workspace agent.yaml
  ↓ (expand ${VAR})
Effective workspace configuration
```

**Workspace config example:**
```yaml
name: Gilfoyle
timezone: America/Denver  # IANA timezone identifier

model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.5

channel:
  type: telegram
  token: ${TELEGRAM_BOT_TOKEN}
  allowed_users: [123456789]
```

### Workspace Loader (`openpaw/workspace/loader.py`)

Loads workspace personality and configuration from disk.

**Responsibilities:**
- Locate workspace directory at `{workspaces_path}/{name}/`
- Read required markdown files (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
- Load optional `agent.yaml` and `crons/*.yaml`
- Discover `tools/` directory for custom LangChain tools
- Combine markdown files into XML-tagged system prompt

**Output format:** System prompt with `<agent>`, `<user>`, `<soul>`, `<heartbeat>` sections.

### Tool Loader (`openpaw/workspace/tool_loader.py`)

Dynamically loads LangChain tools from workspace `tools/` directories.

**Responsibilities:**
- Check `tools/requirements.txt` and auto-install missing packages
- Import Python files from `tools/*.py`
- Extract `@tool` decorated functions (`BaseTool` instances)
- Merge with framework builtins
- Skip files starting with `_`

**Example tool:**
```python
# agent_workspaces/my-agent/tools/weather.py
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get current weather for a city."""
    return fetch_weather_api(city)
```

### Queue System (`openpaw/runtime/queue/`)

Lane-based FIFO queue with configurable concurrency per lane.

**Components:**
- **`lane.py`** - `LaneQueue` with FIFO semantics and concurrency limits
- **`manager.py`** - `QueueManager` coordinates message routing across lanes

**Architecture:**
```
QueueManager
  ├─ main_lane (concurrency: 4)        # Interactive user messages
  ├─ subagent_lane (concurrency: 8)    # Spawned sub-agent tasks
  └─ cron_lane (concurrency: 2)        # Scheduled jobs
```

**Queue modes:**
- **Collect mode** - Debounce messages, process after delay
- **Steer mode** - Redirect agent mid-run when new messages arrive
- **Interrupt mode** - Abort agent run immediately on new message
- **Followup mode** - Support self-continuation workflows

See [queue-system.md](queue-system.md) for detailed behavior.

### Queue-Aware Middleware (`openpaw/agent/middleware/queue_aware.py`)

Tool middleware that enables responsive agent behavior.

**Responsibilities:**
- Check for pending messages before each tool execution via `queue_manager.peek_pending()`
- In **steer mode**: Skip remaining tools, inject pending messages as next input
- In **interrupt mode**: Raise `InterruptSignalError` to abort run immediately
- Post-run detection: Final `peek_pending()` check catches late-arriving messages

**Implementation:**
```python
# Middleware calls queue_manager.peek_pending(session_key)
# - Checks session's pre-debounce buffer
# - Checks lane queue (steer-mode messages bypass session buffer)
```

### Approval Middleware (`openpaw/agent/middleware/approval.py`)

Human-in-the-loop authorization for dangerous tools.

**Responsibilities:**
- Intercept tool calls requiring approval (e.g., `overwrite_file`)
- Raise `ApprovalRequiredError` to pause execution
- Create `PendingApproval` in `ApprovalGateManager`
- Send approval request UI to user (Telegram inline keyboard)
- Resume or deny based on user response

**Configuration example:**
```yaml
approval_gates:
  enabled: true
  timeout_seconds: 120
  default_action: deny  # or "approve"
  tools:
    overwrite_file:
      require_approval: true
      show_args: true
```

**Lifecycle:**
1. Middleware detects gated tool → creates `PendingApproval`
2. Raises `ApprovalRequiredError` → `WorkspaceRunner` catches
3. Channel sends approval request with inline buttons
4. User responds → `ApprovalGateManager.resolve()` called
5. On approval: agent re-runs, middleware bypasses check
6. On denial: agent receives `[SYSTEM]` message about denial

### Channel System (`openpaw/channels/`)

Platform adapters for external communication.

**Components:**
- **`factory.py`** - `create_channel()` factory decouples `WorkspaceRunner` from concrete types
- **`telegram.py`** - Telegram bot adapter using `python-telegram-bot`
- **`commands/`** - Slash command routing and handlers

**Base interface:**
```python
class ChannelAdapter:
    async def start()                     # Initialize platform connection
    async def stop()                      # Shutdown
    async def send_message(session_key, content)  # Send to platform
    async def send_file(session_key, path, filename, caption)  # File delivery
    async def send_approval_request(session_key, request)  # Approval UI
    def on_approval(callback)             # Register approval handler
    def register_commands(definitions)    # Register bot commands (e.g., Telegram menu)
```

**Telegram features:**
- Allowlist support (`allowed_users`, `allowed_groups`)
- Voice/audio message handling (delegates to WhisperProcessor)
- Document upload handling (delegates to DoclingProcessor)
- Photo upload handling
- Inline keyboard support (approval gates)

### Command System (`openpaw/channels/commands/`)

Framework commands are handled by `CommandRouter` **before** messages reach the agent.

**Why before the agent?** Commands bypass the inbound processor pipeline to avoid content modification (e.g., `TimestampProcessor` prepending text) breaking `is_command` detection.

**Built-in commands:**
- `/start` - Welcome message (hidden from `/help`, Telegram onboarding)
- `/new` - Archive current conversation, start fresh (bypasses queue)
- `/compact` - Summarize conversation, archive, start new with summary
- `/help` - List available commands
- `/queue <mode>` - Change queue mode (`collect`, `steer`, `interrupt`, `followup`)
- `/status` - Show model, conversation stats, active tasks, token usage (today + session)

**Command flow:**
```
Channel._handle_command() →
  WorkspaceRunner._handle_inbound_message() →
    CommandRouter.route() →
      CommandHandler.handle() →
        CommandResult
```

### Conversation Persistence (`openpaw/runtime/session/`)

Conversations persist across restarts via `AsyncSqliteSaver` (from `langgraph-checkpoint-sqlite`).

**Components:**
- **`manager.py`** - `SessionManager` tracks conversation threads per session
- **`archiver.py`** - `ConversationArchiver` exports conversations to markdown + JSON

**Lifecycle:**
1. `WorkspaceRunner.start()` opens `aiosqlite` connection, creates `AsyncSqliteSaver`, calls `setup()`
2. Messages are routed with thread ID `"{session_key}:{conversation_id}"` (e.g., `telegram:123456:conv_2026-02-07T14-30-00-123456`)
3. `/new` and `/compact` rotate to new conversation IDs while archiving the old
4. `WorkspaceRunner.stop()` archives all active conversations, then closes DB connection

**Session key format:** `"{channel}:{id}"` (e.g., `telegram:123456` for DMs, `telegram:-1001234567890` for groups)

**Conversation ID format:** `conv_{ISO_timestamp_with_microseconds}` (e.g., `conv_2026-02-07T14-30-00-123456`)

**Storage locations:**
- Framework internals: `{workspace}/.openpaw/` (protected from agent access)
  - `conversations.db` - AsyncSqliteSaver checkpoint database
  - `sessions.json` - Session/thread state
  - `token_usage.jsonl` - Token metrics
  - `subagents.yaml` - Sub-agent requests/results
- Agent-readable: `{workspace}/memory/conversations/`
  - `conv_*.md` - Markdown archives (human-readable)
  - `conv_*.json` - JSON sidecars (machine-readable)

### Cron Scheduler (`openpaw/runtime/scheduling/cron.py`)

Scheduled task execution using APScheduler.

**Responsibilities:**
- Load static cron job definitions from `{workspace}/crons/*.yaml`
- Load dynamic agent-scheduled tasks from `dynamic_crons.json`
- Parse cron expressions (standard format: `"minute hour day month weekday"`)
- Schedule jobs with APScheduler `CronTrigger` (workspace timezone)
- Build fresh agent instance per execution (no checkpointer, stateless)
- Inject cron prompt into system prompt
- Route output to configured channel

**Cron file format:**
```yaml
name: daily-summary
schedule: "0 9 * * *"  # Every day at 9:00 AM (workspace timezone)
enabled: true

prompt: |
  Generate a daily summary of system status and pending tasks.

output:
  channel: telegram
  chat_id: 123456789
```

**Execution model:** Each cron run is independent with no conversation history.

### Dynamic Scheduling (`openpaw/runtime/scheduling/dynamic_cron.py`)

Agents can schedule their own follow-up actions at runtime using the CronTool builtin.

**Components:**
- **`dynamic_cron.py`** - `DynamicCronStore` for persisting agent-scheduled tasks to `{workspace}/dynamic_crons.json`

**Available tools (from `openpaw/builtins/tools/cron.py`):**
- `schedule_at` - One-time action at specific timestamp
- `schedule_every` - Recurring action at fixed intervals
- `list_scheduled` - List pending scheduled tasks
- `cancel_scheduled` - Cancel task by ID

**Storage:** Tasks persist to `dynamic_crons.json` and survive restarts. One-time tasks auto-cleanup after execution or if expired on startup.

### Heartbeat Scheduler (`openpaw/runtime/scheduling/heartbeat.py`)

Proactive agent check-ins on a configurable schedule.

**Responsibilities:**
- Schedule periodic agent invocations (e.g., every 30 minutes)
- Respect active hours window (workspace timezone)
- Pre-flight skip: Avoid LLM call if HEARTBEAT.md is empty and no active tasks
- Inject task summary into heartbeat prompt (avoids extra `list_tasks()` call)
- Suppress output if agent responds "HEARTBEAT_OK" (when `suppress_ok: true`)
- Log events to `{workspace}/heartbeat_log.jsonl` with outcome, duration, token metrics

**Configuration:**
```yaml
heartbeat:
  enabled: true
  interval_minutes: 30
  active_hours: "09:00-17:00"  # Workspace timezone
  suppress_ok: true
  output:
    channel: telegram
    chat_id: 123456789
```

**HEARTBEAT_OK protocol:** If agent determines there's nothing to report, it responds with exactly "HEARTBEAT_OK" and no message is sent.

### Builtins System (`openpaw/builtins/`)

Optional capabilities conditionally loaded based on prerequisites (API keys, packages).

**Components:**
- **`base.py`** - `BaseBuiltinTool`, `BaseBuiltinProcessor`, `BuiltinMetadata`
- **`registry.py`** - Singleton registry of all builtins
- **`loader.py`** - Workspace-aware loading with allow/deny filtering

**Builtins types:**
- **Tools** - LangChain-compatible tools the agent can invoke
- **Processors** - Channel-layer message transformers (run before agent sees message)

**Current builtins:**

| Builtin | Type | Requires | Description |
|---------|------|----------|-------------|
| `browser` | Tool | `playwright` | Web automation via Playwright + accessibility tree |
| `brave_search` | Tool | `BRAVE_API_KEY` | Web search |
| `spawn` | Tool | — | Sub-agent spawning |
| `cron` | Tool | — | Agent self-scheduling |
| `task_tracker` | Tool | — | TASKS.yaml CRUD |
| `send_message` | Tool | — | Mid-execution messaging |
| `send_file` | Tool | — | Send workspace files to users |
| `followup` | Tool | — | Self-continuation |
| `elevenlabs` | Tool | `ELEVENLABS_API_KEY` | Text-to-speech |
| `file_persistence` | Processor | — | Universal file upload handling |
| `docling` | Processor | `docling` | PDF/DOCX/PPTX → markdown with OCR |
| `whisper` | Processor | `OPENAI_API_KEY` | Audio transcription |

**Configuration example:**
```yaml
builtins:
  allow: []  # Empty = allow all available
  deny:
    - group:voice  # Deny entire groups

  browser:
    enabled: true
    config:
      headless: true
      allowed_domains: ["calendly.com", "*.google.com"]
```

See [builtins.md](builtins.md) for detailed reference.

### Sub-Agent Spawning (`openpaw/subagent/`)

Agents can spawn background workers for concurrent task execution.

**Components:**
- **`runner.py`** - `SubAgentRunner` manages spawned agents with concurrency control
- **`openpaw/stores/subagent.py`** - `SubAgentStore` for YAML-based persistence
- **`openpaw/builtins/tools/spawn.py`** - `SpawnToolBuiltin` provides spawn tools

**Available tools:**
- `spawn_agent` - Spawn background sub-agent with task prompt and label
- `list_subagents` - List active and recently completed sub-agents
- `get_subagent_result` - Retrieve result by ID
- `cancel_subagent` - Cancel running sub-agent

**Tool exclusions:** Sub-agents cannot spawn sub-agents, send unsolicited messages, self-continue, or schedule tasks. This prevents recursion and ensures sub-agents are single-purpose workers.

**Lifecycle:** `pending` → `running` → `completed`/`failed`/`cancelled`/`timed_out`

**Notifications:** When `notify: true` (default), completion results are injected into the message queue as `[SYSTEM]` events, triggering a new agent turn.

**Storage:** State persists to `.openpaw/subagents.yaml`. Completed requests older than 24 hours auto-cleanup.

### Token Usage Tracking (`openpaw/agent/metrics.py`)

Every agent invocation logs token counts to `{workspace}/.openpaw/token_usage.jsonl`.

**Components:**
- **`InvocationMetrics`** - Dataclass for input/output token counts
- **`TokenUsageLogger`** - Thread-safe JSONL writer
- **`TokenUsageReader`** - Aggregation (today/session)

**Integration:**
- `AgentRunner.run()` creates `UsageMetadataCallbackHandler` per invocation
- Metrics extracted via `extract_metrics_from_callback()` after completion
- Exposed via `agent_runner.last_metrics`
- `WorkspaceRunner`, `CronScheduler`, `HeartbeatScheduler` pass logger to record each invocation

**Usage:** The `/status` command displays tokens today (workspace timezone day boundary) and tokens this session.

### Timezone Handling (`openpaw/core/timezone.py`)

OpenPaw uses a "store in UTC, display in workspace timezone" pattern.

**What uses workspace timezone:**
- Heartbeat active hours (`active_hours: "09:00-17:00"`)
- Cron schedule expressions (APScheduler `CronTrigger`)
- Agent-scheduled tasks (`schedule_at` timestamp parsing)
- File upload date partitions (`uploads/{YYYY-MM-DD}/`)
- `/status` "tokens today" day boundary
- Display timestamps (conversation archives, task notes, filesystem listings)

**What remains UTC (internal storage):**
- JSONL logs (`token_usage.jsonl`, `heartbeat_log.jsonl`)
- Session state (`sessions.json`)
- Task timestamps (`created_at`, `started_at`, `completed_at` in `TASKS.yaml`)
- Conversation archive JSON sidecar files
- LangGraph checkpoint data

**Utilities:**
- `workspace_now(timezone_str)` - Current time in workspace timezone
- `format_for_display(dt, timezone_str, fmt)` - Convert UTC datetime to display string

**Validation:** `WorkspaceConfig.timezone` has a Pydantic validator that rejects invalid IANA identifiers at config load time.

### Filesystem Access (`openpaw/agent/tools/`)

Agents have sandboxed filesystem access to their workspace directory.

**Components:**
- **`filesystem.py`** - `FilesystemTools` providing sandboxed operations
- **`sandbox.py`** - `resolve_sandboxed_path()` shared utility

**Available operations:**
- `ls` - List directory contents
- `read_file` - Read file (100K character safety valve)
- `write_file` - Write to new file
- `overwrite_file` - Replace existing file
- `edit_file` - Find-and-replace edit
- `glob_files` - Pattern-based file search
- `grep_files` - Content search (supports `context_lines` for surrounding context)
- `file_info` - Lightweight metadata (size, line count, binary detection, read strategy hints)

**Security:**
- Agents restricted to workspace root
- Cannot read/write `.openpaw/` directory (framework internals protected)
- `resolve_sandboxed_path()` validates all paths (rejects absolute paths, `~`, `..`, `.openpaw/`)
- Shared by `FilesystemTools`, `SendFileTool`, and inbound processors

### Inbound File Handling (`openpaw/builtins/processors/`)

OpenPaw provides universal file persistence with optional content enrichment.

**Processor pipeline order:** `file_persistence` → `whisper` → `timestamp` → `docling`

**FilePersistenceProcessor:**
- Saves all uploaded files to `{workspace}/uploads/{YYYY-MM-DD}/` (date partitioning)
- Sets `attachment.saved_path` for downstream processors
- Enriches message content with file receipt notifications

**Content enrichment:**
- **WhisperProcessor** - Transcribes audio/voice, saves `.txt` sibling (e.g., `voice.ogg` → `voice.txt`)
- **DoclingProcessor** - Converts PDF/DOCX/PPTX to markdown with OCR, saves `.md` sibling (e.g., `report.pdf` → `report.md`)

**Agent view:** The agent receives enriched message content with file metadata and transcripts/conversions appended inline. Original files remain in `uploads/` for agent filesystem access.

**Filename handling:**
- `sanitize_filename()` - Normalizes filenames (lowercase, remove special chars, replace spaces)
- `deduplicate_path()` - Appends counters (1), (2), etc. to prevent overwrites

## Data Flow

### Incoming Message Flow

```
1. Platform (Telegram)
   ↓
2. Channel Adapter
   - Convert to unified Message format
   - Run processors (file_persistence, whisper, docling)
   ↓
3. Command Router
   - Intercept slash commands (/new, /status, etc.)
   - Execute command or pass to queue
   ↓
4. Queue Manager
   - Assign to lane (main, subagent, cron)
   - Apply queue mode logic (collect, steer, interrupt)
   - Enforce concurrency limits
   ↓
5. Message Processor
   - Dequeue from lane
   - Build agent context from checkpointer
   ↓
6. Agent Runner
   - Invoke LangGraph create_react_agent with middleware
   - Track token usage via UsageMetadataCallbackHandler
   ↓
7. Middleware Stack
   - QueueAwareToolMiddleware (check for pending messages)
   - ApprovalToolMiddleware (gate dangerous tools)
   ↓
8. Agent Processing
   - Read workspace files via FilesystemTools
   - Invoke tools (brave_search, spawn_agent, etc.)
   - Generate response
   ↓
9. Response Output
   - Return to WorkspaceRunner
   - Log token usage to token_usage.jsonl
   ↓
10. Channel Adapter
    - Convert to platform-specific format
    - Send to Telegram
```

### Cron Job Flow

```
1. APScheduler Trigger
   - Cron expression matched (workspace timezone)
   ↓
2. Cron Scheduler
   - Build fresh agent instance (no checkpointer, stateless)
   - Inject cron prompt into system prompt
   ↓
3. Agent Processing
   - Access workspace files
   - Use tools if needed
   - Generate output
   ↓
4. Output Routing
   - Send to configured channel/chat_id
   - Log token usage
   ↓
5. Channel Adapter
   - Deliver to platform
```

### Heartbeat Flow

```
1. Heartbeat Scheduler Trigger
   - Interval elapsed (e.g., 30 minutes)
   ↓
2. Active Hours Check
   - Skip if outside active_hours window
   ↓
3. Pre-flight Skip Check
   - If HEARTBEAT.md is empty/trivial AND no active tasks → skip (avoid LLM call)
   ↓
4. Build Heartbeat Prompt
   - Inject task summary if active tasks exist
   ↓
5. Agent Processing
   - Generate heartbeat response
   ↓
6. HEARTBEAT_OK Suppression
   - If response is exactly "HEARTBEAT_OK" AND suppress_ok=true → don't send
   ↓
7. Output Routing
   - Send to configured channel/chat_id
   - Log event to heartbeat_log.jsonl with metrics
```

### Sub-Agent Flow

```
1. Main Agent
   - Calls spawn_agent(task="...", label="...")
   ↓
2. SubAgentStore
   - Create SubAgentRequest (status: pending)
   - Persist to .openpaw/subagents.yaml
   ↓
3. SubAgentRunner
   - Acquire semaphore (max 8 concurrent)
   - Update status: running
   ↓
4. Build Sub-Agent Instance
   - Fresh AgentRunner with filtered tools (no spawn, no send_message, etc.)
   - No checkpointer (stateless)
   ↓
5. Execute Task
   - Invoke agent with task prompt
   - Track token usage
   ↓
6. Completion
   - Store result (truncated at 50K chars)
   - Update status: completed/failed/timed_out
   - Release semaphore
   ↓
7. Notification (if notify=true)
   - Inject [SYSTEM] notification into main queue (QueueMode.COLLECT)
   - Triggers new agent turn in main lane
   ↓
8. Main Agent
   - Receives notification
   - Calls get_subagent_result(id) if needed
   - Processes result naturally
```

### Approval Gate Flow

```
1. Agent calls gated tool (e.g., overwrite_file)
   ↓
2. ApprovalToolMiddleware
   - Detects tool requires approval
   - Creates PendingApproval in ApprovalGateManager
   - Raises ApprovalRequiredError
   ↓
3. WorkspaceRunner
   - Catches ApprovalRequiredError
   - Sends approval request to channel
   ↓
4. Channel Adapter
   - Sends inline keyboard (Approve/Deny buttons)
   ↓
5. User Response
   - Clicks Approve or Deny
   - Channel invokes approval callback
   ↓
6. ApprovalGateManager
   - Resolves approval (approved or denied)
   - Stores result
   ↓
7. Agent Re-run
   - On approval: WorkspaceRunner re-runs agent with same message
   - Middleware checks check_recent_approval() → allows tool through
   - Tool executes → clear_recent_approval()
   ↓
8. On Denial
   - WorkspaceRunner sends [SYSTEM] denial message to agent
   - Agent sees "The tool 'X' was denied by the user. Do not retry this action."
```

## Component Dependencies

```
CLI (openpaw/cli.py)
 └─→ OpenPawOrchestrator (openpaw/runtime/orchestrator.py)
      └─→ WorkspaceRunner (openpaw/workspace/runner.py) [per workspace]
           ├─→ WorkspaceLoader (openpaw/workspace/loader.py)
           ├─→ ConfigLoader (openpaw/core/config/loader.py)
           ├─→ ChannelFactory (openpaw/channels/factory.py)
           │    └─→ TelegramAdapter (openpaw/channels/telegram.py)
           ├─→ QueueManager (openpaw/runtime/queue/manager.py)
           │    └─→ LaneQueue (openpaw/runtime/queue/lane.py)
           ├─→ BuiltinLoader (openpaw/builtins/loader.py)
           ├─→ CronScheduler (openpaw/runtime/scheduling/cron.py)
           ├─→ HeartbeatScheduler (openpaw/runtime/scheduling/heartbeat.py)
           ├─→ SessionManager (openpaw/runtime/session/manager.py)
           ├─→ ConversationArchiver (openpaw/runtime/session/archiver.py)
           ├─→ SubAgentRunner (openpaw/subagent/runner.py)
           ├─→ ApprovalGateManager (openpaw/stores/approval.py)
           └─→ AgentFactory (openpaw/workspace/agent_factory.py)
                └─→ AgentRunner (openpaw/agent/runner.py)
                     ├─→ QueueAwareToolMiddleware (openpaw/agent/middleware/queue_aware.py)
                     ├─→ ApprovalToolMiddleware (openpaw/agent/middleware/approval.py)
                     ├─→ FilesystemTools (openpaw/agent/tools/filesystem.py)
                     └─→ LangGraph create_react_agent
                          ├─→ LangChain init_chat_model
                          └─→ Model providers (Anthropic, OpenAI, Bedrock)
```

## Workspace Isolation

Each workspace is **fully isolated** from other workspaces:

**Separate agent instances:**
- Own `AgentRunner` with LangGraph agent
- Own conversation memory (`AsyncSqliteSaver` at `.openpaw/conversations.db`)
- Own system prompt (stitched from AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)

**Separate channels:**
- Can use different Telegram bots (different tokens)
- Independent access control (`allowed_users`, `allowed_groups`)
- Isolated message routing

**Separate queues:**
- Own `QueueManager` and lane configuration
- Independent concurrency limits per lane
- Isolated queue modes

**Separate filesystems:**
- Sandboxed to workspace directory
- Cannot access other workspaces
- Cannot access OpenPaw core files
- `.openpaw/` directory protected from agent access

**Separate schedulers:**
- Own `CronScheduler` (APScheduler instance)
- Own `HeartbeatScheduler`
- Independent job schedules

**Separate sessions:**
- Own `SessionManager` (session/thread tracking)
- Own `ConversationArchiver` (exports to workspace `memory/`)
- Own `SubAgentRunner` (background agent coordination)

This enables running multiple distinct agents simultaneously without interference.

## Memory and State

### Conversation Memory

**Per session:**
- Session ID: `{channel}:{id}` (e.g., `telegram:123456`)
- Thread ID: `{session_key}:{conversation_id}` (e.g., `telegram:123456:conv_2026-02-07T14-30-00-123456`)
- Stored in `AsyncSqliteSaver` at `.openpaw/conversations.db`
- Persists across restarts
- Archived on `/new`, `/compact`, and shutdown to `memory/conversations/`

**No summarization middleware:** OpenPaw does not use LangGraph's `SummarizationMiddleware`. Instead, it relies on:
- `/compact` command for manual summarization
- Model's native context window management
- Conversation archiving for long-term memory

### Workspace State

**Filesystem-based:**
- Agents read/write workspace files for state persistence
- `HEARTBEAT.md` commonly used for session state tracking
- `TASKS.yaml` for persistent task management
- State persists across restarts (filesystem-backed)
- Accessible in cron jobs and heartbeats

**Example state persistence:**
```markdown
# HEARTBEAT.md (before)
No active tasks.

# User: "Start working on OpenPaw docs"

# HEARTBEAT.md (after agent updates)
Active projects:
- OpenPaw documentation (started 2026-02-07)
- Draft architecture.md and getting-started.md
```

### Cron State

**No conversation memory:**
- Each cron run is independent
- Fresh agent instance per execution
- No checkpointer (stateless)

**Filesystem state:**
- Can read/write workspace files
- Share state across cron runs via files
- Example: Append to `daily-log.md`, update `HEARTBEAT.md`

## Multi-Provider Support

OpenPaw supports multiple model providers via LangChain's `init_chat_model()`.

**Supported providers:**

### Anthropic Claude

```yaml
model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key: ${ANTHROPIC_API_KEY}
  temperature: 0.7
```

### OpenAI GPT

```yaml
model:
  provider: openai
  model: gpt-4o
  api_key: ${OPENAI_API_KEY}
  temperature: 0.7
```

### AWS Bedrock

```yaml
model:
  provider: bedrock_converse
  model: moonshot.kimi-k2-thinking
  region: us-east-1  # Optional, defaults to AWS_REGION env var
  temperature: 1.0
```

**Available Bedrock models:**
- `moonshot.kimi-k2-thinking` - Moonshot Kimi K2 (1T MoE, 256K context)
- `us.anthropic.claude-haiku-4-5-20251001-v1:0` - Claude Haiku 4.5
- `amazon.nova-pro-v1:0` - Amazon Nova Pro
- `amazon.nova-lite-v1:0` - Amazon Nova Lite
- `mistral.mistral-large-2402-v1:0` - Mistral Large

**Note:** Newer Bedrock models require inference profile IDs (prefixed with `us.` or `global.`). Use `aws bedrock list-inference-profiles` to discover available profiles.

### OpenAI-Compatible APIs

Any OpenAI-compatible provider can be used by specifying `base_url`:

```yaml
model:
  provider: openai
  model: kimi-k2.5
  api_key: ${MOONSHOT_API_KEY}
  base_url: https://api.moonshot.ai/v1
  temperature: 1.0
```

Extra kwargs beyond the standard set (`provider`, `model`, `api_key`, `temperature`, `max_turns`, `timeout_seconds`, `region`) are passed through to `init_chat_model()`.

## Extensibility

### Adding a New Channel

1. Create channel adapter in `openpaw/channels/<platform>.py`
2. Extend `ChannelAdapter` class
3. Implement required methods: `start()`, `stop()`, `send_message()`, `send_file()`, `send_approval_request()`, `register_commands()`
4. Convert platform messages to unified `Message` format
5. Register in `create_channel()` factory in `openpaw/channels/factory.py`

See [channels.md](channels.md) for details.

### Adding a New Builtin

1. Create tool/processor in `openpaw/builtins/tools/` or `processors/`
2. Extend `BaseBuiltinTool` or `BaseBuiltinProcessor`
3. Define `metadata` with prerequisites (API keys, packages, groups)
4. Implement `get_langchain_tool()` or `process_message()`
5. Register in `openpaw/builtins/registry.py`

See [builtins.md](builtins.md) for details.

### Adding a New Queue Mode

1. Add mode to `QueueMode` enum in `openpaw/runtime/queue/lane.py`
2. Implement handling logic in `QueueManager.add_message()`
3. Update middleware behavior in `QueueAwareToolMiddleware` if needed
4. Update configuration schema in `openpaw/core/config/models.py`
5. Document behavior in [queue-system.md](queue-system.md)

## Design Decisions

### Why LangGraph create_react_agent?

LangGraph provides:
- Native ReAct loop with tool calling
- Conversation checkpointing via `AsyncSqliteSaver`
- Middleware support for tool interception
- Multi-provider model support via LangChain `init_chat_model()`
- Proven reliability and active development

This eliminates the need to build agent orchestration from scratch.

### Why Workspace Isolation?

Isolation enables:
- Running multiple agents with different personalities simultaneously
- Independent configuration per agent (model, channel, tools)
- Security (agents can't interfere with each other's state or files)
- Clear separation of concerns
- Horizontal scaling (distribute workspaces across instances)

### Why Lane-Based Queueing?

Lanes enable:
- Different concurrency limits per message type (main: 4, subagent: 8, cron: 2)
- Prioritization (main takes precedence over subagent and cron)
- Resource management (prevent subagents from starving main lane)
- Independent queue modes per lane (future enhancement)

### Why Builtins System?

Conditional loading enables:
- Pay only for what you use (package dependencies)
- Graceful degradation (missing API key = unavailable, not fatal error)
- Per-workspace capability control (allow/deny filtering)
- Easy addition of new capabilities without modifying core
- Group-based management (`group:voice`, `group:web`)

### Why APScheduler for Cron?

APScheduler provides:
- Standard cron expression support (`"minute hour day month weekday"`)
- Async execution (integrates with asyncio event loop)
- Job management (add, remove, pause jobs dynamically)
- Timezone handling (workspace timezone support)
- Proven reliability in production environments

### Why Middleware Composition?

Middleware enables:
- Clean separation of concerns (queue awareness, approval gates, future extensions)
- Composable behavior (stack multiple middleware layers)
- Tool-level interception (before/after tool execution)
- Reusable patterns across workspaces
- Native LangChain integration (`create_agent(middleware=[...])`)

## Performance Considerations

### Concurrency

**Per workspace:**
- Channels handle messages concurrently (asyncio)
- Queue lanes enforce concurrency limits
- Agent calls are blocking (LLM API calls are synchronous)
- Sub-agents run concurrently (up to 8 by default)

**Across workspaces:**
- Workspaces run in parallel (asyncio tasks)
- Independent resource usage
- No shared state (fully isolated)

### Scaling

**Vertical scaling:**
- Increase lane concurrency for more parallelism
- Add more workspaces per instance
- Increase system resources (CPU, memory)

**Horizontal scaling:**
- Run multiple OpenPaw instances
- Use workspace-specific routing (route users to instances)
- Shared database for persistent state (future enhancement)

### Resource Usage

**Per workspace:**
- 1 channel connection (e.g., Telegram bot)
- 1 queue manager
- 1 cron scheduler (APScheduler instance)
- 1 heartbeat scheduler
- N concurrent agent instances (based on lane concurrency)
- 1 SQLite database connection (`AsyncSqliteSaver`)

**Memory:**
- Conversation checkpointers grow over time (SQLite file size)
- Token usage JSONL logs (append-only, rotate manually if needed)
- Task/subagent YAML persistence (bounded by active tasks/subagents)

## Security

### Sandboxing

**Filesystem access:**
- Agents restricted to workspace directory
- Cannot read/write OpenPaw core files
- Cannot access other workspaces
- `.openpaw/` directory protected (framework internals)
- `resolve_sandboxed_path()` validates all paths (rejects absolute paths, `~`, `..`, `.openpaw/`)

**Tool access:**
- Agents only have tools from enabled builtins
- API keys not exposed to agents
- Sub-agents have filtered tools (no recursion, no unsolicited messaging)

### Access Control

**Channel level:**
- Allowlists for users/groups (`allowed_users`, `allowed_groups`)
- Unauthorized messages ignored silently
- Per-workspace access control

**Configuration:**
- Environment variables for secrets (`${VAR}` syntax)
- No secrets in config files (use `.env` or environment export)
- `.gitignore` for sensitive data (`.env`, `.openpaw/`)

**Browser security:**
- Domain allowlist/blocklist per workspace
- Wildcard support (`*.google.com`)
- Blocklist takes precedence over allowlist

### Future Enhancements

- Rate limiting per user (prevent abuse)
- Audit logging for tool usage (security monitoring)
- Role-based access control (RBAC) for multi-user workspaces
- Encrypted conversation storage (sensitive data protection)

## Testing Strategy

**Unit tests:**
- Configuration parsing and merging (`openpaw/core/config/`)
- Queue mode behaviors (`openpaw/runtime/queue/`)
- Message format conversions (`openpaw/channels/`)
- Builtin registration and loading (`openpaw/builtins/`)
- Timezone utilities (`openpaw/core/timezone.py`)
- Filename sanitization (`openpaw/utils/filename.py`)

**Integration tests:**
- Workspace loading and initialization
- Channel message flow (mocked platform)
- Cron job execution
- Agent invocation with mocked LLM
- Sub-agent spawning and lifecycle
- Approval gate flow

**End-to-end tests:**
- Full workspace lifecycle (start → run → shutdown)
- Multi-workspace orchestration
- Conversation persistence across restarts
- Browser automation (Playwright integration)

**Current test coverage:** 1,000+ tests passing (as of web browsing builtin completion).

See `tests/` directory for test implementations.

## Future Architecture

Planned enhancements:

**Persistent queue:**
- Redis-backed queue for distributed instances
- Workspace-to-instance routing
- Leader election for cron jobs

**Enhanced observability:**
- Structured logging (JSON format)
- Metrics export (Prometheus, OpenTelemetry)
- Distributed tracing (Jaeger, Zipkin)
- WebUI for token usage, conversation archives, task management

**Additional channels:**
- Discord, Slack, WhatsApp adapters
- HTTP API for custom integrations
- WebSocket for real-time updates

**Advanced routing:**
- Route by user/group to specific workspaces
- Multi-channel support per workspace (send to Telegram + Slack simultaneously)
- Channel fallback/redundancy (primary channel fails → fallback to secondary)

**Capability discovery:**
- Agents dynamically query available tools at runtime
- Load tools on-demand based on agent requests
- Tool marketplace/registry for community contributions
