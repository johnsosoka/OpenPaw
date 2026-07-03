"""The ``harness:`` workspace config group (PRD-002 §4, ADR-103).

New 0.5.0 config groups use ``extra="forbid"`` so typos fail fast
(intentional contrast with the legacy ``extra="allow"`` models).

Node model entries are POINTERS into the provider catalog (catalog name or
``provider:model`` string) plus sampling params only — never
api_key/base_url/region. Credentials stay in the catalog (ADR-103 §1).

Zero-config default: a bare ``harness: {type: planner}`` must validate and
run — every node inherits the workspace model (PRD-002 H6.2).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NodeModelConfig(BaseModel):
    """Per-node model reference (ADR-103 §1).

    ``model`` is a provider-catalog name (e.g. ``fast``, ``strong``) or a
    ``provider:model`` string; resolution flows through NodeModelResolver ->
    ModelResolver -> create_chat_model(), keeping provider quirks central.
    Unset = inherit the workspace model.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)

    @field_validator("temperature")
    @classmethod
    def _temperature_in_range(cls, v: float | None) -> float | None:
        if v is not None and not 0.0 <= v <= 2.0:
            raise ValueError(f"temperature must be within [0.0, 2.0], got {v}")
        return v

    @field_validator("model")
    @classmethod
    def _model_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("model must be a catalog name or 'provider:model', not blank")
        return v


class ModuleNodeConfig(NodeModelConfig):
    """Base for kinds that select a reasoning module (ADR-102 §2, H3.4).

    ``module`` is a pinned registry name (no selector node materializes) or
    ``auto`` (selector step: 1 candidate -> short-circuit bind, no LLM call;
    >=2 -> one structured-output call over taglines, fail-open to the kind
    default). ``allowed`` restricts the auto candidate pool and is rejected
    on pinned modules — it is only meaningful with ``auto``.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    allowed: list[str] | None = None

    @model_validator(mode="after")
    def _allowed_requires_auto(self) -> "ModuleNodeConfig":
        if self.allowed is not None and getattr(self, "module", None) != "auto":
            raise ValueError("`allowed` is only valid with `module: auto`")
        return self


class PlanningNodeConfig(ModuleNodeConfig):
    """Planning node: reasoning module selection + model pointer."""

    module: Literal["direct", "self_discover", "auto"] = "direct"


class CreativeNodeConfig(ModuleNodeConfig):
    """Creative (ideate) node: module selection + model pointer."""

    module: Literal["ideonomy", "auto"] = "ideonomy"


class ReflectionNodeConfig(ModuleNodeConfig):
    """Reflection node: pluggable module kind (PRD-002 H4.3).

    ``off`` omits the reflect node from the graph entirely; ``light``
    (default) is a single structured check per step; ``full`` may rewrite
    the remaining plan; ``auto`` lets the selector choose per task.
    """

    module: Literal["off", "light", "full", "auto"] = "light"


class SelectorNodeConfig(NodeModelConfig):
    """Model pointer for the module-selection call (``module: auto`` paths).

    A fast model is the natural fit; unset inherits the workspace model.
    """


class BriefNodeConfig(NodeModelConfig):
    """Brief node (ADR-108): session distillation on the plan/ideate paths.

    Enabled by default — zero-config planner workspaces get session-aware
    planning; react routes never pay for it. ``max_input_tokens`` is an
    optional cost ceiling on the transcript window; unset uses the brief
    model's context window minus headroom. A fast large-context model is the
    natural fit for the model pointer.
    """

    enabled: bool = True
    max_input_tokens: int | None = Field(default=None, ge=1024)


class ToolEquippingConfig(BaseModel):
    """Optional equip phase (PRD-002 H5, ADR-104). Off by default."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    # Floor that can never be filtered out; supports group: prefixes like
    # the existing tool-filter machinery (H5.2).
    always_equip: list[str] = Field(
        default_factory=lambda: ["group:filesystem", "send_message"]
    )
    max_tools: int = Field(default=25, ge=1)
    # React-path option: stock LLMToolSelectorMiddleware, config-gated
    # (ADR-104 §5). Independent of the planner equip node.
    react_selector: bool = False
    model: str | None = None  # selection model pointer (catalog name)

    @field_validator("always_equip")
    @classmethod
    def _no_blank_entries(cls, v: list[str]) -> list[str]:
        if any(not entry.strip() for entry in v):
            raise ValueError("always_equip entries must be non-empty tool/group names")
        return v


class ExecutionConfig(NodeModelConfig):
    """Execution node: step budget. Runtime /model overrides apply to this
    node only (ADR-103 §4)."""

    max_steps: int = Field(default=12, ge=1, le=100)


class HarnessConfig(BaseModel):
    """The ``harness:`` workspace config group (PRD-002 §4).

    Example:
        harness:
          type: planner
          triage:   {model: fast}
          planning: {module: auto, model: strong}        # selector over taglines
          creative: {module: ideonomy}                   # pinned — no selector
          reflection: {module: auto, allowed: [light, full]}
          selector: {model: fast}
          brief: {enabled: true, model: fast}             # session brief (ADR-108)
          tool_equipping:
            enabled: false
            always_equip: [group:filesystem, send_message]
          execution: {max_steps: 12}
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["react", "planner"] = "react"
    triage: NodeModelConfig = Field(default_factory=NodeModelConfig)
    planning: PlanningNodeConfig = Field(default_factory=PlanningNodeConfig)
    creative: CreativeNodeConfig = Field(default_factory=CreativeNodeConfig)
    reflection: ReflectionNodeConfig = Field(default_factory=ReflectionNodeConfig)
    selector: SelectorNodeConfig = Field(default_factory=SelectorNodeConfig)
    brief: BriefNodeConfig = Field(default_factory=BriefNodeConfig)
    synthesize: NodeModelConfig = Field(default_factory=NodeModelConfig)
    tool_equipping: ToolEquippingConfig = Field(default_factory=ToolEquippingConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
