# README Audit Report

**Date:** 2026-02-17
**Branch:** `main`
**Test Count:** 1,016 tests collected
**Auditor:** Claude Code (README Audit Skill)

---

## Executive Summary

The current README is functional but significantly outdated. It reflects the project from several sprints ago and is missing the majority of features that make OpenPaw compelling. The tone is dry and technical — more of a configuration reference than a project pitch. For a public release, the README needs both factual corrections and a major repositioning to highlight OpenPaw's novel capabilities.

**Severity Legend:**
- **Critical** — Blocks a new user from getting started, or is factually wrong
- **Major** — Missing feature documentation that a user would expect to find
- **Minor** — Inaccuracies or inconsistencies that could cause confusion
- **Cosmetic** — Style, tone, or formatting improvements

---

## Section-by-Section Findings

### 1. Opening / Project Description (Lines 1-3)

| Severity | Issue |
|----------|-------|
| **Major** | The one-line description is generic. "Multi-channel AI agent framework" undersells the project. It should lead with the unique value: LangGraph-native personal AI assistants that can spawn sub-agents, browse the web, schedule their own crons, manage tasks, and process documents autonomously. |
| **Minor** | No badges (PyPI, Python version, tests passing, license). Standard for public repos. |

### 2. Features Section (Lines 5-18)

| Severity | Issue |
|----------|-------|
| **Critical** | **13+ major features are completely absent** from the features list. Missing: |
| | - Web browsing (Playwright-based browser automation with accessibility tree navigation) |
| | - Sub-agent spawning (concurrent background workers with `spawn_agent`) |
| | - Approval gates (human-in-the-loop tool authorization via Telegram inline keyboards) |
| | - Document processing (Docling: PDF/DOCX/PPTX to markdown with OCR) |
| | - Voice transcription (Whisper for audio messages) |
| | - Conversation persistence (AsyncSqliteSaver, session management, archiving) |
| | - Token usage tracking (per-invocation JSONL logging, `/status` display) |
| | - Dynamic agent self-scheduling (`schedule_at`, `schedule_every` tools) |
| | - File persistence (universal upload handling with date partitions) |
| | - Slash commands (`/new`, `/compact`, `/status`, `/queue`, `/help`) |
| | - Queue-aware tool middleware (steer/interrupt during agent runs) |
| | - Timezone awareness (workspace-level IANA timezone support) |
| | - Shell execution and SSH remote tools |
| | - Semantic memory search (vector search over past conversations) |
| | - Multi-provider model support (Anthropic, OpenAI, AWS Bedrock, OpenAI-compatible APIs) |
| **Minor** | Existing feature bullets are accurate but lack excitement. "Optional Builtins" says "web search, voice transcription, TTS" — this is a small subset of the 15+ builtins now available. |

### 3. Quick Start / Installation (Lines 20-36)

| Severity | Issue |
|----------|-------|
| **Critical** | `git clone https://github.com/yourusername/OpenPaw.git` — placeholder URL. Must be updated to actual GitHub org/user before public release. |
| **Major** | Poetry extras listed don't match `pyproject.toml`. README lists `voice`, `web`, `all-builtins`. Actual `pyproject.toml` also has `system` (shell + SSH) and `memory` (sqlite-vec). |
| **Minor** | `docling` and `playwright` are now **core dependencies** (in `[project.dependencies]`), not extras. README still implies they're optional via extras. The extras system is for truly optional packages like `openai`, `elevenlabs`, `langchain-community`, `asyncssh`, `sqlite-vec`. |

### 4. Configuration Section (Lines 38-65)

| Severity | Issue |
|----------|-------|
| **Minor** | Accurate but minimal. Could benefit from a more complete example showing model provider options, timezone, heartbeat, and approval gates. |

### 5. Workspace Structure (Lines 67-108)

| Severity | Issue |
|----------|-------|
| **Minor** | The workspace creation instructions are correct. The `@tool` example is accurate. |
| **Minor** | Missing mention that workspaces can also have `agent.yaml` for per-workspace config overrides, `crons/*.yaml` for scheduled tasks, `.env` for secrets, and a `memory/` directory for conversation archives. |

### 6. Run Commands (Lines 110-124)

| Severity | Issue |
|----------|-------|
| **Minor** | Commands are correct. The `-v` verbose flag, `-w` workspace flag, `--all` flag all verified against `openpaw/cli.py`. |

### 7. Architecture Diagram (Lines 126-138)

| Severity | Issue |
|----------|-------|
| **Minor** | Diagram is accurate. `OpenPawOrchestrator` class name confirmed in `openpaw/runtime/orchestrator.py`. The `Channel -> QueueManager -> LaneQueue -> AgentRunner -> LangGraph ReAct Agent` flow is correct. |
| **Minor** | Could be expanded to show the middleware layer (queue-aware + approval) between LaneQueue and AgentRunner. |

### 8. Documentation Links (Lines 140-149)

| Severity | Issue |
|----------|-------|
| **Major** | All 8 linked doc files exist in `docs/`. However, **the docs themselves are severely outdated** (see separate docs audit). They reference the pre-refactor package layout, mention "DeepAgents" (a framework OpenPaw does not use), have incorrect `Message` format, wrong channel registration instructions, and are missing documentation for all features added in the last ~6 sprints. |

