# Architecture

OpenPaw is a multi-workspace AI agent framework built on [DeepAgents](https://github.com/anthropics/deepagents) (LangGraph). This document describes the system design and how components interact.

## System Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    OpenPawOrchestrator                       │
│                                                              │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐ │
│  │ WorkspaceRunner│  │ WorkspaceRunner│  │ WorkspaceRunner│ │
│  │   "gilfoyle"   │  │  "assistant"   │  │  "scheduler"   │ │
│  └────────────────┘  └────────────────┘  └────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

Each `WorkspaceRunner` is an isolated agent with its own:
- Communication channel (Telegram, etc.)
- Message queue and concurrency controls
- Agent instance and conversation memory
- Scheduled tasks (cron jobs)
- Filesystem sandbox

## Core Components

### OpenPawOrchestrator

**Location:** `openpaw/orchestrator.py`

Manages multiple workspace runners. Responsibilities:
- Discover workspaces from `workspaces_path`
- Launch requested workspace runners concurrently
- Handle graceful shutdown across all workspaces
- Coordinate startup/shutdown sequencing

**Startup flow:**
```python
orchestrator = OpenPawOrchestrator(config)
await orchestrator.run(workspace_names=["gilfoyle", "assistant"])
```

### WorkspaceRunner

**Location:** `openpaw/main.py`

Manages a single workspace. Responsibilities:
- Load workspace files (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
- Merge workspace config over global config
- Initialize channel adapter
- Create queue manager with lane configuration
- Load and configure builtins
- Schedule cron jobs
- Run message processing loop

**Lifecycle:**
```
Load workspace → Merge config → Init channel → Setup queue →
Load builtins → Schedule crons → Start message loop
```

### CLI

**Location:** `openpaw/cli.py`

Command-line interface. Responsibilities:
- Parse arguments (`-c config.yaml -w workspace1,workspace2`)
- Load global configuration
- Delegate to orchestrator

**Supported patterns:**
```bash
# Single workspace
openpaw -c config.yaml -w gilfoyle

# Multiple workspaces
openpaw -c config.yaml -w gilfoyle,assistant

# All workspaces
openpaw -c config.yaml --all
openpaw -c config.yaml -w "*"
```

### Configuration System

**Location:** `openpaw/core/config.py`

Pydantic models for validation and merging. Responsibilities:
- Parse YAML configuration files
- Expand environment variables (`${VAR}`)
- Deep-merge workspace config over global config
- Validate configuration schema

**Hierarchy:**
```
Global config.yaml
  ↓ (merged with)
Workspace agent.yaml
  ↓ (result)
Effective workspace configuration
```

### Workspace Loader

**Location:** `openpaw/workspace/loader.py`

Loads workspace personality and configuration. Responsibilities:
- Locate workspace directory
- Read required markdown files (AGENT.md, USER.md, SOUL.md, HEARTBEAT.md)
- Load optional agent.yaml
- Discover skills directory
- Load cron job definitions
- Combine into system prompt

**Output format:**
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
```

### Queue System

**Location:** `openpaw/queue/lane.py`

Lane-based FIFO queue with configurable concurrency. Responsibilities:
- Separate lanes for main, subagent, cron messages
- Per-lane concurrency limits
- Queue modes: collect, steer, followup, interrupt
- Debouncing for collect mode
- Queue capacity management and drop policies

**Architecture:**
```
QueueManager
  ├─ main_lane (concurrency: 4)
  ├─ subagent_lane (concurrency: 8)
  └─ cron_lane (concurrency: 2)
```

### Channel System

**Location:** `openpaw/channels/`

Platform adapters for communication. Responsibilities:
- Platform-specific message handling (Telegram, etc.)
- Convert to unified `Message` format
- Handle platform features (voice, buttons, etc.)
- Manage access control (allowlists)

**Current implementations:**
- `telegram.py` - Telegram bot using python-telegram-bot

**Base interface:** `openpaw/channels/base.py`

```python
class BaseChannel:
    async def start()              # Initialize platform connection
    async def stop()               # Shutdown
    async def send_message(msg)    # Send message to platform
```

### Agent Runner

**Location:** `openpaw/core/agent.py`

Wraps DeepAgents agent creation. Responsibilities:
- Stitch workspace markdown into system prompt
- Configure DeepAgents with workspace skills directory
- Set up `FilesystemBackend` for sandboxed file access
- Create agent with model configuration
- Provide tools (from builtins)

**Agent creation:**
```python
agent = create_deep_agent(
    model=model_config.model,
    system_prompt=workspace_prompt,
    tools=enabled_tools,
    filesystem_backend=workspace_filesystem,
    checkpointer=InMemorySaver()  # Or SqliteSaver for persistence
)
```

### Builtins System

**Location:** `openpaw/builtins/`

Optional capabilities loaded based on prerequisites. Responsibilities:
- Discover available builtins at startup
- Check prerequisites (API keys, packages)
- Register tools and processors
- Apply allow/deny filtering per workspace
- Load configuration for each builtin

**Components:**
- `base.py` - Base classes for tools and processors
- `registry.py` - Singleton registry of all builtins
- `loader.py` - Workspace-aware loading with filtering
- `tools/` - LangChain tool implementations
- `processors/` - Message transformer implementations

### Cron Scheduler

**Location:** `openpaw/cron/scheduler.py`

Scheduled task execution using APScheduler. Responsibilities:
- Load cron job definitions from workspace
- Parse cron expressions
- Schedule jobs with APScheduler
- Build fresh agent instance for each execution
- Route output to configured channel

**Execution model:**
```
Cron trigger → Build agent → Inject prompt → Execute →
Collect response → Send to channel
```

Each cron run is independent with no conversation history.

## Data Flow

### Incoming Message Flow

```
1. Telegram (or other platform)
   ↓
2. Channel Adapter
   - Converts to unified Message format
   - Runs processors (whisper for voice, etc.)
   ↓
3. Queue Manager
   - Assigns to appropriate lane (main)
   - Applies queue mode logic (collect, steer, etc.)
   - Enforces concurrency limits
   ↓
4. Agent Runner
   - Loads conversation context from checkpointer
   - Invokes DeepAgents agent
   - Agent has access to tools (from builtins)
   ↓
5. Agent Processing
   - Reads workspace files via FilesystemBackend
   - Invokes tools if needed (brave_search, elevenlabs)
   - Generates response
   ↓
6. Response Output
   - Returns to channel adapter
   ↓
7. Channel Adapter
   - Converts to platform-specific format
   - Sends to Telegram (or other platform)
```

### Cron Job Flow

```
1. APScheduler Trigger
   - Cron expression matched
   ↓
2. Cron Scheduler
   - Build fresh agent instance (no checkpointer)
   - Inject cron prompt
   ↓
3. Agent Processing
   - Access workspace files
   - Use tools if needed
   - Generate output
   ↓
4. Output Routing
   - Send to configured channel/chat_id
   ↓
5. Channel Adapter
   - Deliver to platform
```

### Configuration Flow

```
1. Load global config.yaml
   ↓
2. For each workspace:
   - Load workspace agent.yaml (if exists)
   - Deep-merge over global config
   - Expand environment variables
   ↓
3. Result: Effective workspace configuration
   - Used to initialize all workspace components
```

## Component Dependencies

```
CLI
 └─→ OpenPawOrchestrator
      └─→ WorkspaceRunner (per workspace)
           ├─→ WorkspaceLoader (personality files)
           ├─→ ConfigMerger (global + workspace config)
           ├─→ ChannelAdapter (Telegram, etc.)
           ├─→ QueueManager (lanes, concurrency)
           ├─→ BuiltinLoader (tools, processors)
           ├─→ CronScheduler (scheduled tasks)
           └─→ AgentRunner (DeepAgents wrapper)
                └─→ DeepAgents
                     ├─→ LangGraph
                     ├─→ LangChain
                     └─→ Claude API
```

## Workspace Isolation

Each workspace is fully isolated:

**Separate agent instances:**
- Own DeepAgents agent
- Own conversation memory (checkpointer)
- Own system prompt

**Separate channels:**
- Can use different Telegram bots
- Independent access control
- Isolated message routing

**Separate queues:**
- Own queue manager
- Independent lane configuration
- Isolated concurrency limits

**Separate filesystems:**
- Sandboxed to workspace directory
- Cannot access other workspaces
- Cannot access OpenPaw core files

**Separate cron schedulers:**
- Own APScheduler instance
- Independent job schedules
- Isolated execution

This enables running multiple distinct agents simultaneously without interference.

## Memory and State

### Conversation Memory

**Per session:**
- Session ID: `telegram_{user_id}` or `telegram_group_{group_id}`
- Stored in checkpointer: `InMemorySaver` (default) or `SqliteSaver`
- Lost on restart with `InMemorySaver`
- Persisted across restarts with `SqliteSaver`

**Summarization:**
- DeepAgents includes `SummarizationMiddleware`
- Auto-compresses when context grows large
- Keeps last 20 messages by default
- Prevents token limit errors

### Workspace State

**Filesystem-based:**
- Agents can read/write workspace files
- HEARTBEAT.md commonly used for state tracking
- State persists across restarts (filesystem-backed)
- Accessible in cron jobs

**Example state persistence:**
```markdown
# HEARTBEAT.md (before)
Active projects: None

# User: "Start working on OpenPaw docs"

# HEARTBEAT.md (after agent updates)
Active projects:
- OpenPaw documentation (started 2026-02-05)
```

### Cron State

**No conversation memory:**
- Each cron run is independent
- Fresh agent instance per execution
- No checkpointer

**Filesystem state:**
- Can read/write workspace files
- Share state across cron runs via files
- Example: Append to daily-log.md

## Extensibility

### Adding a New Channel

1. Create channel adapter in `openpaw/channels/<platform>.py`
2. Extend `BaseChannel` class
3. Implement `start()`, `stop()`, `send_message()`
4. Convert platform messages to `Message` format
5. Register in `CHANNEL_REGISTRY`

See [channels.md](channels.md#adding-new-channels) for details.

### Adding a New Builtin

1. Create tool/processor in `openpaw/builtins/tools/` or `processors/`
2. Extend `BaseBuiltinTool` or `BaseBuiltinProcessor`
3. Define metadata (prerequisites, groups)
4. Register in `openpaw/builtins/registry.py`

See [builtins.md](builtins.md#adding-custom-builtins) for details.

### Adding a New Queue Mode

1. Add mode to `QueueMode` enum in `openpaw/queue/lane.py`
2. Implement handling logic in `QueueManager.add_message()`
3. Update configuration schema in `openpaw/core/config.py`
4. Document behavior in [queue-system.md](queue-system.md)

## Design Decisions

### Why DeepAgents?

DeepAgents provides:
- LangGraph-based agent orchestration
- Built-in tool support
- Conversation checkpointing
- Native skills system
- Filesystem backend for sandboxing

This eliminates the need to build these from scratch.

### Why Workspace Isolation?

Isolation enables:
- Running multiple agents with different personalities
- Independent configuration per agent
- Security (agents can't interfere with each other)
- Clear separation of concerns

### Why Lane-Based Queuing?

Lanes enable:
- Different concurrency limits per message type
- Prioritization (main > subagent > cron)
- Independent queue modes per lane (future enhancement)
- Resource management

### Why Builtins System?

Conditional loading enables:
- Pay only for what you use (dependencies)
- Graceful degradation (missing API key = unavailable, not error)
- Per-workspace capability control
- Easy addition of new capabilities

### Why APScheduler for Cron?

APScheduler provides:
- Standard cron expression support
- Async execution
- Job management (add, remove, pause)
- Timezone handling
- Proven reliability

## Performance Considerations

### Concurrency

**Per workspace:**
- Channels handle messages concurrently (async)
- Queue lanes enforce concurrency limits
- Agent calls are blocking (LLM API calls)

**Across workspaces:**
- Workspaces run in parallel (asyncio tasks)
- Independent resource usage
- No shared state

### Scaling

**Vertical scaling:**
- Increase lane concurrency for more parallelism
- Add more workspaces per instance
- Increase system resources

**Horizontal scaling:**
- Run multiple OpenPaw instances
- Use workspace-specific routing
- Shared database for persistent state (future)

### Resource Usage

**Per workspace:**
- 1 channel connection (Telegram bot)
- 1 queue manager
- 1 cron scheduler
- N concurrent agent instances (based on lane concurrency)

**Memory:**
- Conversation checkpointers (InMemorySaver grows over time)
- Use `SqliteSaver` for bounded memory
- Summarization helps control context size

## Security

### Sandboxing

**Filesystem access:**
- Agents restricted to workspace directory
- Cannot read/write OpenPaw core files
- Cannot access other workspaces

**Tool access:**
- Agents only have tools from enabled builtins
- API keys not exposed to agents
- Tool execution is sandboxed

### Access Control

**Channel level:**
- Allowlists for users/groups
- Unauthorized messages ignored
- Per-workspace access control

**Configuration:**
- Environment variables for secrets
- No secrets in config files
- .gitignore for sensitive data

### Future Enhancements

- Rate limiting per user
- Audit logging for tool usage
- Role-based access control (RBAC)
- Encrypted conversation storage

## Testing Strategy

**Unit tests:**
- Configuration parsing and merging
- Queue mode behaviors
- Message format conversions
- Builtin registration

**Integration tests:**
- Workspace loading and initialization
- Channel message flow
- Cron job execution
- Agent invocation

**End-to-end tests:**
- Full workspace lifecycle
- Multi-workspace orchestration
- Channel integration with mocked platforms

See `tests/` directory for current test coverage.

## Future Architecture

Planned enhancements:

**Persistent state:**
- Swap `InMemorySaver` to `SqliteSaver` by default
- Share database across instances

**Multi-instance coordination:**
- Distributed queue (Redis-backed)
- Workspace-to-instance routing
- Leader election for cron jobs

**Enhanced observability:**
- Structured logging
- Metrics export (Prometheus)
- Distributed tracing

**Additional channels:**
- Discord, Slack, WhatsApp
- HTTP API for custom integrations
- WebSocket for real-time updates

**Advanced routing:**
- Route by user/group to specific workspaces
- Multi-channel support per workspace
- Channel fallback/redundancy
