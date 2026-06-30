# AGENTS.md

This file guides AI agents working on the OpenPaw repository. It is the canonical source for project conventions, workflows, and architectural decisions.

## Project Overview

OpenPaw is a multi-channel AI agent framework built on LangGraph (`create_react_agent`). Each agent runs in an isolated workspace with its own personality files, custom tools, scheduled tasks, and sandboxed filesystem access. Supports Telegram, Discord, and stdio channels with multi-provider LLM support.

**PyPI:** `pip install openpaw-ai`  
**Version:** 0.4.1 (pre-1.0, working towards stable 1.0.0)

---

## Team Workflow

### Branch Strategy

```
main
  └── develop
        └── holding/<sprint-name>  ← integration branch for large efforts
              └── feature/<name>   ← individual work branches
```

**For large efforts (refactors, sprints):**
1. Create `holding/<sprint-name>` from `develop`
2. Cut `feature/<name>` from `holding/<sprint-name>`
3. Do work (delegate to specialized agents)
4. Open MR from `feature/<name>` → `holding/<sprint-name>`
5. **Wait for AI + human review before merging** — both reviews required
6. Merge to `holding/<sprint-name>`, update docs
7. When holding branch is complete, merge to `develop` → `main`

**For small fixes:**
1. Cut `feature/<name>` from `develop` (or `main` for hotfixes)
2. Open MR → `develop`
3. AI review + human approval
4. Merge

### Review Process

- **AI review** is automatic via GitHub Actions (`.github/workflows/ai-code-review.yml`)
- **Human review** is required for all MRs to `holding/*` and `develop`
- **No direct pushes** to `main`, `develop`, or `holding/*` without MR
- **Commit style:** `feat: <description>`, `fix: <description>`, `refactor: <description>` — no "Claude" credits, no coverage percentages

### Release Process

OpenPaw uses **semantic versioning** and **Keep a Changelog** format. Releases are tag-based with automated Trusted Publishing (OIDC) to PyPI.

#### Release Checklist

Before creating a release, the following **must** be complete:

1. **Update `CHANGELOG.md`** — Add an `[Unreleased]` section or update the version-specific section. Every MR merged since the last release should be documented under the appropriate category:
   - `Added` for new features
   - `Changed` for changes in existing functionality
   - `Deprecated` for soon-to-be removed features
   - `Removed` for now removed features
   - `Fixed` for bug fixes
   - `Security` for vulnerability fixes

2. **Update version in `pyproject.toml`** — Follow semver (e.g., `0.4.0` → `0.4.1` for patch, `0.5.0` for minor, `1.0.0` for major).

3. **Run `scripts/sync_version.py`** — Ensure `openpaw/__init__.py` matches `pyproject.toml`:
   ```bash
   python scripts/sync_version.py
   ```

4. **Verify all tests pass** — `poetry run pytest` (2,969 tests expected).

5. **Verify lint and type check** — `poetry run ruff check openpaw/` and `poetry run mypy openpaw/`.

6. **Build and inspect** — `poetry build` then verify `dist/` contains wheel, sdist, CHANGELOG.md, and README.md.

7. **Commit** — `git commit -m "release: bump version to X.Y.Z"`.

8. **Create and push tag** — `git tag vX.Y.Z && git push origin vX.Y.Z`.

#### Automated Release Pipeline

Once the tag is pushed, GitHub Actions handles the rest:

```bash
# GitHub Actions automatically:
# 1. Validates version tag matches pyproject.toml
# 2. Runs tests, lint, and mypy
# 3. Builds wheel + sdist
# 4. Publishes to TestPyPI
# 5. Waits for manual approval (pypi-production environment)
# 6. Publishes to production PyPI
# 7. Creates GitHub release with changelog
```

**Manual approval required** — Go to the GitHub Actions run and click "Approve and deploy" to publish to production PyPI.

#### Post-Release

1. **Verify PyPI** — `pip install openpaw-ai==X.Y.Z` in a fresh virtual environment.
2. **Verify version** — `openpaw --version` should report `X.Y.Z`.
3. **Update README badge** — Ensure the PyPI badge shows the new version.
4. **Merge holding → develop → main** (if releasing from a holding branch).

