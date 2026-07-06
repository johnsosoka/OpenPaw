"""Per-kind module selection (ADR-102 §2) — pinned | auto [+ allowed].

Three-path resolution, evaluated at graph-build time per kind:

1. Pinned name -> direct bind (zero cost; unknown name is a config error).
2. ``auto`` with exactly one candidate after ``allowed:`` filtering ->
   short-circuit bind, no LLM call.
3. ``auto`` with >=2 candidates -> one structured-output call over the
   candidates' taglines; any failure (exception, unknown name returned)
   falls back to the kind's registry default (fail-open, mirroring triage).

Every resolution path emits ``module.selected`` (ADR-106) so the assembled
harness is always observable in the session log. Emission rides the custom
stream (ADR-110) — resolve_module always runs inside streamed graph nodes.
"""

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from openpaw.agent.harness.modules.base import ModuleKind, ReasoningModule, emit_status
from openpaw.agent.harness.modules.registry import KIND_DEFAULTS
from openpaw.model.status_event import StatusEventKind

logger = logging.getLogger(__name__)


class _ModuleChoice(BaseModel):
    """Structured output for the auto-selection call."""

    module: str = Field(description="Name of the chosen module")
    reason: str = Field(description="One sentence: why this module fits the task")


async def resolve_module(
    configured: str,
    allowed: list[str] | None,
    candidates: dict[str, ReasoningModule],
    kind: ModuleKind,
    task: str,
    selector_model: BaseChatModel,
    workspace: str,
) -> ReasoningModule:
    """Resolve which module instance handles this kind.

    Args:
        configured: Pinned module name, or ``"auto"``.
        allowed: Optional restriction list applied to ``auto`` resolution.
        candidates: Built module instances of this kind, keyed by name.
        kind: The module kind being resolved.
        task: Task objective, presented to the selector model.
        selector_model: Per-node model for path 3 (a fast class fits, ADR-103).
        workspace: Owning workspace name for the ``module.selected`` event.

    Raises:
        ValueError: If a pinned name is unknown, or ``allowed`` filters out
            every candidate — both are config errors, not runtime failures.
    """
    if configured != "auto":
        if configured not in candidates:
            raise ValueError(
                f"Pinned {kind.value} module {configured!r} is not available; "
                f"candidates: {sorted(candidates)}"
            )
        chosen, reason = candidates[configured], "pinned"
    else:
        pool = {name: mod for name, mod in candidates.items() if allowed is None or name in allowed}
        if not pool:
            raise ValueError(
                f"No {kind.value} module candidates remain after 'allowed' filtering "
                f"(allowed={allowed}, candidates={sorted(candidates)})"
            )
        if len(pool) == 1:
            chosen, reason = next(iter(pool.values())), "only candidate"
        else:
            chosen, reason = await _select_with_model(pool, candidates, kind, task, selector_model)

    emit_status(
        StatusEventKind.MODULE_SELECTED,
        {"kind": kind.value, "module": chosen.name, "reason": reason},
        workspace=workspace,
        node=kind.value,
    )
    return chosen


async def _select_with_model(
    pool: dict[str, ReasoningModule],
    candidates: dict[str, ReasoningModule],
    kind: ModuleKind,
    task: str,
    selector_model: BaseChatModel,
) -> tuple[ReasoningModule, str]:
    """Path 3: one structured-output call over the candidate catalog.

    Fail-open: any failure binds the kind default — selection must never be
    less reliable than not selecting at all.
    """
    catalog = "\n".join(f"- {mod.name}: {mod.tagline}" for mod in pool.values())
    prompt = f"Task: {task}\n\nAvailable {kind.value} modules:\n{catalog}\n\nChoose the best-fit module."
    try:
        choice = await selector_model.with_structured_output(_ModuleChoice).ainvoke([HumanMessage(prompt)])
        if not isinstance(choice, _ModuleChoice):
            raise ValueError(f"selector returned {type(choice).__name__}")
        return pool[choice.module], choice.reason
    except Exception:
        logger.warning("Module selection for kind %s failed; using kind default", kind.value, exc_info=True)
        return candidates[KIND_DEFAULTS[kind]], "selector failed; kind default"
