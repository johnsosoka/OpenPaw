"""Tests for module selection (resolve_module) and the module registry (ADR-102 §2)."""

from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from openpaw.agent.harness.modules.base import (
    ModuleKind,
    ReasoningArtifact,
    ReasoningContext,
    ReasoningModule,
)
from openpaw.agent.harness.modules.direct import DirectPlanner
from openpaw.agent.harness.modules.reflection import FullReflection, LightReflection
from openpaw.agent.harness.modules.registry import (
    KIND_DEFAULTS,
    MODULE_REGISTRY,
    candidates_for,
    get_module_class,
)
from openpaw.agent.harness.modules.selector import _ModuleChoice, resolve_module
from openpaw.model.status_event import StatusEvent, StatusEventKind


class CaptureEmitter:
    """In-memory StatusEmitter for assertions."""

    def __init__(self) -> None:
        self.events: list[StatusEvent] = []

    async def emit(self, event: StatusEvent) -> None:
        self.events.append(event)


class FakeStructuredModel:
    """Fake chat model: with_structured_output(...).ainvoke returns canned outputs in order."""

    def __init__(self, *outputs: object) -> None:
        self._outputs = list(outputs)
        self.prompts: list[str] = []

    def with_structured_output(self, schema: type) -> "FakeStructuredModel":
        return self

    async def ainvoke(self, messages: list[BaseMessage]) -> object:
        self.prompts.append(str(messages[0].content))
        output = self._outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output

    @property
    def call_count(self) -> int:
        return len(self.prompts)


class StubModule:
    """Minimal ReasoningModule for selector tests."""

    def __init__(self, name: str, kind: ModuleKind, tagline: str = "stub tagline") -> None:
        self.name = name
        self.kind = kind
        self.tagline = tagline

    async def run(self, ctx: ReasoningContext) -> ReasoningArtifact:
        raise NotImplementedError


def reflection_candidates() -> dict[str, ReasoningModule]:
    return {
        "light": StubModule("light", ModuleKind.REFLECTION, "fast outcome check"),
        "full": StubModule("full", ModuleKind.REFLECTION, "deep plan rewrite"),
        "extra": StubModule("extra", ModuleKind.REFLECTION, "experimental depth"),
    }


async def resolve(
    configured: str,
    *,
    allowed: list[str] | None = None,
    candidates: dict[str, ReasoningModule] | None = None,
    model: FakeStructuredModel | None = None,
    emitter: CaptureEmitter | None = None,
) -> tuple[ReasoningModule, CaptureEmitter, FakeStructuredModel]:
    emitter = emitter or CaptureEmitter()
    model = model or FakeStructuredModel()
    chosen = await resolve_module(
        configured=configured,
        allowed=allowed,
        candidates=candidates if candidates is not None else reflection_candidates(),
        kind=ModuleKind.REFLECTION,
        task="Refactor the billing module",
        selector_model=cast(BaseChatModel, model),
        emit=emitter,
        workspace="testws",
        run_id="run-1",
        session_key="telegram:123",
    )
    return chosen, emitter, model


def assert_selected_event(emitter: CaptureEmitter, module: str, reason: str) -> None:
    assert len(emitter.events) == 1
    event = emitter.events[0]
    assert event.kind == StatusEventKind.MODULE_SELECTED
    assert event.node == "reflection"
    assert event.workspace == "testws"
    assert event.run_id == "run-1"
    assert event.session_key == "telegram:123"
    assert event.payload == {"kind": "reflection", "module": module, "reason": reason}


# ---------------------------------------------------------------------------
# resolve_module — the three paths + failure modes
# ---------------------------------------------------------------------------


async def test_pinned_binds_without_model_call():
    chosen, emitter, model = await resolve("full")

    assert chosen.name == "full"
    assert model.call_count == 0
    assert_selected_event(emitter, "full", "pinned")


async def test_pinned_unknown_name_raises():
    emitter = CaptureEmitter()
    with pytest.raises(ValueError, match="not available"):
        await resolve("nonexistent", emitter=emitter)
    assert emitter.events == []


async def test_auto_single_candidate_short_circuits():
    chosen, emitter, model = await resolve("auto", allowed=["full"])

    assert chosen.name == "full"
    assert model.call_count == 0  # no LLM call on the short-circuit path
    assert_selected_event(emitter, "full", "only candidate")


async def test_auto_multiple_candidates_uses_selector_model():
    model = FakeStructuredModel(_ModuleChoice(module="full", reason="long fragile plan"))
    chosen, emitter, model = await resolve("auto", model=model)

    assert chosen.name == "full"
    assert model.call_count == 1
    assert_selected_event(emitter, "full", "long fragile plan")

    prompt = model.prompts[0]
    assert "Refactor the billing module" in prompt
    assert "- light: fast outcome check" in prompt
    assert "- full: deep plan rewrite" in prompt


async def test_auto_allowed_filters_catalog():
    model = FakeStructuredModel(_ModuleChoice(module="light", reason="cheap"))
    chosen, _, model = await resolve("auto", allowed=["light", "full"], model=model)

    assert chosen.name == "light"
    prompt = model.prompts[0]
    assert "extra" not in prompt  # filtered candidate never presented


async def test_auto_selector_exception_falls_back_to_kind_default():
    model = FakeStructuredModel(RuntimeError("model exploded"))
    chosen, emitter, _ = await resolve("auto", model=model)

    assert chosen.name == "light"  # KIND_DEFAULTS[REFLECTION]
    assert_selected_event(emitter, "light", "selector failed; kind default")


async def test_auto_selector_unknown_module_falls_back_to_kind_default():
    model = FakeStructuredModel(_ModuleChoice(module="made_up", reason="hallucinated"))
    chosen, emitter, _ = await resolve("auto", model=model)

    assert chosen.name == "light"
    assert_selected_event(emitter, "light", "selector failed; kind default")


async def test_auto_empty_pool_after_allowed_filter_raises():
    with pytest.raises(ValueError, match="No reflection module candidates"):
        await resolve("auto", allowed=["nonexistent"])


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_contents():
    assert MODULE_REGISTRY["direct"] is DirectPlanner
    assert MODULE_REGISTRY["light"] is LightReflection
    assert MODULE_REGISTRY["full"] is FullReflection


def test_candidates_for_kind():
    from openpaw.agent.harness.modules.ideonomy import IdeonomyModule
    from openpaw.agent.harness.modules.self_discover import SelfDiscoverPlanner

    assert candidates_for(ModuleKind.PLANNING) == {
        "direct": DirectPlanner,
        "self_discover": SelfDiscoverPlanner,
    }
    assert candidates_for(ModuleKind.REFLECTION) == {"light": LightReflection, "full": FullReflection}
    assert candidates_for(ModuleKind.CREATIVE) == {"ideonomy": IdeonomyModule}


def test_kind_defaults():
    assert KIND_DEFAULTS[ModuleKind.PLANNING] == "direct"
    assert KIND_DEFAULTS[ModuleKind.REFLECTION] == "light"


def test_get_module_class():
    assert get_module_class("direct") is DirectPlanner
    with pytest.raises(ValueError, match="Unknown reasoning module"):
        get_module_class("bogus")