#### CHANGELOG Format

Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html):

```markdown
## [Unreleased]

### Added
- New feature or capability.

### Changed
- Change in existing functionality.

### Fixed
- Bug fix.

## [X.Y.Z] - YYYY-MM-DD

### Added
- Specific feature added in this release.

### Fixed
- Specific bug fixed in this release.
```

**Categories** (use only if applicable):
- `Added` — New features, capabilities, builtins, channels, or APIs.
- `Changed` — Changes to existing functionality, behavior, or configuration.
- `Deprecated` — Features marked for removal in a future release.
- `Removed` — Features removed in this release.
- `Fixed` — Bug fixes, race conditions, security issues, or type errors.
- `Security` — Vulnerability fixes or security hardening.

**Notes:**
- Always maintain an `[Unreleased]` section at the top for work-in-progress.
- Reference specific PRs or issues where possible: `- Fixed race condition in approval gate (#42)`.
- Keep entries concise but descriptive — one line per change.
- Do not repeat commit messages verbatim — summarize the user-visible impact.

---

## Build & Test

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

# Build package
poetry build
```

## CLI Commands

```bash
# Scaffold a new workspace
poetry run openpaw init <workspace_name>
poetry run openpaw init my_agent --model anthropic:claude-sonnet-4-20250514 --channel telegram

# List available workspaces
poetry run openpaw list
poetry run openpaw list --path /custom/workspaces/dir

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
```

---

## Architecture Principles

### Stability Contract

Code dependencies flow **downward only**. Upper layers depend on lower layers; lower layers never import from above.

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

- `model/` — Pure dataclasses, no framework imports
- `core/` — Config, utilities, prompts. Depends only on `model/`
- `agent/` — LangGraph execution. Depends on `core/` and `model/`
- `workspace/` — Lifecycle management. Depends on `agent/`, `core/`, `model/`
- `runtime/` — Orchestration, queues, scheduling. Depends on `workspace/` and below
- `channels/` — External adapters. Depends on `workspace/` and below

**Never introduce upward imports.** An import cycle signals a design problem.

### Workspace Isolation

Each workspace runs as an independent asyncio task with its own:
- Channel connection
- Message queue (lane-based FIFO)
- Agent instance (LangGraph ReAct)
- Conversation database (`AsyncSqliteSaver`)
- Schedulers (cron + heartbeat)
- Sandboxed filesystem

A crash in one workspace cannot affect another.

### Lane-Based Queues

Three lanes (`main`, `subagent`, `cron`) with independent concurrency limits prevent any category of work from starving another.

### Stateless Scheduled Agents

Cron jobs and heartbeats use fresh agent instances with no checkpointer. Scheduled agents communicate state through workspace files (`HEARTBEAT.md`, `TASKS.yaml`) rather than conversation history. Their toolbelt is otherwise the same as the interactive agent's — builtins, workspace tools, and MCP server tools are all available to stateless cron/heartbeat runs and profiled sub-agent spawns.

### System Event Delivery

When the main (interactive) agent processes a `[SYSTEM]` event — a cron/heartbeat injection, a sub-agent completion, or a dynamic-task result — its terminal reply is **suppressed by default**. The reply is recorded in conversation history so the agent stays aware of what happened, but it is not delivered to the user. To surface anything user-facing, the agent must call `send_message` during the run. This makes accidental bombardment (duplicate "nothing to report" messages) structurally impossible. Cron's `delivery` defaults to `both` — the raw output reaches the channel while the run is also injected for awareness; heartbeats default to `channel`.

---

## Coding Standards

### Type Safety

- **All functions and methods** must have type annotations
- **Mypy runs in strict mode** — zero errors is the target
- **No `Any` without justification** — cast explicitly when needed
- **Generic types** — use `list[str]`, `dict[str, int]`, not bare `list`, `dict`
- **Install stub packages** for untyped dependencies (e.g., `types-PyYAML`)
- **Disable `warn_unused_ignores`** in CI to prevent local/CI mismatch

### Code Quality

- **No god classes** — Classes >500 lines are a smell. Decompose into collaborators.
- **No god modules** — Modules >700 lines are a smell. Extract submodules.
- **Single Responsibility** — One reason to change per class/function
- **No bare `except:`** — Always catch specific exceptions. If broad catch is needed, log with `exc_info=True` before swallowing.
- **Exception chaining** — Use `raise NewError(...) from exc` (B904 rule)
- **No dead code** — Remove `if __name__ == "__main__":` blocks, stale `# type: ignore`, unused imports

