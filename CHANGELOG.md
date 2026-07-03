# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

The 0.5.0 theme: agents that **plan visibly and learn durably**. A pluggable agent harness adds a planner type (triage → plan → execute → reflect) with per-node models and live plan checklists, while a three-phase learning loop lets agents create and update their own skills behind validation gates. The existing react agent is untouched and remains the default — a 45-scenario feature-parity matrix pins every existing behavior across both harness types.

### Added

- **Planner agent harness** (`harness.type: planner`): a triage node routes each message to the plain react loop (simple turns), a planning path (multi-step work), or an ideation path (open-ended asks). Plans are first-class state — checkpointed, revisable (step insertion "2A", remaining-plan rewrites), resumable across restarts, and rendered as a live edited-in-place checklist in-channel. Execution embeds the existing react loop per step, so middleware, approval gates, steer/interrupt, and status updates apply to every planned step by construction. Triage and every module call fail open to the react path — the planner is never less reliable than the current loop.
- **Pluggable reasoning modules** (`harness.planning.module`, `creative`, `reflection`): one interface, three kinds. Ships `direct` (single-call planning baseline), `self_discover` (SELECT/ADAPT/IMPLEMENT over the 39 Self-Discover seed modules with a per-task-type structure cache; Zhou et al. 2024), `ideonomy` (creative ideation through 28 curated ideonomic lenses with deterministic selection; after Gunkel/ideonomy.mit.edu and the MIT-licensed Morpheis/ideonomy-engine), and `light`/`full` reflection (per-step outcome verdicts; `full` may rewrite the remaining plan). `module: auto` inserts a selector that picks per task over module taglines, short-circuiting without an LLM call when only one candidate exists.
- **Per-node models** (ADR-103): each harness node (triage, planning, creative, reflection, selector, synthesize) can point at a provider-catalog entry (`triage: {model: fast}`) — credentials stay in the catalog, provider quirks stay in `create_chat_model()`, and a bare `harness: {type: planner}` runs with every node inheriting the workspace model. `/harness` prints the resolved node→model table.
- **Per-node telemetry**: every node emits `node.completed` events with token counts and latency; per-node rows land in `token_usage.jsonl` alongside the unchanged run-level records.
- **Tool equipping** (`harness.tool_equipping.enabled`, off by default): an equip step selects a task-relevant tool subset before planning, with a never-filtered floor (`always_equip`), a `request_tools` recovery loop for mis-equips, and `tools.equipped` events. React-path workspaces can instead opt into the stock `LLMToolSelectorMiddleware` (`react_selector: true`).
- **Learning loop Phase 1** (`learning.enabled`): agents watch for repeated procedures, corrected mistakes, tool recipes, and stated preferences, and codify them via the new `manage_skill` tool. Every programmatic skill write flows through a validated `SkillStore`: frontmatter schema, per-skill token budget, per-workspace skill cap, content lint (credential- and injection-shaped content rejected), and per-workspace approval policy (`immediate` or `staged`). Skills hot-equip via the new reload mechanism; a framework `skill-authoring` guide teaches the format.
- **Learning loop Phase 2** (`learning.phase2.enabled`, off by default): every N main-lane runs, a background evaluation proposes a skill to create or update; a low-temperature `skill-builder` sub-agent drafts it and the result lands **staged** for human approval via `/skills approve`. Budget-capped by `learning.budget.daily_tokens`, debounced to one in-flight evaluation, and never user-facing on failure.
- **Skills hot-reload**: `WorkspaceRunner.reload_skills()` and the `/reload` command — skills added or edited on disk take effect without a restart.
- **`/skills` command**: list skills with provenance (version, author, status) and approve/reject staged skills. Skill frontmatter gains `version`, `created_by`, `source`, `updated_at`, `status` — all backward compatible.
- **Unified status event backbone** (ADR-106): every observable happening (runs, tools, sub-agents, plan lifecycle, skill lifecycle, learning evaluations) is now a machine-readable `StatusEvent` fanned out through a per-workspace `StatusBus` to pluggable sinks — channel rendering, a JSONL event log, and (future) a web portal. Channel rendering behavior is unchanged; events flow alongside it.
- **Provider catalog `model:` field**: catalog entries can now carry a default model id, so workspaces (and harness nodes) reference `model: fast` without repeating credentials or model ids.
- **AgentHarness seam** (ADR-101): `MessageProcessor`/`WorkspaceRunner`/commands now program against a topology-agnostic protocol; all `create_agent` internals live behind it.

