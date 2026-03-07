# Architecture

OpenPaw is a multi-workspace AI agent framework built on [LangGraph](https://langchain-ai.github.io/langgraph/) (`create_react_agent`) and [LangChain](https://www.langchain.com/). This page covers system design, data flows, and architectural decisions for developers who want to understand, contribute to, or extend the framework.

<div align="center">
  <img src="../assets/images/openpaw-multi-agent.png" alt="OpenPaw Architecture Overview" width="650">
</div>

---

## System Overview

`OpenPawOrchestrator` manages a collection of `WorkspaceRunner` instances, each representing a fully isolated agent.

[![System Overview](../assets/diagrams/system-overview.png)](../assets/diagrams/system-overview.png)

Each workspace runs as an independent asyncio task with its own:

- **Channel connection** — a dedicated Telegram bot or other platform adapter
- **Message queue** — lane-based FIFO with per-lane concurrency limits
- **Agent instance** — LangGraph ReAct loop with composed middleware
- **Conversation database** — `AsyncSqliteSaver` backed by SQLite, persists across restarts
- **Schedulers** — cron jobs and heartbeat check-ins, each in the workspace timezone
- **Sandboxed filesystem** — read/write access scoped to the workspace directory

`OpenPawOrchestrator` launches workspaces concurrently and coordinates graceful shutdown, including archiving active conversations. Workspaces share no state — a crash or misconfiguration in one cannot affect another.

---

## Layered Architecture

OpenPaw enforces a **stability contract**: code dependencies flow downward only. Upper layers depend on lower layers; lower layers never import from above. This prevents circular imports and keeps the core data layer portable across framework changes.

```
        cli.py
           │
    runtime/orchestrator
           │
    workspace/runner  ──── channels/
           │           └── builtins/
       agent/runner    └── stores/
           │
        model/
```

[![Component Dependencies](../assets/diagrams/component-dependencies.png)](../assets/diagrams/component-dependencies.png)

The stability contract is enforced by convention: any import that flows upward is a design violation. `model/` has no framework imports; `core/` does not import from `agent/` or `workspace/`; `agent/` does not import from `workspace/` or `runtime/`.

### `openpaw/model/`

Pure dataclasses with no framework imports and no I/O. These are the types that flow through the entire system:

- `Message` / `MessageAttachment` — unified representation of an inbound user event
- `Task` / `TaskStatus` — cross-session task records for `TASKS.yaml`
- `SessionState` — which conversation thread is active for a given session key
- `SubAgentRequest` / `SubAgentStatus` — lifecycle tracking for spawned agents
- `DynamicCronTask` — agent-scheduled task definition

Any layer can import from `model/` without introducing a dependency cycle. These types are the shared vocabulary of the entire codebase.

### `openpaw/core/`

Cross-cutting infrastructure used by all higher layers. Nothing in `core/` imports from `agent/`, `workspace/`, or `runtime/`.

- **`config/models.py`** — Pydantic models for `GlobalConfig`, `WorkspaceConfig`, `CronDefinition`, `ProviderDefinition`, and related nested structures
- **`config/loader.py`** — Discovers workspace directories, loads YAML files, performs deep merge of global over workspace config
- **`config/env_expansion.py`** — Expands `${VAR}` tokens; fails fast with a descriptive error for unresolved references
- **`config/providers.py`** — `resolve_provider()` maps a catalog provider name to a `ResolvedProvider` (model string, API key, region, extra kwargs)
- **`timezone.py`** — `workspace_now(tz)` and `format_for_display(dt, tz, fmt)` implement the "store in UTC, display in workspace timezone" pattern
- **`workspace.py`** — `AgentWorkspace` dataclass that assembles the XML-tagged system prompt from identity files and dynamic framework sections
- **`utils.py`** — `sanitize_filename()`, `deduplicate_path()`, `sanitize_error_for_user()`, `resolve_user_name()`

### `openpaw/agent/`

The LangGraph execution layer. `AgentRunner` wraps `create_react_agent()`, composes the middleware stack, and manages model instantiation via `init_chat_model()`.

**Key responsibilities:**

- Stitches `AGENT.md`, `USER.md`, `SOUL.md`, `HEARTBEAT.md`, and a dynamic `<framework>` section into the system prompt as XML-tagged blocks
- Uses `UsageMetadataCallbackHandler` per invocation to capture input/output token counts, exposed via `last_metrics`
- Exposes `update_model()` for live model switching without restarting the workspace or losing conversation state
- Provides `get_context_info()` for context window utilization checks (used by auto-compact)

**`agent/middleware/`** contains two middleware classes that use LangGraph's `@wrap_tool_call` decorator pattern:

- `QueueAwareToolMiddleware` — calls `queue_manager.peek_pending()` before each tool call; in steer mode injects pending messages as next input; in interrupt mode raises `InterruptSignalError`
- `ApprovalToolMiddleware` — checks whether the target tool is gated; if so, raises `ApprovalRequiredError` and stores a `PendingApproval`

**`agent/tools/`** provides `FilesystemTools` — eight sandboxed operations (`ls`, `read_file`, `write_file`, `overwrite_file`, `edit_file`, `glob_files`, `grep_files`, `file_info`) restricted to the workspace root. `sandbox.py` exports `resolve_sandboxed_path()`, which rejects absolute paths, `~`, `..`, and `.openpaw/` access. This function is shared by `SendFileTool` and inbound processors for defense-in-depth validation.

**`agent/metrics.py`** provides `InvocationMetrics` (input/output/total tokens, LLM call count), thread-safe `TokenUsageLogger` (JSONL append to `.openpaw/token_usage.jsonl`), and `TokenUsageReader` for today/session aggregation using the workspace timezone day boundary.

### `openpaw/workspace/`

Workspace lifecycle management — the layer that assembles all services into a running agent.

`WorkspaceRunner` is the central orchestrator for a single workspace. It initializes all services in order (load config → init channel → setup queue → load builtins → initialize checkpointer → schedule crons → start message loop), handles graceful shutdown (archive active conversations → close DB → stop channel), and dispatches lifecycle notifications.

`MessageProcessor` drives the main processing loop:

1. Dequeue message from lane
2. Check auto-compact threshold (pre-run, not middleware)
3. Invoke `AgentRunner.run()` with thread ID and message content
4. Catch `ApprovalRequiredError` — send approval UI to channel, await resolution
5. Catch `InterruptSignalError` — treat pending messages as new input
6. Handle `followup` depth tracking for self-continuation workflows
7. Process `[SYSTEM]` events from sub-agents and schedulers

`AgentFactory` manages the middleware list, the `RuntimeModelOverride` for `/model` switching (ephemeral — lost on restart), and `create_stateless_agent()` for cron/heartbeat runs (always uses the configured model, ignoring any runtime override).

`WorkspaceLoader` reads identity files and returns an `AgentWorkspace` with the fully assembled system prompt. `ToolLoader` discovers and imports `@tool`-decorated functions from the workspace's `tools/` directory, auto-installing packages from `tools/requirements.txt`.

### `openpaw/runtime/`

Runtime services that coordinate across a workspace's lifetime.

- **`orchestrator.py`** — `OpenPawOrchestrator` launches workspace runners as concurrent asyncio tasks and coordinates shutdown
- **`queue/lane.py`** — `LaneQueue`: FIFO with concurrency limit and per-session locking
- **`queue/manager.py`** — `QueueManager`: routes messages across `main`, `subagent`, and `cron` lanes; exposes `peek_pending()` / `consume_pending()` for middleware
- **`scheduling/cron.py`** — `CronScheduler`: APScheduler wrapper for YAML-defined and dynamically-scheduled jobs, fires in workspace timezone
- **`scheduling/heartbeat.py`** — `HeartbeatScheduler`: configurable check-in intervals with active hours enforcement, pre-flight skip logic, and HEARTBEAT_OK suppression
- **`scheduling/dynamic_cron.py`** — `DynamicCronStore`: persistence for agent-scheduled tasks
- **`session/manager.py`** — `SessionManager`: maps session keys to active conversation IDs, persisted to `.openpaw/sessions.json`
- **`session/archiver.py`** — `ConversationArchiver`: exports LangGraph checkpoint state to `memory/conversations/` as `conv_*.md` + `conv_*.json` pairs
- **`subagent/runner.py`** — `SubAgentRunner`: manages spawned agents with a semaphore, filtered tools, and session log writing

### `openpaw/stores/`

File-backed persistence using threading locks and atomic writes (write to a tmp file, then `os.rename`). All stores are thread-safe and workspace-local.

- `TaskStore` — `TASKS.yaml` CRUD with `_load_unlocked`/`_save_unlocked` pattern for atomic compound operations
- `SubAgentStore` — `subagents.yaml` with full status lifecycle; auto-cleans entries older than 24 hours on initialization
- `DynamicCronStore` — `dynamic_crons.json`; one-time tasks auto-cleanup after execution
- `ApprovalGateManager` — in-memory state machine; not persisted (approvals are short-lived by design)

### `openpaw/channels/`

External communication adapters. `ChannelAdapter` is the abstract base all adapters implement. The `create_channel()` factory in `factory.py` decouples `WorkspaceRunner` from concrete channel types — adding a new platform requires a new adapter file and a factory registration, nothing else.

The Telegram adapter handles sender allowlisting, voice/audio (delegated to `WhisperProcessor`), documents (delegated to `DoclingProcessor`), photo uploads, and inline keyboard callbacks for approval gates. The `commands/` subdirectory contains `CommandRouter` and handler classes for all framework commands.

### `openpaw/builtins/`

Extensible capabilities loaded conditionally based on prerequisites (API keys, Python packages). `BaseBuiltinTool` and `BaseBuiltinProcessor` define the extension interfaces. `BuiltinRegistry` is a singleton holding all registered builtins. `BuiltinLoader` filters by allow/deny lists and group membership, injects workspace config (including timezone) into each builtin's config dict, and activates only those with satisfied prerequisites.

**Tools** extend the agent's callable tool set: `brave_search`, `browser` (Playwright with accessibility tree), `spawn`, `cron`, `task_tracker`, `send_message`, `send_file`, `followup`, `plan`, `elevenlabs`.

**Processors** transform inbound messages before the agent sees them. Pipeline order is fixed by registration order in `registry.py`: `file_persistence` → `whisper` → `docling`. `FilePersistenceProcessor` always runs first, saving uploads to `uploads/{date}/` and setting `attachment.saved_path` so downstream processors read from disk rather than memory.

---

## Data Flows

### Message Flow

[![Message Flow](../assets/diagrams/message-flow.png)](../assets/diagrams/message-flow.png)

A user message travels through the following stages:

1. **Channel adapter** — Receives the platform event, validates the sender against the allowlist, converts to a unified `Message`, and runs the inbound processor pipeline (`file_persistence` → `whisper` → `docling`).

2. **Command router** — Checks for a slash command prefix. Matched commands execute immediately and return a `CommandResult` without entering the queue. Commands run before processors intentionally — processors that prepend text would break slash command detection.

3. **Queue manager** — Assigns the message to the `main` lane, applies debouncing, and applies queue mode logic. In `collect` mode messages accumulate briefly; in `steer` or `interrupt` mode the manager flags the middleware.

4. **Message processor** — Dequeues the message, runs the pre-flight auto-compact check, and invokes `AgentRunner.run()`.

5. **Middleware stack** — Before each tool call: `QueueAwareToolMiddleware` calls `peek_pending()` — if new messages arrived and the mode is `steer`, it skips remaining tools and injects pending messages as the next input; if the mode is `interrupt`, it raises `InterruptSignalError`. `ApprovalToolMiddleware` raises `ApprovalRequiredError` for gated tools.

6. **Agent execution** — The LangGraph ReAct loop calls tools, reads workspace files, and generates a response.

7. **Response delivery** — Returns through `MessageProcessor` to `WorkspaceRunner`, which sends it via the channel adapter. Token metrics write to `token_usage.jsonl`.

### Scheduled Execution

Cron jobs and heartbeats bypass the queue entirely. The scheduler fires at the configured time (workspace timezone), builds a fresh stateless `AgentRunner` (no checkpointer, no conversation history), injects the prompt, and invokes the agent. Session logs write to `memory/sessions/{cron,heartbeat}/` as three JSONL records: prompt, response, and metadata (tools used, token metrics, duration).

The `delivery` field controls output routing: `channel` sends directly to the configured chat, `agent` injects a `[SYSTEM]` event into the main lane queue, and `both` does both. Heartbeats add a pre-flight skip: if `HEARTBEAT.md` is trivial and no active tasks exist, the LLM call skips entirely and a `skip` outcome logs to `heartbeat_log.jsonl`.

### Sub-Agent Flow

[![Sub-Agent Flow](../assets/diagrams/subagent-flow.png)](../assets/diagrams/subagent-flow.png)

1. The main agent calls `spawn_agent(task=..., label=...)`.
2. `SubAgentStore` creates a `SubAgentRequest` (status: `pending`) and persists it to `subagents.yaml`. The ID returns to the agent immediately.
3. `SubAgentRunner` acquires a concurrency semaphore (default: 8), updates status to `running`, and builds a fresh `AgentRunner` with a filtered tool set — `spawn_agent`, `send_message`, `send_file`, `request_followup`, and scheduling tools are excluded to prevent recursion and unsolicited messaging.
4. The agent executes the task. Session logs write to `memory/sessions/subagent/`.
5. On completion, the result stores (truncated at 50K characters), status transitions, and the semaphore releases.
6. If `notify: true` (default), a `[SYSTEM]` notification injects into the main lane via `QueueMode.COLLECT`, triggering a new agent turn where the main agent can call `get_subagent_result(id)` for the full output.

### Approval Gate Flow

[![Approval Gate Flow](../assets/diagrams/approval-gate.png)](../assets/diagrams/approval-gate.png)

1. The agent calls a gated tool (e.g., `overwrite_file`).
2. `ApprovalToolMiddleware` creates a `PendingApproval` and raises `ApprovalRequiredError`.
3. `MessageProcessor` catches the error. Because LangGraph already checkpointed the `AIMessage(tool_calls=[...])`, `AgentRunner.resolve_orphaned_tool_calls()` injects synthetic `ToolMessage` responses to satisfy the state machine.
4. The channel sends an approval request (e.g., Telegram inline keyboard with Approve / Deny buttons).
5. The user responds. The channel invokes the registered approval callback, which calls `ApprovalGateManager.resolve()`.
6. On **approval**: `WorkspaceRunner` re-runs the agent with the original message. The middleware calls `check_recent_approval()`, bypasses the gate, allows the tool to execute, then calls `clear_recent_approval()`.
7. On **denial**: The agent receives `[SYSTEM] The tool 'X' was denied by the user. Do not retry this action.`
8. On **timeout**: `default_action` (`deny` or `approve`) applies automatically after `timeout_seconds`.

---

## Configuration Resolution

Global defaults merge with workspace overrides, environment variables expand, and provider catalog entries resolve connection details before any workspace starts.

[![Configuration Resolution](../assets/diagrams/config-merging.png)](../assets/diagrams/config-merging.png)

The merge is a deep dictionary merge: nested keys in `agent.yaml` override only the fields they specify; everything else inherits from `config.yaml`. A workspace that sets only `model.temperature` inherits the global model provider, API key, and all channel settings.

`${VAR}` substitution runs after merging. Any unresolved reference fails fast at startup with an error naming the missing variable and its source file. Provider catalog entries under `providers:` in `config.yaml` let multiple workspaces share connection details. The shorthand `model: moonshot:kimi-k2.5` triggers resolution: `moonshot` maps to `type: openai`, `api_key`, and `base_url` in the catalog, producing a call to `init_chat_model("openai:kimi-k2.5", ...)` with those values. The user-visible display string stays `moonshot:kimi-k2.5` in `/status` output.

See [Configuration](configuration.md) for the full field reference and provider catalog examples.

---

## Design Decisions

### Why LangGraph `create_react_agent`?

LangGraph provides a proven ReAct loop with native tool calling, conversation checkpointing via `AsyncSqliteSaver`, and first-class middleware support for tool interception. Building equivalent infrastructure from scratch would duplicate significant work with fewer correctness guarantees. LangChain's `init_chat_model()` handles multi-provider model instantiation behind a single interface, removing the need for per-provider adapter code and making runtime model switching straightforward to implement.

### Why workspace isolation?

Running each workspace as a fully independent unit means one workspace's failure, model switch, or queue backlog cannot affect another. Isolation also enables distinct personalities, channels, and tool configurations per agent — a personal assistant workspace and a monitoring workspace coexist on the same host with zero shared state, separate conversation databases, and independent access control lists. Future horizontal scaling (distributing workspaces across machines) follows naturally from this design.

### Why lane-based queueing?

Three lanes (`main`, `subagent`, `cron`) with independent concurrency limits prevent any category of work from starving another. Sub-agent tasks, which can run up to 8 concurrently, cannot block interactive user messages on the main lane. The design draws from [OpenClaw](https://github.com/johnsosoka/openclaw) (a predecessor project) whose command queue architecture proved the pattern in production. Per-lane session locking ensures a given user's messages execute in order even when concurrency is enabled.

### Why the stability contract?

Enforcing one-directional dependencies keeps `model/` free of framework imports. Models can be instantiated, serialized, and tested without pulling in LangGraph, APScheduler, or Telegram. If the framework changes its underlying orchestration library, business model code remains untouched. The stability contract also makes dependency graphs predictable — any import cycle signals a design problem that needs resolution before merging.

### Why stateless scheduled agents?

Cron jobs and heartbeats use fresh agent instances with no checkpointer. Conversation history from user sessions would consume context window during unrelated scheduled runs and could produce confusing cross-contamination between interactive conversations and automated tasks. Scheduled agents communicate state through workspace files (`HEARTBEAT.md`, `TASKS.yaml`) which all execution contexts — including the main agent — can read and write.

### Why middleware over hooks?

LangGraph's middleware API composes as a list passed to `create_agent(middleware=[...])`. Queue-aware behavior and approval gating are independent concerns that need to run in a specific order: queue-aware first so interrupt signals abort before approval prompts fire. Each middleware layer is a self-contained unit testable in isolation. New cross-cutting concerns (rate limiting, audit logging, per-tool timeouts) plug in without modifying agent, processor, or workspace code.

---

## Extensibility

### Adding a channel

Create a class extending `ChannelAdapter` in `openpaw/channels/<platform>.py`. Implement the required interface:

- `start()` / `stop()` — initialize and tear down the platform connection
- `send_message(session_key, content)` — deliver a text response
- `send_file(session_key, path, filename, caption)` — deliver a file
- `send_approval_request(session_key, request)` — display an approval UI
- `on_approval(callback)` — register the approval resolution callback
- `register_commands(definitions)` — register slash commands with the platform (e.g., Telegram bot command menu)

Convert inbound platform events to the unified `Message` model. Register the new type string in `create_channel()` in `openpaw/channels/factory.py`. `WorkspaceRunner` is fully channel-agnostic — no other changes are needed.

See [Channels](channels.md) for the interface reference and a Discord example.

### Adding a builtin tool or processor

Create a class extending `BaseBuiltinTool` or `BaseBuiltinProcessor` in `openpaw/builtins/tools/` or `openpaw/builtins/processors/`:

1. Define a `metadata` property as a `BuiltinMetadata` instance with `name`, `description`, optional `requires_api_keys`, `requires_packages`, and `group`.
2. Implement `get_langchain_tool()` returning a list of `BaseTool` instances (for tools), or `process_message(message, workspace)` (for processors).
3. Register the class in `openpaw/builtins/registry.py`.

The loader handles conditional activation — if prerequisites are unmet, the builtin is silently skipped rather than raising an error.

See [Built-ins](builtins.md) for the full builtin reference and existing implementations.

### Adding workspace tools

Drop a Python file containing `@tool`-decorated functions into a workspace's `tools/` directory. `ToolLoader` discovers and imports them at startup, merging them into the agent's tool set alongside framework builtins. List any additional packages in `tools/requirements.txt` — the loader installs missing dependencies automatically before importing. Files prefixed with `_` are skipped. Each workspace can carry a completely different tool set, enabling purpose-built agents without any framework changes.

### Adding a command

Extend `CommandHandler` ABC with:

- `definition` property — returns `CommandDefinition` (name, description, usage string)
- `handle(context: CommandContext)` — executes the command and returns `CommandResult`

Register the handler in `get_framework_commands()` in `openpaw/channels/commands/router.py`. Commands fire before inbound processors and before queue assignment. `CommandContext` provides access to the workspace runner, agent factory, session manager, and channel — everything needed to implement any framework-level operation.

---

## Security Model

### Filesystem sandboxing

Agents have read/write access scoped strictly to their workspace directory. `resolve_sandboxed_path()` validates every path before any filesystem operation, rejecting absolute paths, `~`, `..`, and any path that would escape the workspace root. The `.openpaw/` directory is additionally protected — agents cannot read or write framework internals (checkpoint database, session state, token logs). `resolve_sandboxed_path()` is shared across `FilesystemTools`, `SendFileTool`, and inbound processors for consistent enforcement.

### Tool access control

Agents only receive tools from enabled builtins and workspace-defined tools. API keys are resolved at startup from environment variables and passed to LangChain directly — they are never available as tool arguments or accessible to the agent. Sub-agents receive a filtered tool set with no recursion tools (`spawn_agent`), no unsolicited messaging tools (`send_message`, `send_file`), and no self-continuation tools (`request_followup`) to prevent unbounded autonomous behavior.

### Channel access control

Each workspace maintains an `allowed_users` and `allowed_groups` allowlist. The channel adapter silently ignores messages from unauthorized senders before they enter the processor pipeline. Access control is per-workspace — the same Telegram user may be allowed in one workspace and blocked in another.

### Secret management

Secrets never appear in config files directly. The `${VAR}` expansion system reads from environment variables at startup. Workspace `.env` files load automatically and are excluded from version control via `.gitignore`. Unresolved `${VAR}` references fail fast with a descriptive error rather than silently using empty values.

---

## Testing

The test suite (1,100+ tests as of the current release) covers three levels:

**Unit tests** target individual components in isolation: config parsing and deep-merge logic, queue mode behaviors and lane concurrency, channel message format conversion, builtin registration and conditional loading, timezone utilities, filename sanitization, and sandbox path validation. Mock-heavy by design — no external services required.

**Integration tests** wire multiple components together with a mocked LLM: workspace loading and initialization, the full message flow from channel adapter to agent response, cron and heartbeat execution, sub-agent spawning and lifecycle, and approval gate round-trips. These tests use `AsyncSqliteSaver` with an in-memory database to validate checkpointing behavior without touching disk.

**Browser tests** use Playwright's test mode to validate the accessibility tree snapshot transformer, domain policy enforcement, and browser lifecycle (lazy init, session cleanup on `/new` and `/compact`). These run against static HTML fixtures rather than live websites.

Run the full suite with `poetry run pytest`. Individual modules: `poetry run pytest tests/test_queue.py -v`.
