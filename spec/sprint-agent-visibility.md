# Sprint: Agent Visibility Improvements

**Branch:** `feature/agent-visibility-improvements` (from `develop`)
**Issues:** #56, #29
**Date:** 2026-03-25

---

## Overview

Two complementary features that improve user and agent visibility during long-running operations:

1. **Track 1 (#56):** Silent operation detection — remind agents to use `send_message` when working silently too long
2. **Track 2 (#29):** Sub-agent progress updates — periodic status pings from background workers

Both features are independent and can be implemented in parallel.

---

## Track 1: Silent Operation Detection Middleware (#56)

### Problem

LLMs frequently go silent during multi-turn tool-calling loops. The framework prompt encourages `send_message` usage, but compliance is inconsistent. Users see no activity for minutes during complex tasks.

### Design

Two-class architecture inspired by the `drift_detection` reference implementation in `johnsosoka/code-examples`, adapted to OpenPaw's existing `AgentMiddleware` pattern (same base class as `ThinkingTokenMiddleware`).

**Reference:** `github.com/johnsosoka/code-examples/.../drift_detection/` — provides the three-gate decision model, detector/middleware separation, and non-invasive injection pattern.

#### Class 1: `StatusReminderDetector` (pure logic, no LangChain deps)

**File:** `openpaw/agent/middleware/status_reminder.py`

Stateful tracker that maintains counters per agent run. Three-gate decision logic prevents nagging:

```python
class StatusReminderDetector:
    """Pure detection logic — tracks turns and decides when to intervene."""

    def __init__(self, threshold: int = 5, max_reminders: int = 3, cooldown_turns: int = 1):
        self._threshold = threshold
        self._max_reminders = max_reminders
        self._cooldown_turns = cooldown_turns
        self._turns_since_update = 0
        self._reminders_issued = 0
        self._turns_since_last_reminder = 0

    def record_turn(self, tool_calls: list[str]) -> None:
        """Record an agent turn. Resets counter if send_message was called."""
        if "send_message" in tool_calls:
            self._turns_since_update = 0
        else:
            self._turns_since_update += 1
        self._turns_since_last_reminder += 1

    def should_remind(self) -> bool:
        """Three-gate check: threshold AND budget AND cooldown."""
        if self._turns_since_update < self._threshold:
            return False
        if self._reminders_issued >= self._max_reminders:
            return False
        if self._turns_since_last_reminder < self._cooldown_turns:
            return False
        return True

    def record_reminder(self) -> None:
        self._reminders_issued += 1
        self._turns_since_last_reminder = 0

    def build_reminder(self) -> str:
        return REMINDER_TEMPLATE.format(
            turns=self._turns_since_update,
            remaining=self._max_reminders - self._reminders_issued,
        )

    def reset(self) -> None:
        """Reset all counters between runs."""
        self._turns_since_update = 0
        self._reminders_issued = 0
        self._turns_since_last_reminder = 0
```

#### Class 2: `StatusReminderMiddleware(AgentMiddleware)`

LangChain integration layer. Uses `after_model` to track tool calls, `before_model` to inject reminders.

```python
class StatusReminderMiddleware(AgentMiddleware):
    def __init__(self, config: StatusReminderConfig):
        self._detector = StatusReminderDetector(
            threshold=config.threshold,
            max_reminders=config.max_reminders,
            cooldown_turns=config.cooldown_turns,
        )
        self._enabled = config.enabled

    def before_model(self, state, runtime):
        """If detector says remind, prepend <framework_instruction> to last message."""
        if not self._enabled or not self._detector.should_remind():
            return None
        reminder = self._detector.build_reminder()
        self._detector.record_reminder()
        return inject_framework_instruction(state, reminder)

    def after_model(self, state, runtime):
        """Inspect tool_calls in the latest AIMessage, record the turn."""
        messages = state.get("messages", [])
        if not messages:
            return None
        last = messages[-1]
        if isinstance(last, AIMessage):
            tool_names = [tc.get("name", "") for tc in (last.tool_calls or [])]
            if tool_names:  # Only count turns where tools were called
                self._detector.record_turn(tool_names)
        return None

    def reset(self) -> None:
        """Reset detector state between runs. Called from message_processor."""
        self._detector.reset()
```

**Injection approach:** `inject_framework_instruction(state, text)` prepends a `<framework_instruction>` XML block to the last `ToolMessage` or `HumanMessage` in the state. This is non-invasive — no extra messages added to the checkpoint, the instruction rides along on an existing message. This matches the reference implementation's proven pattern.

```python
def inject_framework_instruction(state: dict, instruction: str) -> dict:
    """Prepend framework instruction to last suitable message in state."""
    messages = list(state.get("messages", []))
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], (ToolMessage, HumanMessage)):
            prefix = f"<framework_instruction>{instruction}</framework_instruction>\n\n"
            messages[i] = messages[i].model_copy(
                update={"content": prefix + messages[i].content}
            )
            state["messages"] = messages
            return state
    return state
```

**Reminder text:**
```
You have completed {turns} tool-calling turns without sending the user a
progress update. Use send_message() to inform them of your current status.
({remaining} reminders remaining this run)
```

#### Configuration

**File:** `openpaw/core/config/models.py`

```python
class StatusReminderConfig(BaseModel):
    enabled: bool = Field(default=True)
    threshold: int = Field(default=5, ge=1, le=50)
    max_reminders: int = Field(default=3, ge=0, le=20)
    cooldown_turns: int = Field(default=1, ge=0, le=10)
```

Add field to `WorkspaceConfig`:
```python
status_reminder: StatusReminderConfig = Field(default_factory=StatusReminderConfig)
```

**Config YAML:**
```yaml
status_reminder:
  enabled: true
  threshold: 5         # turns before first reminder
  max_reminders: 3     # budget per run (prevents nagging)
  cooldown_turns: 1    # spacing between consecutive reminders
```

#### Wiring

**File:** `openpaw/workspace/lifecycle.py` (or `agent_factory.py`)

- Only create middleware if `send_message` builtin is enabled (no point reminding about a tool that doesn't exist)
- Add to middleware list: `[ThinkingTokenMiddleware, StatusReminderMiddleware, queue_middleware, approval_middleware]`
- Order: status reminder runs after thinking token cleanup, before queue/approval
- Call `status_reminder_middleware.reset()` in message_processor's `finally` block (same pattern as queue/approval middleware)

#### Tasks

- [ ] T1.1: Create `StatusReminderDetector` + `StatusReminderMiddleware` + `inject_framework_instruction()` in `openpaw/agent/middleware/status_reminder.py`
- [ ] T1.2: Add `StatusReminderConfig` to `openpaw/core/config/models.py`
- [ ] T1.3: Wire middleware into agent creation (lifecycle/factory) + `reset()` in message_processor
- [ ] T1.4: Write unit tests for detector (three-gate logic, budget, cooldown, reset)
- [ ] T1.5: Write unit tests for middleware (before_model injection, after_model tracking)
- [ ] T1.6: Write unit test for `inject_framework_instruction()` helper

#### Acceptance Criteria

- [ ] After N tool-calling turns without `send_message`, a `<framework_instruction>` reminder is injected
- [ ] Threshold is configurable via `status_reminder.threshold` in config
- [ ] `max_reminders` budget prevents infinite nagging (default: 3 per run)
- [ ] `cooldown_turns` prevents back-to-back reminders (default: 1)
- [ ] `enabled: false` disables the middleware entirely
- [ ] Middleware only active when `send_message` builtin is loaded
- [ ] Injection is non-invasive (prepended to existing message, no new checkpoint entries)
- [ ] Detector state resets between runs (no cross-run bleed)
- [ ] No reminder on first few turns (respects threshold)
- [ ] Cron/heartbeat/sub-agent runs are NOT affected (they don't have send_message)

---

## Track 2: Sub-Agent Periodic Progress Updates (#29)

### Problem

When the main agent spawns long-running sub-agents (10-30+ min), it has zero visibility into progress. The only notifications are terminal events (completed/failed/timed_out). The main agent can call `list_subagents` to see status, but gets no insight into what the sub-agent is currently doing.

### Design

Add an optional `progress_interval_minutes` parameter to `spawn_agent`. When set, an asyncio timer task runs alongside the sub-agent and periodically injects `[SYSTEM]` progress events into the main agent's queue using the existing `result_callback` path.

#### Model Changes

**File:** `openpaw/model/subagent.py`

Add to `SubAgentRequest`:
```python
progress_interval_minutes: int = 0  # 0 = disabled
```

Update `to_dict()` and `from_dict()` accordingly. Omit from dict when 0 (like `origin`).

#### Progress Timer

**File:** `openpaw/runtime/subagent/runner.py`

New method on `SubAgentRunner`:

```python
async def _progress_timer(
    self,
    request: SubAgentRequest,
    runner: AgentRunner,
    start_time: float,
) -> None:
    """Emit periodic progress updates for a running sub-agent."""
    interval_seconds = request.progress_interval_minutes * 60

    while True:
        await asyncio.sleep(interval_seconds)

        elapsed_seconds = time.monotonic() - start_time
        tools_used = list(runner._last_tools_used) if runner._last_tools_used else []
        current_tool = runner._current_tool_name or "thinking"

        content = SUBAGENT_PROGRESS_TEMPLATE.format(
            label=request.label,
            elapsed=_format_elapsed(elapsed_seconds),
            tools_summary=", ".join(tools_used[-5:]) if tools_used else "none yet",
            current_activity=current_tool,
            total_tools=len(tools_used),
            origin_suffix=self._build_origin_suffix(request),
        )

        if self._result_callback:
            try:
                await self._result_callback(request.session_key, content)
            except Exception as e:
                logger.warning(f"Failed to send progress for {request.id}: {e}")
```

**Integration in `_execute_subagent()`:**

```python
# After runner is created and configured, before the agent run:
progress_task = None
if request.progress_interval_minutes > 0:
    progress_task = asyncio.create_task(
        self._progress_timer(request, runner, start_time)
    )

try:
    async with asyncio.timeout(request.timeout_minutes * 60):
        response = await runner.run(message=request.task)
finally:
    if progress_task:
        progress_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await progress_task
```

**Key properties read from runner during execution:**
- `runner._last_tools_used` — list populated incrementally by the streaming loop
- `runner._current_tool_name` — last tool call seen in stream updates
- Both are safe to read concurrently (list append is atomic, string assignment is atomic)

#### System Event Template

**File:** `openpaw/core/prompts/system_events.py`

```python
SUBAGENT_PROGRESS_TEMPLATE = PromptTemplate(
    template=(
        "[SYSTEM] Sub-agent '{label}' progress update{origin_suffix}.\n"
        "Elapsed: {elapsed} | Tools called: {total_tools}\n"
        "Recent tools: {tools_summary}\n"
        "Currently: {current_activity}"
    ),
    input_variables=["label", "elapsed", "total_tools", "tools_summary",
                     "current_activity", "origin_suffix"],
)
```

#### Spawn Tool Changes

**File:** `openpaw/builtins/tools/spawn.py`

Add parameter to `spawn_agent`:
```python
def spawn_agent(
    task: str,
    label: str,
    timeout_minutes: int = 30,
    notify: bool = True,
    progress_interval_minutes: int = 0,  # NEW
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
) -> str:
```

Pass `progress_interval_minutes` through to `SubAgentRequest` creation.

**Validation:** Minimum interval of 1 minute (prevent spam). Value of 0 disables. Clamp to max `timeout_minutes` (can't report progress after timeout).

#### Configuration

**File:** `openpaw/core/config/models.py`

Add to `SpawnBuiltinConfig`:
```python
default_progress_interval: int = Field(
    default=0,
    ge=0,
    description="Default progress interval in minutes (0 = disabled)"
)
```

The `spawn_agent` tool uses this as default when `progress_interval_minutes` is not explicitly set by the agent.

#### Helper: `_build_origin_suffix`

Extract the existing origin suffix logic from `_format_notification` into a shared method `_build_origin_suffix(request)` to avoid duplication between notification and progress formatting.

#### Tasks

- [ ] T2.1: Add `progress_interval_minutes` to `SubAgentRequest` model
- [ ] T2.2: Add `SUBAGENT_PROGRESS_TEMPLATE` to system_events.py
- [ ] T2.3: Implement `_progress_timer()` and wire into `_execute_subagent()`
- [ ] T2.4: Add parameter to `spawn_agent` tool + validation
- [ ] T2.5: Add `default_progress_interval` to spawn config
- [ ] T2.6: Extract `_build_origin_suffix()` helper (refactor)
- [ ] T2.7: Write unit tests (timer lifecycle, message format, cancellation, interval validation)

#### Acceptance Criteria

- [ ] `spawn_agent(task=..., progress_interval_minutes=5)` sends progress every 5 min
- [ ] Progress messages use `[SYSTEM]` prefix and include elapsed time, tools used, current tool
- [ ] Timer is cancelled on completion, failure, timeout, and cancellation
- [ ] `progress_interval_minutes=0` (default) preserves current behavior (no progress)
- [ ] Minimum interval enforced (1 minute)
- [ ] Progress uses same `result_callback` path as completion notifications
- [ ] Reading `runner._last_tools_used` / `_current_tool_name` is safe (no locking needed)
- [ ] Config `default_progress_interval` works as workspace-level default

---

## Implementation Order

1. **Track 1 & Track 2 can run in parallel** (independent code paths)
2. Within each track, follow task order (model → template → logic → wiring → tests)
3. Code review after both tracks complete
4. Update CLAUDE.md documentation sections
5. Close issues #56 and #29 with comments

## Files Modified

### Track 1 (new + modified)
- `openpaw/agent/middleware/status_reminder.py` (NEW)
- `openpaw/core/config/models.py` (add StatusReminderConfig)
- `openpaw/workspace/agent_factory.py` or `lifecycle.py` (wire middleware)
- `tests/test_status_reminder.py` (NEW)

### Track 2 (modified)
- `openpaw/model/subagent.py` (add field)
- `openpaw/core/prompts/system_events.py` (add template)
- `openpaw/runtime/subagent/runner.py` (timer + refactor)
- `openpaw/builtins/tools/spawn.py` (add param)
- `openpaw/core/config/models.py` (spawn config)
- `tests/test_subagent_progress.py` (NEW)

## Risk Assessment

- **Track 1:** Low risk. Middleware is additive, stateless scanning, disabled by default on cron/heartbeat. Worst case: reminder is slightly annoying (tunable threshold).
- **Track 2:** Low-medium risk. Timer reads runner state concurrently — but only reads (no writes), and Python's GIL ensures atomic reads. Timer cancellation is standard asyncio pattern. Worst case: progress message arrives slightly after completion (benign race).