### Changed

- **The planner harness narrates its phases in the status line** (round-1 testing feedback): "Thinking..." during triage, a first-person routing announcement after it ("I need to form a plan for this..." / "I need to think about this creatively..."), which planning/creative module was selected, per-step reflection outcomes ("going back to the drawing board..." on a plan rewrite), and "Putting it all together..." while synthesizing. Harness runs suppress the generic "Starting work..." label, and harness phase lines bypass the status throttle so transitions are never silently dropped. React-only workspaces are unchanged.
- **Ideonomy ideation now streams its progress and insights** (two new additive status events, `module.phase` + `module.insight`): the selected lenses are announced up front ("Exploring through 3 lenses: …"), each lens shows "Lens n/m: …" as it runs, and every lens surfaces a one-line 💡 snapshot of what it found before the module weaves them together. Lens explorations are now structured output (a headline + body per lens) — the headline drives the snapshot and feeds a cleaner synthesis. Fills the silent gap where a multi-call ideation run looked frozen.
- **Self-Discover planning narrates its reasoning process too** (same `module.phase`/`module.insight` events): it announces whether it is reusing a proven reasoning structure or discovering a new one, streams the SELECT → ADAPT → IMPLEMENT stages, and surfaces a 💡 snapshot of the composed reasoning structure before building the plan — making the previously opaque "what is Self-Discover doing" visible without touching the paper's transferable, task-only discovery prompts.
- `docs/configuration.md` gains a resolution-precedence reference (model/credentials, builtins, approval gates, tool timeouts, queue) and a catalog-first model configuration guide; `config.example.yaml` rewritten catalog-first.
- New 0.5.0 config groups (`harness:`, `learning:`) use `extra="forbid"` — typos fail at startup instead of being silently swallowed.
- `docs/architecture.md` updated for the `create_agent` v2 API and direct provider instantiation (stale `create_react_agent`/`init_chat_model` references removed).

### Removed

- **`report_progress` builtin tool.** The framework's automatic status updates — tool-call lines, sub-agent lifecycle, and the new planner-harness phase/ideonomy-lens narration — now cover progress reporting comprehensively, making an agent-invoked progress tool redundant (and a wasted tool call). Its framework-prompt guidance is gone too. `send_message` remains for genuine user-facing messages mid-run, and the `status_reminder` middleware still nudges `send_message` during long silent runs.

### Deprecated

- Inline workspace model credentials (`model.api_key`/`base_url`/`region`) when a provider catalog exists, and global `agent.api_key` — one-time startup warnings point at the catalog-first form; removal targeted for 0.6.

### Fixed

- **Outbound channel deliveries now retry transient network failures.** A dropped connection or timeout talking to Telegram/Discord (e.g. an httpx `ConnectError` mid-send) previously discarded a user-facing agent response with no retry. Channels now classify their transient transport errors and route content-bearing sends through a shared bounded exponential-backoff retry (honoring server `retry_after` hints); permanent errors (Telegram `BadRequest`, Discord 4xx) still surface immediately. The retry lives on the `ChannelAdapter` interface, so stdio and future channels inherit it (inert by default).
- Dead `AgentBuilder` class removed (never instantiated; superseded by the harness seam).

## [0.4.4] - 2026-07-02

A first-run onboarding polish release, plus a Fireworks reasoning fix. Found during an install-and-run evaluation of 0.4.3 across both `poetry` and `pip`, these fixes unblock pip users, trim the default install, and correct docs and CLI output. It also resolves a `thinking` validation error that broke Fireworks reasoning models and hardens the `thinking` field so it can never leak into an unsupported provider's request.

