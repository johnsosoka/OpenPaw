# Contributing to OpenPaw

Thank you for your interest in contributing. OpenPaw is built with a strong emphasis on clean, readable, and maintainable code. Contributions that share that philosophy are welcome.

Before diving in, it is worth reading through this guide and the [Architecture overview](docs/architecture.md) to understand how the system is structured and where new code belongs.

---

## Development Setup

**Prerequisites**

- Python 3.11+
- [Poetry 2.0+](https://python-poetry.org/docs/#installation)

**Install**

```bash
git clone https://github.com/johnsosoka/OpenPaw.git
cd OpenPaw
poetry install
```

**Optional extras**

```bash
poetry install --extras voice    # Whisper transcription + ElevenLabs TTS
poetry install --extras web      # Brave Search via langchain-community
poetry install --extras memory   # Semantic search over conversation archives
poetry install --extras all-builtins  # All of the above
```

**Verify**

```bash
poetry run pytest
```

All tests should pass before you begin.

---

## Project Structure

OpenPaw is organized into eight top-level packages:

| Package | Purpose |
|---------|---------|
| `openpaw/model/` | Pure business models — `Message`, `Task`, `SessionState`, etc. No framework dependencies. |
| `openpaw/core/` | Configuration, logging, timezone utilities, centralized prompts, shared utilities. |
| `openpaw/agent/` | `AgentRunner` (LangGraph wrapper), token metrics, tool middleware, sandboxed filesystem tools. |
| `openpaw/workspace/` | `WorkspaceRunner`, message processing loop, agent factory, lifecycle hooks, tool loader. |
| `openpaw/runtime/` | `OpenPawOrchestrator`, lane queues, cron/heartbeat schedulers, session management, sub-agent runner. |
| `openpaw/stores/` | Persistence layer — task, sub-agent, dynamic cron, and vector stores. |
| `openpaw/channels/` | Channel adapters (Telegram), command router, channel factory. |
| `openpaw/builtins/` | Optional tools and processors loaded conditionally at startup. |

**Stability contract:** Dependencies point inward toward stability. `model/` has no dependencies on any other package. `core/` depends only on `model/`. Code in `agent/` or `workspace/` may depend on lower layers but not on `runtime/` or `channels/`. Violations of this contract will be flagged in review.

---

## Development Workflow

**Branching**

Branch from `develop` using one of these prefixes:

```
feature/short-description
bugfix/short-description
docs/short-description
chore/short-description
```

Feature and bugfix branches are merged into `develop` via pull request. The `develop` branch is merged into `main` for releases.

**Before submitting**

Run all three checks locally before opening a pull request:

```bash
# Lint
poetry run ruff check openpaw/

# Type check
poetry run mypy openpaw/

# Tests
poetry run pytest
```

Fix any issues before pushing. PRs with failing lint, type errors, or broken tests will not be merged.

---

## Code Style

OpenPaw uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, and [mypy](https://mypy-lang.org/) in strict mode for type checking. Configuration lives in `pyproject.toml`.

**Key conventions:**

- All functions and methods must have type annotations.
- Keep functions small and single-purpose. If a function is doing more than one thing, extract it.
- Avoid flag arguments and deep nesting. Prefer early returns.
- Use descriptive names. Abbreviations are acceptable only for well-understood domain terms.
- Thread-safe persistence follows the `threading.Lock` + atomic write (tmp + rename) pattern used throughout `openpaw/stores/`.
- Async tools use the `StructuredTool.from_function(func=sync_fn, coroutine=async_fn)` pattern.
- Builtins that need channel access use the shared `_channel_context.py` contextvars module — do not pass channel references directly into tool functions.

---

## Testing

Tests live in `tests/` and mirror the `openpaw/` package structure. New code requires new tests.

```bash
# Run all tests
poetry run pytest

# Run a specific file
poetry run pytest tests/test_builtin_loader.py -v

# Run tests matching a name pattern
poetry run pytest -k "test_approval"
```

**Test conventions:**

- Use `pytest` with `pytest-asyncio` for async tests (`asyncio_mode = "auto"` is set in `pyproject.toml`).
- Tests should be fast and isolated — no shared mutable state between test functions.
- Use fixtures over setUp/tearDown patterns.
- Test behavior, not implementation details.
- When adding a new builtin, processor, or channel adapter, include unit tests for the core logic and at least one integration-style test for the happy path.

---

## Pull Request Process

1. Fork the repository and create a branch from `develop`.
2. Implement your change with tests.
3. Run lint, type check, and tests locally — all must pass.
4. Open a pull request against `develop`. Reference any related issue in the PR description.
5. Keep PRs focused: one feature or fix per PR. If your change is large, consider breaking it into a series of smaller PRs.

PRs that introduce unnecessary complexity, skip tests, or deviate from the architectural conventions described above will be asked to revise before merge.

---

## Adding Builtins

Builtins are the primary extension point. They are optional capabilities (tools or processors) loaded conditionally at workspace startup.

**Tools** are LangChain-compatible tools the agent can invoke. **Processors** are channel-layer message transformers that run before the agent sees a message.

**Steps to add a new builtin:**

1. Create a class in `openpaw/builtins/tools/` or `openpaw/builtins/processors/` that extends `BaseBuiltinTool` or `BaseBuiltinProcessor`.
2. Define a `metadata` property returning a `BuiltinMetadata` instance. Declare any prerequisites (e.g., API keys, packages) here — the loader will skip the builtin if prerequisites are not met.
3. Implement `get_langchain_tool()` (for tools) or `process()` (for processors). Tools must return a list, even if it contains a single tool.
4. Register the class in `openpaw/builtins/registry.py`.
5. If the builtin has configuration fields, add a typed field to `BuiltinsConfig` / `WorkspaceBuiltinsConfig` in `openpaw/core/config/models.py`.
6. If the builtin warrants a mention in the framework orientation prompt, add a conditional section in `openpaw/core/prompts/framework.py`.

See `openpaw/builtins/tools/brave_search.py` for a minimal tool example and `openpaw/builtins/processors/whisper.py` for a processor example.

---

## Adding Channels

The channel system is factory-based and decoupled from `WorkspaceRunner`. See [docs/channels.md](docs/channels.md) for the full guide on implementing and registering a new channel adapter.

---

## License

OpenPaw is released under the [PolyForm Noncommercial 1.0.0](LICENSE) license. By contributing, you agree that your contributions will be licensed under the same terms.
