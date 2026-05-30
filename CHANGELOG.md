# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

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

[0.4.0]: https://github.com/johnsosoka/openpaw/releases/tag/v0.4.0
