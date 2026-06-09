# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Automatic status updates** — `StatusUpdateMiddleware` reports agent start, tool usage, and sub-agent dispatch to the user channel with configurable throttling.
- **Hermes pattern** — Status updates edit a single message in place instead of sending multiple messages. Supports `edit_message`/`delete_message` on Telegram and Discord. Configurable via `status_updates.hermes_mode` (default: `true`).
- **Run-aware status labels** — First user-message run shows `"Starting work..."`, subsequent runs show `"Continuing work..."`. System events (cron, heartbeat, sub-agent completions) skip the status update to avoid mid-task confusion.
- **`report_progress` builtin tool** — Agent-driven structured progress reporting with `status`, `detail`, and optional `percentage` (0-100).
- **`StatusUpdatesConfig`** configuration model with workspace-level toggles (`agent_start`, `tool_calls_detected`, `tool_start`, `tool_complete`, `subagent_spawned`, `hermes_mode`) and throttling (`min_interval_seconds`, `max_updates_per_run`).
- **Typing indicators** — `status_updates.typing_indicator` (default: `true`) sends a channel typing indicator while the agent is processing.
- **Emoji reactions** — `status_updates.reactions` (default: `true`) adds an emoji reaction to the user's original message to indicate the agent is working. Reactions are removed when the agent finishes.
- **Emoji-enriched status updates** — `status_updates.use_emojis` (default: `true`) prefixes auto-generated status messages with relevant emoji (e.g., `⚙️` for tool calls, `🚀` for starting work, `🤖` for sub-agent dispatch).
- **Optional `emoji` parameter for `report_progress`** — Agents can pass a custom emoji to `report_progress` to prefix the status message with a visual indicator.
- **Steer-mode-aware status notifications** — `StatusUpdateMiddleware` now detects `STEER`, `INTERRUPT`, and `COLLECT` mode events and sends user-facing emoji-prefixed notifications via the existing Hermes message. Messages: `🔄 Redirecting to your new message...`, `🛑 Stopping current run — processing your new message`, `📨 New messages received — bundling...`. Configurable via `steer_redirected`, `run_interrupted`, and `collect_queued` (default: `true`).
- Background task supervisor in `WorkspaceRunner` that monitors queue processor health, restarts crashed tasks, and sends direct crash notifications to active sessions.
- Entry/exit logging to critical async paths (`AgentRunner.run`, `SubAgentRunner._execute_subagent`, `SubAgentProfiler.setup`, `MessageProcessor.process_messages`, `LaneQueue.process`).
- Enriched subagent timeout/error notifications with last tool context and tools used list.

### Changed

- Updated `docs/builtins.md`, `docs/configuration.md`, and `docs/architecture.md` with status updates and `report_progress` documentation.
- Updated `ChannelAdapter` base class with `edit_message` and `delete_message` default no-ops.
- Implemented `edit_message`/`delete_message` in Telegram and Discord channel adapters.
- `aafter_model` status messages now include per-tool argument details (e.g., `read_file (notes.md)` instead of just `read_file`).
- `min_interval_seconds` default lowered from `3` to `1` to allow `tool_start` messages to get through during multi-step operations.
- `tool_start` now defaults to `true` so granular status details are visible without manual configuration.
- Interrupt mode fallback notification now uses emoji-prefixed `🛑 Stopping current run — processing your new message` instead of bracketed `[Run interrupted — processing new message]`, making it unmistakably user-facing.

### Removed

### Fixed

- Fixed `AttributeError: 'CronToolBuiltin' object has no attribute '_add_to_live_scheduler'` in `FollowupScheduler` and `MessageProcessor` — both callers now use the standalone `_add_to_live_scheduler(scheduler, task)` bridge function from `scheduler_bridge.py` instead of calling a non-existent instance method. This was crashing the queue processor on delayed followup scheduling.
- `LaneQueue.process()` now catches handler exceptions and continues the loop, preventing a single handler crash from killing the entire message pipeline.
- `SubAgentStore` converted to async-safe operations with `asyncio.to_thread()`, preventing synchronous YAML I/O from blocking the event loop.
- Added outer timeout (10 minutes) to lane handler execution to prevent a single hung session from starving the entire lane.
- `QueueManager._debounce_flush` now logs exceptions instead of silently swallowing them.
- Telegram `set_message_reaction` now uses `ReactionTypeEmoji` objects instead of raw emoji strings, fixing `Reaction_invalid` and `Can't parse reactiontype` API errors.
- Reaction emojis changed to Telegram-valid set: `👍` (success) and `👎` (failure) instead of `✅` and `❌`.
- Fixed `UnboundLocalError` in `runner.py` when processing tool call updates without `messages_in_update` defined.

## [0.4.1] - 2026-05-30

