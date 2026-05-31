# Documentation Audit Report: OpenPaw Docs vs. Codebase

**Date:** 2026-02-17
**Branch:** main
**Audited:** All 8 files in `docs/`

## Executive Summary

The docs were written against an early version of OpenPaw before a major refactor. Primary issues:

1. **Pervasive stale file paths** - Old flat layout (`openpaw/main.py`, `openpaw/core/agent.py`, `openpaw/queue/`) referenced everywhere. Canonical locations now under `openpaw/workspace/`, `openpaw/runtime/`, `openpaw/agent/`, `openpaw/core/queue/`, `openpaw/core/config/`, `openpaw/stores/`.
2. **Missing features** - Browser, sub-agents, approval gates, middleware, heartbeat, timezone, file persistence, dynamic crons, token tracking, conversation archiving, commands, and many builtins are undocumented.
3. **Incorrect "DeepAgents" references** - Multiple docs reference "DeepAgents" as the underlying framework. OpenPaw uses LangGraph's `create_react_agent` directly. No `DeepAgents`, `FilesystemBackend`, `SummarizationMiddleware`, or `create_deep_agent` exist.
4. **Wrong Message format** - Documented `Message` dataclass doesn't match `openpaw/domain/message.py`.
5. **Wrong channel registration** - Docs say edit `CHANNEL_REGISTRY` in `__init__.py`. Actual: `create_channel()` in `factory.py`.
6. **Broken cross-references** - `getting-started.md` links to non-existent `workspaces.md#skills` anchor.

## File-by-File Issues

### 1. getting-started.md
- Links to `workspaces.md#skills` describing "DeepAgents' skill system" (doesn't exist)
- Missing all features added in last 6 sprints
- Missing `timezone` field in workspace config example

### 2. configuration.md
- References `openpaw/core/config.py` (deprecated shim); actual: `openpaw/core/config/models.py` + `loader.py`
- Missing `timezone`, `heartbeat`, `approval_gates`, `tools` config sections
- Claims only `anthropic:*` models supported; actual: openai, bedrock_converse, OpenAI-compatible APIs

### 3. workspaces.md
- Directory structure missing: `.env`, `.openpaw/`, `tools/`, `uploads/`, `downloads/`, `screenshots/`, `memory/`, `heartbeat_log.jsonl`
- Entire "Skills" section describes non-existent "DeepAgents' skill system"
- References non-existent `FilesystemBackend`; actual: `FilesystemTools` in `openpaw/agent/tools/filesystem.py`

### 4. channels.md
- Channel registration points to non-existent `CHANNEL_REGISTRY`; actual: `openpaw/channels/factory.py`
- `Message` dataclass fields wrong (session_id->session_key, sender->user_id, missing attachments)
- Says commands are "regular text messages handled in personality files"; actual: full CommandRouter system
- Missing approval gate UI, send_file capability, photo handling

### 5. queue-system.md
- Path `openpaw/queue/lane.py` wrong; actual: `openpaw/core/queue/lane.py`
- Missing `steer-backlog` queue mode
- Steer mode description incorrect (says "cancels current work"; actual: redirects at tool boundary)
- Session key format wrong (`telegram_{user_id}` vs `telegram:123456`)
- Missing `/queue` runtime command

### 6. cron-scheduler.md
- Says "cron schedules run in the system timezone"; actual: workspace timezone
- Dynamic scheduling section suggests editing YAML directly; actual: CronToolBuiltin with dedicated tools
- Missing heartbeat system entirely

### 7. builtins.md (MOST OUTDATED)
- Registry only shows 4 tools + 2 processors; actual: 12 tools + 4 processors
- Missing 8 tools: cron, task_tracker, send_message, followup, send_file, spawn, browser, memory_search
- Missing 2 processors: file_persistence, docling
- Custom builtin example uses wrong pattern (BaseTool inheritance vs StructuredTool factory)
- Registration example uses wrong method names

### 8. architecture.md
- All component paths wrong (pre-refactor)
- "DeepAgents" referenced throughout (doesn't exist)
- Says InMemorySaver is default; actual: AsyncSqliteSaver
- References non-existent SummarizationMiddleware
- Missing entire architectural layers: domain/, stores/, workspace/, runtime/, agent/middleware/

## Recommendation

The docs need a **complete rewrite**, not incremental patches. The "DeepAgents" references alone touch nearly every page. Combined with the refactored package layout and 6 sprints of new features, it's more efficient to regenerate from the CLAUDE.md (which is accurate and comprehensive) than to patch the existing docs.
