"""Tests for the Phase 2 learning loop (PRD-001 F2.x, T4.4).

Covers the LearningEvaluator (counter cadence, debounce, budget gate,
evaluation -> builder -> store pipeline, failure containment, events),
the SkillChannelSink channel rendering, the MessageProcessor hook, and
the WorkspaceRunner wiring gate.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.agent.metrics import InvocationMetrics
from openpaw.agent.middleware.status_update import StatusUpdateMiddleware
from openpaw.core.config.models import WorkspaceConfig
from openpaw.core.config.models.learning import LearningConfig
from openpaw.core.config.models.status_updates import StatusUpdatesConfig
from openpaw.core.workspace import AgentWorkspace
from openpaw.model.message import Message, MessageDirection
from openpaw.model.skill import SkillCreatedBy, SkillInfo
from openpaw.model.status_event import StatusEvent, StatusEventKind
from openpaw.model.subagent import SubAgentResult, SubAgentStatus
from openpaw.runtime.learning import (
    SKILL_BUILDER_PROFILE_NAME,
    LearningEvaluator,
    build_skill_builder_profile,
)
from openpaw.runtime.learning.evaluator import SkillProposal, _strip_fences
from openpaw.runtime.status_bus import SkillChannelSink
from openpaw.stores.skill import SkillRejectedError, SkillValidationError
from openpaw.workspace.message_processor import MessageProcessor
from openpaw.workspace.runner import WorkspaceRunner

GUIDE_BODY = "AUTHORING GUIDE BODY: one reusable procedure per skill."


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeEmitter:
    """Records emitted StatusEvents."""

    def __init__(self) -> None:
        self.events: list[StatusEvent] = []

    async def emit(self, event: StatusEvent) -> None:
        self.events.append(event)

    def kinds(self) -> list[StatusEventKind]:
        return [e.kind for e in self.events]


class FakeUsageReader:
    """Returns a fixed daily token total."""

    def __init__(self, total_tokens: int = 0) -> None:
        self._total = total_tokens

    def tokens_today(self, timezone_str: str = "UTC") -> InvocationMetrics:
        return InvocationMetrics(total_tokens=self._total)


class FakeStructuredModel:
    """Fake chat model whose structured-output call returns a proposal."""

    def __init__(self, proposal: SkillProposal) -> None:
        self._proposal = proposal
        self.prompts: list[str] = []

    def with_structured_output(self, schema: Any) -> "FakeStructuredModel":
        return self

    async def ainvoke(self, prompt: str) -> SkillProposal:
        self.prompts.append(prompt)
        return self._proposal


@dataclass
class FakeSkillStore:
    """Records create/update calls; optionally rejects."""

    reject: bool = False
    create_calls: list[dict[str, Any]] = field(default_factory=list)
    update_calls: list[dict[str, Any]] = field(default_factory=list)

    async def create(self, **kwargs: Any) -> None:
        if self.reject:
            raise SkillRejectedError(
                [SkillValidationError("budget", "too many tokens")]
            )
        self.create_calls.append(kwargs)

    async def update(self, **kwargs: Any) -> None:
        self.update_calls.append(kwargs)


class FakeSubAgentRunner:
    """Completes every spawned request immediately with a fixed output."""

    def __init__(self, output: str = "# Skill body\n\nDo the thing.") -> None:
        self.output = output
        self.spawned: list[Any] = []

    async def spawn(self, request: Any) -> str:
        self.spawned.append(request)
        return str(request.id)

    async def get_status(self, request_id: str) -> Any:
        request = self.spawned[-1]
        request.status = SubAgentStatus.COMPLETED
        return request

    async def get_result(self, request_id: str) -> SubAgentResult:
        return SubAgentResult(request_id=request_id, output=self.output)


class FakeSubAgentStore:
    def __init__(self) -> None:
        self.created: list[Any] = []

    async def create(self, request: Any) -> None:
        self.created.append(request)


def make_skill(name: str, description: str = "", content: str = "") -> SkillInfo:
    return SkillInfo(
        name=name, description=description, content=content, path=Path(f"/tmp/{name}")
    )


def make_config(every_n: int = 3, daily_tokens: int = 100_000) -> LearningConfig:
    return LearningConfig.model_validate(
        {
            "enabled": True,
            "phase2": {"enabled": True, "every_n_runs": every_n, "approval": "staged"},
            "budget": {"daily_tokens": daily_tokens},
        }
    )


def make_evaluator(
    proposal: SkillProposal | None = None,
    skills: list[SkillInfo] | None = None,
    tokens_used: int = 0,
    skill_store: FakeSkillStore | None = None,
    every_n: int = 3,
    model_factory: Any = None,
) -> tuple[LearningEvaluator, FakeEmitter, FakeSkillStore, FakeStructuredModel]:
    emitter = FakeEmitter()
    store = skill_store or FakeSkillStore()
    model = FakeStructuredModel(proposal or SkillProposal())
    all_skills = [make_skill("skill-authoring", "guide", GUIDE_BODY)] + (skills or [])
    evaluator = LearningEvaluator(
        workspace_name="testspace",
        config=make_config(every_n=every_n),
        skill_store=store,  # type: ignore[arg-type]
        usage_reader=FakeUsageReader(tokens_used),  # type: ignore[arg-type]
        model_factory=model_factory or (lambda: model),
        skills_provider=lambda: all_skills,
        emitter=emitter,
        poll_interval_seconds=0.0,
    )
    return evaluator, emitter, store, model


def wire_builder(
    evaluator: LearningEvaluator, output: str = "# Skill body\n\nDo the thing."
) -> tuple[FakeSubAgentRunner, FakeSubAgentStore]:
    runner = FakeSubAgentRunner(output)
    store = FakeSubAgentStore()
    evaluator.set_subagent_runner(runner, store)  # type: ignore[arg-type]
    return runner, store


# ---------------------------------------------------------------------------
# Counter cadence + debounce
# ---------------------------------------------------------------------------


async def test_counter_fires_at_every_n_and_resets() -> None:
    evaluator, _, _, _ = make_evaluator(every_n=3)
    calls = 0

    async def fake_evaluate() -> None:
        nonlocal calls
        calls += 1

    evaluator._evaluate = fake_evaluate  # type: ignore[method-assign]

    for _ in range(2):
        evaluator.record_run("u", "r")
    await asyncio.sleep(0)
    assert calls == 0

    evaluator.record_run("u", "r")
    await asyncio.sleep(0)
    assert calls == 1
    assert evaluator._run_count == 0  # counter reset

    for _ in range(3):
        evaluator.record_run("u", "r")
    await asyncio.sleep(0)
    assert calls == 2


async def test_debounce_skips_when_evaluation_in_flight() -> None:
    evaluator, _, _, _ = make_evaluator(every_n=1)
    release = asyncio.Event()
    calls = 0

    async def slow_evaluate() -> None:
        nonlocal calls
        calls += 1
        await release.wait()

    evaluator._evaluate = slow_evaluate  # type: ignore[method-assign]

    evaluator.record_run("u", "r")
    await asyncio.sleep(0)
    evaluator.record_run("u", "r")  # in-flight -> skipped
    await asyncio.sleep(0)
    assert calls == 1

    release.set()
    assert evaluator._inflight is not None
    await evaluator._inflight

    evaluator.record_run("u", "r")  # previous done -> fires again
    await asyncio.sleep(0)
    assert calls == 2


async def test_record_run_never_raises_on_internal_failure() -> None:
    evaluator, _, _, _ = make_evaluator(every_n=1)
    # Force an internal failure: config access inside record_run blows up.
    evaluator._config = None  # type: ignore[assignment]
    evaluator.record_run("u", "r")  # must not raise (F2.4)


# ---------------------------------------------------------------------------
# Budget gate
# ---------------------------------------------------------------------------


async def test_budget_exhausted_skips_quietly() -> None:
    model_calls = 0

    def counting_factory() -> Any:
        nonlocal model_calls
        model_calls += 1
        return FakeStructuredModel(SkillProposal())

    evaluator, emitter, _, _ = make_evaluator(
        tokens_used=200_000, model_factory=counting_factory
    )
    await evaluator._evaluate()

    assert model_calls == 0
    assert emitter.kinds() == [StatusEventKind.LEARNING_EVALUATION_COMPLETED]
    assert emitter.events[0].payload["skipped"] == "budget"


# ---------------------------------------------------------------------------
# Evaluation pipeline
# ---------------------------------------------------------------------------


async def test_happy_path_create_flows_to_store() -> None:
    proposal = SkillProposal(
        action="create",
        skill_name="digest-format",
        description="How to format digests",
        rationale="User corrected the format twice",
    )
    evaluator, emitter, skill_store, model = make_evaluator(proposal=proposal)
    runner, sub_store = wire_builder(evaluator)
    evaluator.record_run("please format it differently", "done")

    await evaluator._evaluate()

    # Evaluation prompt listed existing skills and the digest
    assert "skill-authoring" in model.prompts[0]
    assert "please format it differently" in model.prompts[0]

    # Builder spawned with the framework profile and authoring-guide prompt
    assert len(runner.spawned) == 1
    request = runner.spawned[0]
    assert request.profile == SKILL_BUILDER_PROFILE_NAME
    assert request.notify is False
    assert GUIDE_BODY in request.task
    assert "digest-format" in request.task
    assert sub_store.created == [request]

    # Store submission: MIDDLEWARE provenance + staged approval
    assert len(skill_store.create_calls) == 1
    call = skill_store.create_calls[0]
    assert call["name"] == "digest-format"
    assert call["created_by"] is SkillCreatedBy.MIDDLEWARE
    assert call["approval"] == "staged"
    assert call["source"].startswith("learning:phase2:")
    assert call["content"] == "# Skill body\n\nDo the thing."

    # Events: started then completed with the outcome
    assert emitter.kinds() == [
        StatusEventKind.LEARNING_EVALUATION_STARTED,
        StatusEventKind.LEARNING_EVALUATION_COMPLETED,
    ]
    assert emitter.events[1].payload["outcome"] == "created"
    assert emitter.events[0].payload["evaluation_id"] == (
        emitter.events[1].payload["evaluation_id"]
    )


async def test_update_includes_existing_content_and_calls_update() -> None:
    proposal = SkillProposal(
        action="update", skill_name="old-skill", description="d", rationale="r"
    )
    existing = make_skill("old-skill", "old desc", "OLD SKILL CONTENT")
    evaluator, _, skill_store, _ = make_evaluator(proposal=proposal, skills=[existing])
    runner, _ = wire_builder(evaluator)

    await evaluator._evaluate()

    assert "OLD SKILL CONTENT" in runner.spawned[0].task
    assert len(skill_store.update_calls) == 1
    assert skill_store.update_calls[0]["name"] == "old-skill"
    assert skill_store.update_calls[0]["created_by"] is SkillCreatedBy.MIDDLEWARE


async def test_action_none_is_a_noop() -> None:
    evaluator, emitter, skill_store, _ = make_evaluator(
        proposal=SkillProposal(action="none")
    )
    runner, _ = wire_builder(evaluator)

    await evaluator._evaluate()

    assert runner.spawned == []
    assert skill_store.create_calls == []
    assert emitter.events[-1].payload["outcome"] == "none"


async def test_gate_rejection_is_logged_not_raised() -> None:
    proposal = SkillProposal(action="create", skill_name="bad-skill")
    evaluator, emitter, _, _ = make_evaluator(
        proposal=proposal, skill_store=FakeSkillStore(reject=True)
    )
    wire_builder(evaluator)

    await evaluator._evaluate()

    assert emitter.events[-1].payload["outcome"] == "rejected"
    assert emitter.events[-1].payload["skill"] == "bad-skill"


async def test_evaluation_failure_is_swallowed() -> None:
    def broken_factory() -> Any:
        raise RuntimeError("model exploded")

    evaluator, emitter, _, _ = make_evaluator(model_factory=broken_factory)

    await evaluator._evaluate()  # must not raise

    assert emitter.kinds() == [
        StatusEventKind.LEARNING_EVALUATION_STARTED,
        StatusEventKind.LEARNING_EVALUATION_COMPLETED,
    ]
    assert emitter.events[-1].payload["outcome"] == "error"


async def test_builder_error_reported_as_builder_failed() -> None:
    proposal = SkillProposal(action="create", skill_name="a-skill")
    evaluator, emitter, skill_store, _ = make_evaluator(proposal=proposal)
    runner, _ = wire_builder(evaluator)

    async def failed_result(request_id: str) -> SubAgentResult:
        return SubAgentResult(request_id=request_id, output="", error="boom")

    runner.get_result = failed_result  # type: ignore[method-assign]

    await evaluator._evaluate()

    assert skill_store.create_calls == []
    assert emitter.events[-1].payload["outcome"] == "builder_failed"


async def test_no_subagent_runner_skips_build() -> None:
    proposal = SkillProposal(action="create", skill_name="a-skill")
    evaluator, emitter, skill_store, _ = make_evaluator(proposal=proposal)
    # set_subagent_runner never called

    await evaluator._evaluate()

    assert skill_store.create_calls == []
    assert emitter.events[-1].payload["skipped"] == "no_subagent_runner"


def test_strip_fences() -> None:
    assert _strip_fences("```markdown\n# Body\n```") == "# Body"
    assert _strip_fences("# Body") == "# Body"
    assert _strip_fences("  # Body \n") == "# Body"


def test_skill_builder_profile_shape() -> None:
    profile = build_skill_builder_profile()
    assert profile.name == SKILL_BUILDER_PROFILE_NAME
    assert profile.temperature == 0.2
    assert profile.allowed_tools == ["read_file"]
    assert profile.source == "system"


# ---------------------------------------------------------------------------
# Skill channel sink rendering (F4.1)
# ---------------------------------------------------------------------------


def _skill_event(
    kind: StatusEventKind = StatusEventKind.SKILL_CREATED,
    session_key: str | None = None,
) -> StatusEvent:
    return StatusEvent(
        kind=kind,
        workspace="testspace",
        session_key=session_key,
        run_id="run1",
        node="skill_store",
        payload={"name": "digest-format", "version": 1, "created_by": "agent"},
    )


def _armed_middleware() -> tuple[StatusUpdateMiddleware, MagicMock]:
    channel = MagicMock()
    sent = MagicMock()
    sent.id = "msg1"
    channel.send_message = AsyncMock(return_value=sent)
    middleware = StatusUpdateMiddleware(StatusUpdatesConfig(enabled=True))
    middleware.set_context(channel, "telegram:123")
    return middleware, channel


async def test_skill_sink_renders_forced_one_liner() -> None:
    middleware, channel = _armed_middleware()
    sink = SkillChannelSink(middleware)

    await sink.handle(_skill_event())

    channel.send_message.assert_awaited_once()
    text = channel.send_message.await_args.args[1]
    assert text == "🧠 Skill created: digest-format (by agent)"


async def test_skill_sink_ignores_non_skill_events() -> None:
    middleware, channel = _armed_middleware()
    sink = SkillChannelSink(middleware)

    await sink.handle(
        StatusEvent(
            kind=StatusEventKind.TOOL_STARTED,
            workspace="testspace",
            session_key=None,
            run_id="run1",
        )
    )

    channel.send_message.assert_not_awaited()


async def test_skill_status_skipped_without_armed_context() -> None:
    middleware = StatusUpdateMiddleware(StatusUpdatesConfig(enabled=True))
    # no set_context — background path with no armed channel
    await middleware.send_skill_status(_skill_event())  # must not raise


async def test_skill_status_skipped_on_session_mismatch() -> None:
    middleware, channel = _armed_middleware()

    await middleware.send_skill_status(_skill_event(session_key="telegram:999"))

    channel.send_message.assert_not_awaited()


async def test_skill_status_verbs_cover_all_lifecycle_kinds() -> None:
    middleware, channel = _armed_middleware()
    for kind, verb in [
        (StatusEventKind.SKILL_UPDATED, "Skill updated"),
        (StatusEventKind.SKILL_STAGED, "Skill staged for approval"),
        (StatusEventKind.SKILL_EQUIPPED, "Skill equipped"),
    ]:
        channel.send_message.reset_mock()
        middleware._status_message_id = None  # force fresh send, not edit
        await middleware.send_skill_status(_skill_event(kind=kind))
        text = channel.send_message.await_args.args[1]
        assert verb in text


# ---------------------------------------------------------------------------
# MessageProcessor hook (F2.1 call site)
# ---------------------------------------------------------------------------


def _make_processor(recorder: Any) -> MessageProcessor:
    qm = MagicMock()
    qm.get_session_mode = AsyncMock(return_value=None)
    qm.peek_pending = AsyncMock(return_value=False)
    qm.consume_pending = AsyncMock(return_value=None)

    sm = MagicMock()
    sm.get_thread_id = MagicMock(return_value="telegram:123:conv1")
    sm.increment_message_count = MagicMock()
    sm.is_session_expired = MagicMock(return_value=False)

    bl = MagicMock()
    bl.get_tool_instance = MagicMock(return_value=None)

    qmw = MagicMock()
    qmw.was_steered = False
    qmw.pending_steer_message = None

    agent_runner = MagicMock()
    agent_runner.run = AsyncMock(return_value="the response")
    agent_runner.last_metrics = None
    agent_runner.last_tools_used = []

    return MessageProcessor(
        agent_runner=agent_runner,
        session_manager=sm,
        queue_manager=qm,
        builtin_loader=bl,
        queue_middleware=qmw,
        approval_middleware=MagicMock(),
        approval_manager=None,
        workspace_name="testspace",
        token_logger=MagicMock(),
        logger=logging.getLogger("test"),
        learning_recorder=recorder,
    )


def _message(user_id: str = "42", content: str = "hello there") -> Message:
    return Message(
        id="1",
        channel="telegram",
        session_key="telegram:123",
        user_id=user_id,
        content=content,
        direction=MessageDirection.INBOUND,
        timestamp=datetime.now(UTC),
    )


async def test_hook_invoked_after_successful_user_batch() -> None:
    recorder = MagicMock()
    processor = _make_processor(recorder)
    channel = MagicMock()
    channel.send_message = AsyncMock()

    await processor.process_messages("telegram:123", [_message()], channel)

    recorder.assert_called_once()
    user_content, response = recorder.call_args.args
    assert "hello there" in user_content
    assert response == "the response"


async def test_hook_not_invoked_for_system_batch() -> None:
    recorder = MagicMock()
    processor = _make_processor(recorder)
    channel = MagicMock()
    channel.send_message = AsyncMock()

    await processor.process_messages(
        "telegram:123", [_message(user_id="system", content="[SYSTEM] cron")], channel
    )

    recorder.assert_not_called()


async def test_hook_not_invoked_on_agent_error() -> None:
    recorder = MagicMock()
    processor = _make_processor(recorder)
    processor._agent_runner.run = AsyncMock(side_effect=RuntimeError("boom"))
    channel = MagicMock()
    channel.send_message = AsyncMock()

    await processor.process_messages("telegram:123", [_message()], channel)

    recorder.assert_not_called()


# ---------------------------------------------------------------------------
# WorkspaceRunner wiring gate (F2.5 — disabled by default)
# ---------------------------------------------------------------------------


def _make_workspace(tmp_path: Path, learning: dict[str, Any]) -> AgentWorkspace:
    skills_path = tmp_path / "agent" / "skills"
    skills_path.mkdir(parents=True, exist_ok=True)
    return AgentWorkspace(
        name="wiring-test",
        path=tmp_path,
        agent_md="",
        user_md="",
        soul_md="",
        heartbeat_md="",
        skills_path=skills_path,
        tools_path=tmp_path / "tools",
        config=WorkspaceConfig.model_validate({"learning": learning}),
    )


@pytest.fixture
def stub_runner(tmp_path: Path) -> MagicMock:
    stub = MagicMock()
    stub.workspace_name = "wiring-test"
    stub.logger = logging.getLogger("test-wiring")
    stub._agent_factory = MagicMock()
    stub._agent_factory.status_emitter = None
    stub._skill_store = MagicMock()
    return stub


def test_no_evaluator_when_phase2_disabled(
    stub_runner: MagicMock, tmp_path: Path
) -> None:
    stub_runner._workspace = _make_workspace(tmp_path, {"enabled": True})
    assert WorkspaceRunner._init_learning_evaluator(stub_runner) is None


def test_no_evaluator_without_skill_store(
    stub_runner: MagicMock, tmp_path: Path
) -> None:
    stub_runner._workspace = _make_workspace(
        tmp_path, {"enabled": True, "phase2": {"enabled": True}}
    )
    stub_runner._skill_store = None
    assert WorkspaceRunner._init_learning_evaluator(stub_runner) is None


def test_evaluator_built_when_phase2_enabled(
    stub_runner: MagicMock, tmp_path: Path
) -> None:
    stub_runner._workspace = _make_workspace(
        tmp_path,
        {"enabled": True, "phase2": {"enabled": True, "every_n_runs": 5}},
    )
    evaluator = WorkspaceRunner._init_learning_evaluator(stub_runner)
    assert isinstance(evaluator, LearningEvaluator)
    assert evaluator._config.phase2.every_n_runs == 5
