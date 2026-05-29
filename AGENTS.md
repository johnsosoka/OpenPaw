# AGENTS.md

This file provides guidance to AI agents working with code in the OpenPaw repository.

## Project Background

OpenPaw is a multi-channel AI agent framework built on LangGraph (`create_react_agent`). It gives each agent its own isolated workspace — personality files, custom tools, scheduled tasks, and sandboxed filesystem access — then handles the orchestration so you can focus on what the agent actually does.

Agents can ingest documents, browse the web, search the internet, manage files, and run scheduled cron jobs or heartbeat check-ins. The framework supports Telegram, Discord, and stdio channels with multi-provider LLM support (Anthropic, OpenAI, AWS Bedrock, xAI, Fireworks, and OpenAI-compatible endpoints).

## Build Commands

```bash
# Install dependencies
poetry install

# Run tests
poetry run pytest

# Lint
poetry run ruff check openpaw/
poetry run ruff check openpaw/ --fix

# Type check
poetry run mypy openpaw/
```

## Key Architectural Decisions

**Workspace isolation** — Each workspace runs as an independent asyncio task with its own channel connection, message queue, agent instance, conversation database, and schedulers. A crash in one workspace cannot affect another.

**Stability contract** — Code dependencies flow downward only. `model/` has no framework imports; `core/` depends only on `model/`; `agent/` and `workspace/` may depend on lower layers but never on `runtime/` or `channels/`. Never introduce upward imports.

**Lane-based queues** — Three lanes (`main`, `subagent`, `cron`) with independent concurrency limits prevent any category of work from starving another. Sub-agent tasks cannot block interactive user messages.

**Stateless scheduled agents** — Cron jobs and heartbeats use fresh agent instances with no checkpointer. Scheduled agents communicate state through workspace files (`HEARTBEAT.md`, `TASKS.yaml`) rather than conversation history.

## Directory Structure

```
openpaw/
├── model/            # Pure business models (no framework imports)
├── core/             # Configuration, logging, timezone, utilities, prompts
│   └── config/       # Pydantic models, loaders, env expansion
├── agent/            # Agent execution (LangGraph wrapper, middleware, tools)
│   ├── middleware/   # Queue-aware, approval, status reminder
│   └── tools/        # Sandboxed filesystem tools
├── workspace/        # Workspace management (runner, message processor, factory)
├── runtime/          # Orchestrator, queues, scheduling, session management
├── stores/           # Persistence layer (task, subagent, dynamic cron)
├── channels/         # Channel adapters (telegram, discord, stdio)
│   └── commands/     # Framework slash commands
└── builtins/         # Optional tools and processors (brave_search, browser, etc.)
    ├── tools/
    └── processors/
```

**Where to add new code:**

- **New builtin tools** → `openpaw/builtins/tools/`
- **New builtin processors** → `openpaw/builtins/processors/`
- **New channel adapter** → `openpaw/channels/`
- **New command** → `openpaw/channels/commands/handlers/`
- **New config fields** → `openpaw/core/config/models/`
- **New persistence store** → `openpaw/stores/`

## Conventions

**Type hints** — All functions and methods must have type annotations. Mypy runs in strict mode.

**Docstrings** — Use clear, concise docstrings. Explain *why* when the code does not make intent obvious.

**Async patterns** — Prefer `asyncio` for I/O-bound work. Use `asyncio.to_thread()` for blocking operations. Async tools use `StructuredTool.from_function(func=sync_fn, coroutine=async_fn)`.

**Thread-safe persistence** — Follow the `threading.Lock` + atomic write (tmp + rename) pattern used throughout `openpaw/stores/`.

**Error handling** — Never leak internal details to users. Use `sanitize_error_for_user()` before sending errors to channels.

**Testing** — New code requires new tests. Tests live in `tests/` and mirror the `openpaw/` package structure.

- Use `pytest` with `pytest-asyncio` for async tests (`asyncio_mode = "auto"` in `pyproject.toml`).
- Keep tests fast and isolated — no shared mutable state.
- Use fixtures over setUp/tearDown.
- Test behavior, not implementation details.

## Further Reading

See `CLAUDE.md` for full architecture details, component descriptions, workspace structure, and configuration reference.