### Added

- `AGENTS.md` — comprehensive agent guidance covering release process, changelog standards, and coding standards.
- PyPI badge added to README.
- GitHub issue templates (bug report, feature request, documentation).
- GitHub pull request template.
- `SECURITY.md` — security policy and vulnerability reporting.
- `CODE_OF_CONDUCT.md` — Contributor Covenant v2.1.
- Release process documented in `AGENTS.md`.
- Changelog standards documented in `AGENTS.md`.

### Changed

- `.gitignore` updated to include `*.sh`.
- `CONTRIBUTING.md` updated to reference `AGENTS.md` and the `holding/*` branching model.
- `README.md` refined as a first-class landing page with clearer install and quick-start instructions.
- `pyproject.toml` updated with `Changelog` URL in `[project.urls]`.

### Removed

- `CLAUDE.md` consolidated into `AGENTS.md`.
- `start.sh` local development script removed.

## [0.4.0] - 2026-05-29

### Added

- **Structural refactor** — Layered architecture with clear stability contract: `model` (pure data) → `core` (config, prompts, utilities) → `agent` (runner, tools, middleware) → `workspace` (loader, runner, lifecycle) → `runtime` (orchestrator, queue, scheduling, subagents) → `channels` (external adapters).
- **Multi-channel support** — Run multiple channels (Telegram, Discord) simultaneously in a single workspace. Each channel is isolated with its own session keys, activation filters, and trigger keywords.
- **Workspace isolation** — Every workspace gets its own channels, queue, agent runner, and cron scheduler. No state leakage between workspaces.
- **Cron & heartbeat scheduling** — APScheduler-based cron jobs from YAML definitions; proactive heartbeat check-ins with active-hours support, HEARTBEAT_OK suppression, and task summary injection.
- **Sub-agent spawning** — Background concurrent workers via `spawn_agent` with isolated contexts, tool filtering, and session-scoped lifecycle tracking. Supports spawn profiles (`agent/team/*.yaml`) for specialized personas.
- **Browser automation** — Playwright-based web browsing with accessibility tree navigation, domain allowlists/blocklists, cookie persistence, and screenshot/download support.
- **Email integration** — Gmail send/receive via service account + domain-wide delegation. Supports search, reply, attachments, and recipient policy enforcement.
- **GPT-Researcher builtin** — Deep research via WebSocket with streaming progress and report generation.
- **Dynamic & persistent scheduling** — Agents can schedule one-time (`schedule_at`) or recurring (`schedule_every`) tasks at runtime, or create persistent YAML cron jobs via `cron_manager`.
- **Queue-aware middleware** — Steer and interrupt modes let agents respond to new user messages mid-execution without losing context.
- **Approval gates** — Human-in-the-loop authorization for dangerous tools with configurable timeout and default action.
- **Token usage tracking** — Per-invocation metrics logged to JSONL for cost monitoring and `/status` queries.
- **Runtime model switching** — Live provider/model switching via `/model` command without restart.
- **Auto-compact** — Automatic conversation compaction when context window utilization exceeds a threshold.
- **Session TTL** — Lazy conversation auto-reset after inactivity in group channels.
- **Checkpoint pruning** — Automatic cleanup of orphaned conversation checkpoints on startup.
- **Provider catalog** — Define provider connection details once in global config and reference by name from workspaces.
- **Skills system** — Reusable knowledge patterns via `SKILL.md` files with progressive disclosure (summary vs full injection).
- **Framework skills** — Bundled reference skills for team management, web browsing, and channel awareness.
- **Status reminder middleware** — Automatic nudges for agents to update users after long silent tool chains.
- **Session logging** — JSONL session logs for heartbeat, cron, and sub-agent runs readable by the main agent.
- **Channel history & logs** — On-demand context fetch and persistent JSONL channel logging for group awareness.
- **File persistence & enrichment** — Universal upload handling with Whisper transcription and Docling document conversion.
- **Trusted Publishing support** — CI/CD workflows configured for PEP 740 Trusted Publishing to PyPI.
- **Pre-commit hooks** — Ruff, mypy, and version sync checks.

### Changed

- CLI now supports single workspace, multiple workspaces, or wildcard `--all`.
- Configuration deep-merges workspace `agent.yaml` over global `config.yaml`.
- Error sanitization prevents internal details from leaking to channel users.

### Fixed

- Various race conditions in approval gate resolution and sub-agent cancellation.
- Path traversal protection hardened across filesystem tools and inbound processors.

[Unreleased]: https://github.com/johnsosoka/OpenPaw/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/johnsosoka/openpaw/releases/tag/v0.4.1
[0.4.0]: https://github.com/johnsosoka/openpaw/releases/tag/v0.4.0