### Added

- **`openpaw init` scaffolds a runnable `config.yaml`.** Fresh pip installs were hard-blocked at first run: `init` printed a run command that failed with `Config file not found: config.yaml`, and no `config.example.yaml` ships in the wheel to copy. `init` now writes a minimal, valid top-level `config.yaml` (when one does not already exist) next to the workspaces directory, so `run` works immediately after `init`. (#171)
- **`[documents]` extra** for the Docling OCR/CV document stack. (#174)
- **Top-level `openpaw --help` now lists the `init` and `list` subcommands** — previously it showed only the run flags, hiding the first commands a new user needs. (#177)
- **"Install from PyPI" quickstart** in the README (`pip install` → `init` → run), plus documented extras. The existing steps are labelled as the from-source (Poetry) workflow. (#172)

### Changed

- **Bare `pip install openpaw-ai` is now lean.** `docling`, `easyocr`, and `opencv` were core dependencies, so a default install pulled `torch` and hundreds of MB even for a text-only chat bot. They now live behind the optional `[documents]` extra (`pip install 'openpaw-ai[documents]'`), also included in `all-builtins`. The Docling processor already degrades gracefully when the package is absent. (#174)
- **`init` "Next steps" show the correct invocation per install mode** — both the `poetry run openpaw …` and bare `openpaw …` forms — instead of a single bare command that failed under Poetry with `command not found`. Telegram/Discord scaffolds also warn that the bot denies all users by default until you add your ID to the allowlist. (#176, #179)
- **Pinned `fireworks-ai` to the tested line (`>=0.16.4,<0.17.0`).** A bare pip install drifted to 0.19.x, which leaks aiohttp client sessions and prints `Unclosed client session` ERRORs during model init; the pin keeps pip close to `poetry.lock`. (#180)
- Advertised the token-free `stdio` channel as the fastest first-run path (README Quick Start, CLI `--channel` help) and reworded "no tokens needed" to "no channel token needed (still requires an LLM API key)". (#178)
- **`thinking` is now consumed or explicitly ignored by every provider.** Previously it was only handled for `moonshot` and `fireworks`; on other providers it silently leaked into the request body as a raw boolean (the same failure class as the Fireworks fix below). It is now popped centrally and, on providers that don't support it, ignored with a warning. (#190)

### Fixed

- **Fireworks reasoning models no longer fail with a `thinking` validation error.** The top-level `thinking: bool` config field was forwarded to the Fireworks API as a raw boolean, which the API rejects (`InvalidRequestError` on `thinking.ThinkingConfigEnabled/Disabled/Adaptive`). It is now coerced into the object form Fireworks expects — `{"type": "enabled", "budget_tokens": ...}` or `{"type": "disabled"}` — with the reasoning budget capped below `max_output_tokens`. (#190)
- **Access-denied reply pointed to the wrong config path.** The Telegram/Discord unauthorized message told users to edit `agent_workspaces/<ws>/agent.yaml`, which does not exist — the file lives under `config/`. (#175)
- **Suppressed the `langgraph` `allowed_objects` `LangChainPendingDeprecationWarning`** that printed to stderr on every CLI invocation (including `--help`). It is an upstream default we cannot pass through, so it is filtered at the package root. (#181)
- The `Config file not found` error is now actionable, pointing users to `openpaw init` and the getting-started docs. (#171)

### Documentation

- Logo now uses an absolute raw URL so it renders on the PyPI project page (repo-relative paths do not resolve there). (#170)
- Replaced the decommissioned Fireworks example model (`deepseek-v3p1`) with `kimi-k2p6` and added a note to verify against the provider's live catalog. (#173)
- Corrected `docs/channels.md`: non-allowlisted messages are **not** "silently ignored" — the bot replies with an access-denied message and logs a warning. (#179)
- Getting Started polish: `config.yaml` is scaffolded by `init` (copying `config.example.yaml` is an optional source-only step), the `agent.yaml` `model:` block is commented out unless `--model` is passed, model precedence is documented, and the Playwright browser install is noted as needed only for the browser builtin. (#182)

## [0.4.3] - 2026-06-30

> **BREAKING:** Workspaces using the pre-0.4.3 Moonshot configuration shape
> (`provider: openai` with `base_url: https://api.moonshot.ai/v1`, or any
> `extra_body.thinking` block) will now fail to load. Switch to the native
> `moonshot` provider — see migration note below.

### Added

- **Native `moonshot` provider** for Kimi models via the [langchain-moonshot](https://pypi.org/project/langchain-moonshot/) package. New top-level `thinking: bool` field on the workspace model config replaces the old `extra_body.thinking` workaround. Temperature is auto-corrected to `0.6` / `1.0` based on `thinking` when the framework default (`0.7`) reaches the provider — the override is logged as a `WARNING` so users who deliberately set `0.7` see the substitution. Reasoning content is now separated by ChatMoonshot rather than emitted as inline `<think>` tags. Install with `pip install 'openpaw-ai[moonshot]'`.
- **First-class `ollama` provider** for local models via the official [langchain-ollama](https://pypi.org/project/langchain-ollama/) package. No API key required; talks to a local Ollama server (default `http://localhost:11434`). Supports `bind_tools` on tool-capable models (llama3.1, qwen2.5, mistral-nemo, gemma3:27b, etc.). Install with `pip install 'openpaw-ai[ollama]'`.
- **`thinking: bool | None`** field on `WorkspaceModelConfig` — opt-in reasoning mode for providers that support it natively.
- **`base_url`** promoted from extras to a typed field on `WorkspaceModelConfig` for clearer schema and validation.
- New `tests/test_native_providers.py` covers ChatMoonshot wiring (thinking flag, temperature auto-correct, ImportError) and ChatOllama wiring (no api_key, ollama-specific kwargs, no retries, ImportError) plus provider catalog integration for both.
- `openpaw init` workspace scaffolder learned `moonshot` and `ollama` providers. `openpaw init my_agent --model moonshot:kimi-k2.5` scaffolds a config with `thinking: false` + `temperature: 0.6`; `--model ollama:llama3.1` scaffolds keyless with `base_url: http://localhost:11434` and `num_ctx: 16384`. New tests in `tests/cli_init/test_scaffolder.py` round-trip the generated YAML through `WorkspaceConfig` to ensure it boots cleanly.
- **First-class MCP (Model Context Protocol) server support** via [langchain-mcp-adapters](https://reference.langchain.com/python/langchain-mcp-adapters/). Per-workspace `mcp:` configuration block supports multiple servers per workspace and three transports: `http` (Streamable HTTP — preferred), `sse`, and `stdio` (local subprocess). MCP tools are exposed to the agent alongside builtins, workspace tools, and filesystem tools — they flow through the existing approval middleware and tool-timeout machinery unchanged. Install with `pip install 'openpaw-ai[mcp]'`.
- **`MCPServerConfig` / `WorkspaceMCPConfig`** Pydantic models in `openpaw/core/config/models/mcp.py`. Transport-specific validation rejects mismatched fields at config-load time (e.g. `command:` on an `http` server, `url:` on a `stdio` server). Duplicate server names within a workspace fail loudly. `${ENV_VAR}` expansion works in `headers`/`env` via the existing loader pipeline.
- **`MCPManager`** in `openpaw/runtime/mcp/manager.py` wraps `MultiServerMCPClient`. Connects each configured server independently, applies per-server tool prefixing (default `{server.name}_`, opt out with `tool_prefix: ""`) and allow/deny filters, and honors a per-server `required:` flag — non-required server failures log a warning and skip; required failures abort workspace start. Idempotent `connect()` and clean `close()`.
- **`AgentRunner.update_tools()`** — surgical agent-graph rebuild that mirrors the existing `update_checkpointer()` pattern, used by `WorkspaceRunner.start()` to inject MCP-loaded tools after the async checkpointer is ready.
- New `mcp` extra in `pyproject.toml` pulling `langchain-mcp-adapters >=0.3.0,<1.0.0`. Also added to `all-builtins`. Runtime guard raises an actionable `RuntimeError` with the install hint if MCP is enabled in config but the extra is missing.
- Example `mcp:` block in `example_agent_workspaces/assistant/agent.yaml` covering both an HTTP server with a bearer-token header and a stdio subprocess server. Pointer comment in `config.example.yaml` clarifies MCP is per-workspace, not global.
- 39 unit tests (`tests/test_mcp_config.py`, `tests/test_mcp_manager.py`) plus 12 integration tests (`tests/integration/test_mcp_integration.py`) driving a vendored FastMCP echo server in `tests/fixtures/mcp/` over both stdio and streamable-http. Integration tests cover discovery, invocation, allow/deny filtering, prefix opt-out, multi-server fan-out, and non-required server skip-on-failure.
- 6 regression tests in `tests/test_agent_factory_mcp.py` that lock the contract that `AgentFactory` retains MCP tools across rebuilds (see Fixed). Full suite: 3142 passed.

### Changed

- `create_chat_model()` consolidated to `openpaw/agent/model_factory.py`. The duplicate copy in `openpaw/agent/runner.py` has been removed; `AgentRunner` now imports from `model_factory`. External imports of `create_chat_model`, `THINKING_MODELS`, `BEDROCK_TOOL_NAME_PATTERN`, `MAX_TOOL_NAME_LENGTH`, and `validate_tool_names` from `openpaw.agent.runner` still work via re-export.
- `AgentRunner._validate_tool_names` now delegates to the shared `validate_tool_names` helper in `model_factory`, removing duplicated tool-name validation logic.
- `THINKING_MODELS` trimmed to the single verified Bedrock-routed Kimi entry (`moonshot.kimi-k2-thinking`). The native `moonshot:` provider returns reasoning content via `additional_kwargs`, so it does not need regex stripping by `ThinkingTokenMiddleware`.
- Provider catalog example in `config.example.yaml` updated to show native `moonshot` and `ollama` entries.
- `docs/concepts.md` and `docs/architecture.md` rewritten to describe the native dispatch path through `create_chat_model()` instead of the retired `init_chat_model("openai:kimi-k2.5", ...)` route.
- **Stateless scheduled agents now receive MCP tools.** `create_stateless_agent` and `create_profiled_agent` include the workspace's MCP tools alongside builtins and workspace tools, so cron jobs, heartbeats, and profiled sub-agent spawns can call MCP tools when they fire. Previously MCP tools were omitted from the stateless path by design.
- **Cron `delivery` now defaults to `both`** (was `channel`). The raw cron output still goes to the channel, and the run is also injected into the main agent so it stays aware of what fired. Heartbeat `delivery` still defaults to `channel` (heartbeats fire too often to inject every check-in).
- **`[SYSTEM]`-event terminal replies are now suppressed by default in the main agent.** When the interactive (checkpointed) agent processes a cron/heartbeat/sub-agent/dynamic-task injection, its terminal reply is recorded in conversation history for awareness but is no longer delivered to the user automatically — the agent must call `send_message` to surface anything user-facing. This makes accidental message bombardment structurally impossible. `acknowledge_event` is demoted to an optional audit note on the main-agent path but still gates the heartbeat executor's own delivery.
- Migrated AI code review from the legacy single-pass reviewer to AI Council v0.2.0. (#162)
- Replaced `.github/workflows/ai-code-review.yml` with `.github/workflows/ai-council-review.yml` using `Sosoka-Labs/ai-council-code-review@v0.2.0`.
- Added `.ai-council/config.yaml` tuned for the Python project.

### Removed

- **Legacy Moonshot-via-OpenAI-compat shape** is no longer accepted. Configurations with `provider: openai` + `base_url: https://api.moonshot.ai/v1`, or an `extra_body.thinking` block **under the `openai` provider specifically**, now raise a `ValueError` at workspace load time pointing at the new shape. Anthropic's native extended-thinking via `extra_body.thinking` is unaffected — the validator is scoped to `provider == "openai"` only. **Migration:**
  ```yaml
  # Before (0.4.2 and earlier)
  model:
    provider: openai
    model: kimi-k2.5
    api_key: ${MOONSHOT_API_KEY}
    base_url: https://api.moonshot.ai/v1
    temperature: 0.6
    extra_body:
      thinking:
        type: disabled

  # After (0.4.3)
  model:
    provider: moonshot
    model: kimi-k2.5
    api_key: ${MOONSHOT_API_KEY}
    thinking: false
  ```

### Fixed

- **`AgentFactory.create_agent` was silently dropping MCP tools on rebuild.** Connectors that rebuild the agent after startup (`connect_memory_search_tool` removing `search_conversations` when the vector store is uninitialized; `connect_channel_history_tool` removing `browse_channel_history` when no history-capable channels are connected) call `agent_factory.create_agent()` to construct a fresh `AgentRunner`. The factory's `all_tools` list was `builtin_tools + workspace_tools` only — MCP tools that had been injected directly onto the runner via `update_tools()` were not stored on the factory and were therefore lost. Discovered during live smoke-test on a Telegram workspace: model could see ~56 builtins but never the 29 MCP tools, falling back to `shell` with the MCP tool name as a string argument. Fixed by storing MCP tools on the factory via a new `set_mcp_tools()` method and including them in subsequent rebuilds; `WorkspaceRunner.start()` now calls `set_mcp_tools()` before the connectors run. (At the time of this fix `create_stateless_agent` was intentionally left MCP-free; that limitation has since been removed — see *Changed* below.)
- **MCP tools were unusable on the Fireworks provider.** `langchain-mcp-adapters` returns every tool result as a list of content blocks, and langchain-core stamps each with an `lc_` id. The Fireworks API rejects that shape (`messages[N].content` must be a string; the `id` field is "not permitted"), so any Fireworks workspace using MCP tools failed the moment the agent fed a tool result back to the model. Builtin tools (plain-string results) were unaffected; ollama/moonshot tolerate the block-list. Fixed by bumping `langchain-fireworks` to `>=1.3.1,<1.4.0`, which sanitizes the content blocks provider-side (the maintainers explicitly declined to normalize on the adapter side). The `<1.4.0` cap is deliberate: 1.4.x requires an alpha `fireworks-ai` SDK that relocates `fireworks.client.error` and breaks the provider import. Pulls `langchain-core` 1.2.x → 1.4.x as a transitive consequence (full suite green).
- **Gmail builtin aborted the runner with SIGTRAP under concurrent access.** `GmailProvider` shared a single non-thread-safe `httplib2.Http` transport across the `asyncio.to_thread` workers used for Gmail API calls, so concurrent tool calls (e.g. parallel `check_email` / `send_email`) corrupted the shared connection and crashed the process with SIGTRAP. Fixed by constructing a per-request `Http` transport via the Google API-client `requestBuilder` (isolating each call) and priming the OAuth access token once under a lock so the first burst of concurrent calls does not trigger a refresh herd. (#164)

## [0.4.2] - 2026-06-10

### Added

- **Per-sub-agent status messages** — Each spawned sub-agent now gets its own live status message that is created on dispatch, edited as the sub-agent runs each tool, and finalized to `✅ Completed`, `❌ Failed`, or `🚫 Cancelled` on completion. Gives the user real-time visibility into long-running team members. New `SubAgentToolMiddleware` is injected into each sub-agent's runner; events bridge back to the parent `StatusUpdateMiddleware` via a `status_callback` on `SubAgentRunner`. (#144)
- **`StatusUpdatesConfig.subagent_status`** (default `true`) and **`subagent_status_cleanup`** (`"edit"` / `"delete"`, default `"edit"`) configuration fields to control per-sub-agent status behavior.
- **Automatic status updates** — `StatusUpdateMiddleware` reports agent start, tool usage, and sub-agent dispatch to the user channel with configurable throttling.
- **Live in-place status pattern** — Status updates edit a single message in place instead of sending multiple messages. Supports `edit_message`/`delete_message` on Telegram and Discord. Configurable via `status_updates.edit_in_place` (default: `true`).
- **Run-aware status labels** — First user-message run shows `"Starting work..."`, subsequent runs show `"Continuing work..."`. System events (cron, heartbeat, sub-agent completions) skip the status update to avoid mid-task confusion.
- **`report_progress` builtin tool** — Agent-driven structured progress reporting with `status`, `detail`, and optional `percentage` (0-100).
- **`StatusUpdatesConfig`** configuration model with workspace-level toggles (`agent_start`, `tool_calls_detected`, `tool_start`, `tool_complete`, `subagent_spawned`, `edit_in_place`) and throttling (`min_interval_seconds`, `max_updates_per_run`).
- **Typing indicators** — `status_updates.typing_indicator` (default: `true`) sends a channel typing indicator while the agent is processing.
- **Emoji reactions** — `status_updates.reactions` (default: `true`) adds an emoji reaction to the user's original message to indicate the agent is working. Reactions are removed when the agent finishes.
- **Emoji-enriched status updates** — `status_updates.use_emojis` (default: `true`) prefixes auto-generated status messages with relevant emoji (e.g., `⚙️` for tool calls, `🚀` for starting work, `🤖` for sub-agent dispatch).
- **Optional `emoji` parameter for `report_progress`** — Agents can pass a custom emoji to `report_progress` to prefix the status message with a visual indicator.
- **Steer-mode-aware status notifications** — `StatusUpdateMiddleware` now detects `STEER`, `INTERRUPT`, and `COLLECT` mode events and sends user-facing emoji-prefixed notifications via the existing status message. Messages: `🔄 Redirecting to your new message...`, `🛑 Stopping current run — processing your new message`, `📨 New messages received — bundling...`. Configurable via `steer_redirected`, `run_interrupted`, and `collect_queued` (default: `true`).
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
- `BrowserSession` typed with explicit `Playwright | Browser | BrowserContext | Page` annotations and `_require_page()` / `_require_context()` accessors. Calling a browser tool before launch now raises a clear `RuntimeError("Browser not launched")` instead of an opaque `AttributeError` on `None`.
- Develop CI mypy step is now a hard gate. Previously the step was annotated `continue-on-error: true`, which silently allowed type regressions onto develop and would have failed the publish workflow at tag-push time.

### Removed

- **`status_updates.max_updates_per_run`** configuration field has been removed. The per-agent-run budget cap (default `10`) silently dropped status updates after the budget was exhausted, which produced a "frozen status" UX during tool-heavy runs (e.g., browser sessions with 30+ tool calls). `min_interval_seconds` remains the active throttle; the agent loop's own recursion ceiling caps total iterations.

### Fixed

- Resolved all outstanding mypy errors across the codebase (40 errors → 0). The bulk were in `openpaw/builtins/tools/browser/session.py` from a prior browser refactor where Playwright lifecycle fields were initialized to `None` without `Optional` annotations.
- `StatusUpdateMiddleware` now sends the steer redirect notification exactly once per steer event instead of re-editing the status message for every skipped tool. Adds a `_steer_notified` guard that is reset in `set_context()` and `reset()` so subsequent runs can notify again. (#146)
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

[Unreleased]: https://github.com/johnsosoka/OpenPaw/compare/v0.4.4...HEAD
[0.4.4]: https://github.com/johnsosoka/OpenPaw/compare/v0.4.3...v0.4.4
[0.4.3]: https://github.com/johnsosoka/OpenPaw/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/johnsosoka/OpenPaw/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/johnsosoka/openpaw/releases/tag/v0.4.1
[0.4.0]: https://github.com/johnsosoka/openpaw/releases/tag/v0.4.0