### Async Patterns

- Prefer `asyncio` for I/O-bound work
- Use `asyncio.to_thread()` for blocking operations
- Async tools use `StructuredTool.from_function(func=sync_fn, coroutine=async_fn)`

### Persistence

- **Thread-safe** — Use `threading.Lock` + atomic write (tmp + rename)
- **Workspace-local** — All stores are scoped to the workspace directory
- **Pattern**: `_load_unlocked()` / `_save_unlocked()` for compound operations

### Error Handling

- **Never leak internal details to users** — Use `sanitize_error_for_user()` before sending errors to channels
- **Fail fast** — Unresolved `${VAR}` references cause startup errors with descriptive messages
- **Graceful degradation** — Best-effort features (channel logging, auto-compact) should never block the main flow

### Testing

- New code requires new tests
- Tests live in `tests/` and mirror the `openpaw/` package structure
- Use `pytest` with `pytest-asyncio` (`asyncio_mode = "auto"`)
- Keep tests fast and isolated — no shared mutable state
- Use fixtures over setUp/tearDown
- Test behavior, not implementation details

---

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
├── runtime/          # Orchestration, queues, scheduling, session management
├── stores/           # Persistence layer (task, subagent, dynamic cron)
├── channels/         # Channel adapters (telegram, discord, stdio)
│   └── commands/     # Framework slash commands
└── builtins/         # Optional tools and processors
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

---

## AI Team Delegation

When working on large tasks, delegate to specialized agents:

- **Senior Python Engineer** — Type hardening, complex refactors, architecture decisions
- **Readme Expert** — Documentation, README updates, docstrings
- **Junior Engineer** — Mechanical fixes, config updates, simple refactors
- **DevOps Expert** — Infrastructure, CI/CD, Terraform, AWS
- **Code Reviewer** — Pre-merge review for clarity, maintainability, best practices

**Delegate in parallel** when possible. Save context to `llm_memory/` for handoff between sessions.

---

## Lessons from Recent Sprints

### Refactoring Sprint (80+ modules)
- **Decompose monoliths** early — `runner.py` went from 1,158 to 849 lines by extracting processors, lifecycle, and loading
- **Package boundaries matter** — The stability contract prevented circular imports during the refactor
- **Tests are your safety net** — 2,969 tests passing gave confidence to make large changes

### Polish Sprint (3 phases)
- **Phase 1: Blockers** — Fix version alignment, metadata, and critical docs before anything else
- **Phase 2: Hardening** — Type-clean (`mypy` zero errors) is achievable; install stubs first
- **Phase 3: Publish** — Trusted Publishing takes time to configure but is worth it; always test the workflow

### Key Practices
- **Version sync** — Keep `pyproject.toml`, `__init__.py`, and git tags in sync. Use `scripts/sync_version.py`
- **Package name** — Check PyPI availability early. `openpaw` was taken; we use `openpaw-ai`
- **CHANGELOG** — Include in sdist via `tool.poetry.include` or `MANIFEST.in`
- **Lock file** — Ensure CI Poetry version matches local (`poetry --version`)
- **Mypy CI/local parity** — Use same mypy version, same config, disable `warn_unused_ignores` if needed

---

## Further Reading

- `docs/architecture.md` — Full system design, data flows, extensibility guide
- `docs/configuration.md` — Complete config reference
- `docs/builtins.md` — All built-in tools and processors
- `CHANGELOG.md` — Release history
- `llm_memory/` — Sprint plans, audit reports, and session handoffs