### 9. Development Section (Lines 151-163)

| Severity | Issue |
|----------|-------|
| **Minor** | Commands are correct: `poetry run pytest`, `poetry run ruff check openpaw/`, `poetry run mypy openpaw/` all verified. |

### 10. Requirements Section (Lines 165-173)

| Severity | Issue |
|----------|-------|
| **Minor** | README says "Python 3.12+" but `pyproject.toml` says `requires-python = ">=3.11,<4.0"`. The CLAUDE.md internal docs also reference "Python 3.12+". Should be reconciled — either update pyproject.toml or the README. |
| **Minor** | "Model provider credentials (one of)" is accurate. Lists Anthropic, OpenAI, AWS Bedrock correctly. Could also mention OpenAI-compatible APIs (e.g., Moonshot/Kimi). |

### 11. License (Lines 175-177)

| Severity | Issue |
|----------|-------|
| **Critical** | README states "MIT" but **no LICENSE file exists at the project root**. Must create `LICENSE` with MIT license text before going public. |

### 12. Credits (Lines 179-181)

| Severity | Issue |
|----------|-------|
| **Minor** | OpenClaw credit is appropriate. Could also credit LangGraph/LangChain ecosystem. |

---

## Missing Repo Hygiene Items

| Severity | Item |
|----------|------|
| **Critical** | No `LICENSE` file at project root |
| **Major** | `.gitignore` excludes `agent_workspaces/` entirely — good for security, but means no example workspace ships with the repo. New users have no reference workspace to learn from. Consider adding a `docs/examples/` with a sanitized example workspace. |
| **Minor** | `.gitignore` excludes `llm_memory/` — good. Also excludes `config.yaml` while keeping `config.example.yaml` — correct. |
| **Minor** | No `CONTRIBUTING.md` for a public repo |
| **Cosmetic** | No GitHub issue/PR templates |

---

## Recommended README Structure for Public Release

The README should be restructured with this flow:

1. **Hero section** — Project name, one-liner pitch, key badges
2. **What makes OpenPaw different** — 3-4 compelling bullet points (agent autonomy, @tool native, document intelligence, multi-provider)
3. **Quick demo** — Show what it looks like in action (Telegram screenshot or conversation example)
4. **Features at a glance** — Organized by category (Agent Capabilities, Builtin Tools, Framework Features)
5. **Quick Start** — Installation, config, first workspace, run
6. **Architecture overview** — Brief diagram
7. **Documentation index** — Links to detailed docs
8. **Configuration reference** — Or link to docs/configuration.md
9. **Development** — Test, lint, type check
10. **Contributing / License / Credits**

---

## Feature Inventory (for README rewrite)

Complete list of features verified against codebase:

### Agent Capabilities
- LangGraph `create_react_agent` with multi-provider support (Anthropic, OpenAI, Bedrock, OpenAI-compatible)
- Sandboxed filesystem (read, write, edit, glob, grep, file_info)
- Custom workspace `@tool` functions with auto-dependency installation
- Sub-agent spawning (up to 8 concurrent background workers)
- Self-continuation (followup tool for multi-step autonomous workflows)
- Self-scheduling (dynamic cron: `schedule_at`, `schedule_every`)
- Task management (persistent TASKS.yaml for cross-session work tracking)
- Mid-execution messaging (send_message, send_file)
- Web browsing (Playwright + accessibility tree, 11 browser tools)
- Web search (Brave Search API)
- Shell execution (local shell commands)
- SSH remote execution
- Semantic memory search (vector search over past conversations)

### Document Intelligence
- Docling: PDF, DOCX, PPTX, etc. to markdown with OCR (macOS native + EasyOCR)
- Whisper: Audio/voice message transcription
- File persistence: Universal upload handling with date-partitioned storage
- Sibling file convention (report.pdf -> report.md, voice.ogg -> voice.txt)

### Framework Features
- Multi-workspace orchestration (fully isolated agents)
- Lane-based FIFO queue (main, subagent, cron lanes)
- Queue-aware tool middleware (steer, interrupt, collect, followup modes)
- Conversation persistence (AsyncSqliteSaver, session management)
- Conversation archiving (markdown + JSON exports)
- Slash commands (/new, /compact, /status, /queue, /help)
- Approval gates (human-in-the-loop with Telegram inline keyboards)
- Heartbeat system (proactive check-ins, active hours, HEARTBEAT_OK)
- Static cron scheduler (YAML-defined scheduled tasks)
- Token usage tracking (per-invocation JSONL, today/session aggregation)
- Timezone awareness (workspace-level IANA timezone)
- Structured logging with rotation
- Per-workspace .env loading

### Channel Support
- Telegram (text, voice, documents, photos, inline keyboards)
- Extensible factory pattern for additional channels

---

## Priority Actions

1. **Critical:** Create `LICENSE` file (MIT)
2. **Critical:** Fix placeholder git clone URL
3. **Critical:** Rewrite README with marketing messaging and complete feature list
4. **Major:** Update or rewrite all 8 docs/ pages (they reference "DeepAgents" and pre-refactor paths)
5. **Major:** Add example workspace or getting-started guide that doesn't require existing agent_workspaces/
6. **Minor:** Reconcile Python version (3.11 vs 3.12) across pyproject.toml and docs
7. **Minor:** Update pyproject.toml extras documentation in README
