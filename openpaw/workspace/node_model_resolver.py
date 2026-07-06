"""Per-node model resolution for the ultra harness (ADR-103).

Node config entries are pointers into the provider catalog — never a fourth
credential site. Resolution is a thin layer over the existing
:class:`ModelResolver`, and all instantiation flows through
``create_chat_model()`` so provider quirks (Moonshot temperature rules,
Fireworks retry patch, thinking coercion) stay centralized.

Precedence per node:
- ``node.model`` unset → the workspace's resolved model, workspace extras and
  all — current behavior; node ``temperature``/``max_tokens`` still override
  for that node only.
- ``node.model`` set (catalog name or ``provider:model``) → catalog entry's
  credentials + extras. Workspace extra kwargs deliberately do NOT leak onto
  catalog-pointed node models: they are workspace-model-specific (e.g. a
  Moonshot ``thinking`` flag must not reach an Anthropic triage model).
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel

from openpaw.core.config.models import NodeModelConfig
from openpaw.workspace.model_resolver import ModelResolver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedNodeModel:
    """Fully resolved parameters for one harness node's model.

    Attributes:
        model_str: LangChain ``provider:model`` string.
        display_str: User-facing name for /harness output and telemetry.
        api_key: Resolved credential (catalog or workspace fallback).
        temperature: Effective temperature (node override or workspace).
        region: AWS region for Bedrock models.
        extra_kwargs: Provider kwargs for create_chat_model.
        inherited: True when the node inherits the workspace model.
    """

    model_str: str
    display_str: str
    api_key: str | None
    temperature: float
    region: str | None
    extra_kwargs: dict[str, Any] = field(default_factory=dict)
    inherited: bool = True


class NodeModelResolver:
    """Resolves per-node model config against the workspace's ModelResolver.

    One instance per harness build; ``create_node_model()`` results should be
    cached on the harness object and rebuilt on ``rebuild_agent()`` — same
    lifecycle as today's single model (ADR-103 §4).
    """

    def __init__(
        self,
        resolver: ModelResolver,
        workspace_model: str,
        workspace_api_key: str | None,
        workspace_temperature: float,
        workspace_region: str | None,
        workspace_extra_kwargs: dict[str, Any],
    ) -> None:
        """Initialize with the workspace's resolved baseline.

        Args:
            resolver: The workspace's ModelResolver (catalog access).
            workspace_model: The workspace's configured/override model id
                (pre-resolution form, e.g. catalog name or provider:model).
            workspace_api_key: The workspace model's API key.
            workspace_temperature: The workspace temperature.
            workspace_region: The workspace AWS region, if any.
            workspace_extra_kwargs: Workspace-level extra model kwargs
                (merged catalog<workspace, as AgentFactory computes them).
        """
        self._resolver = resolver
        self._workspace_model = workspace_model
        self._workspace_api_key = workspace_api_key
        self._workspace_temperature = workspace_temperature
        self._workspace_region = workspace_region
        self._workspace_extra_kwargs = workspace_extra_kwargs

    def resolve_node(self, node: NodeModelConfig) -> ResolvedNodeModel:
        """Resolve one node's effective model parameters (no instantiation)."""
        if node.model is None:
            resolved = self._resolver.resolve(self._workspace_model)
            merged_extra = {**resolved.extra_kwargs, **self._workspace_extra_kwargs}
            api_key = (
                resolved.api_key
                if resolved.api_key is not None
                else self._workspace_api_key
            )
            base = ResolvedNodeModel(
                model_str=resolved.model_str,
                display_str=resolved.display_str,
                api_key=api_key,
                temperature=self._workspace_temperature,
                region=resolved.region or self._workspace_region,
                extra_kwargs=merged_extra,
                inherited=True,
            )
        else:
            resolved = self._resolver.resolve(node.model)
            api_key = (
                resolved.api_key
                if resolved.api_key is not None
                else self._resolver.resolve_api_key(node.model)
            )
            base = ResolvedNodeModel(
                model_str=resolved.model_str,
                display_str=resolved.display_str,
                api_key=api_key,
                temperature=self._workspace_temperature,
                region=resolved.region,
                extra_kwargs=dict(resolved.extra_kwargs),
                inherited=False,
            )

        # Node sampling params override for this node only (ADR-103 §2).
        temperature = (
            node.temperature if node.temperature is not None else base.temperature
        )
        extra = dict(base.extra_kwargs)
        if node.max_tokens is not None:
            extra["max_tokens"] = node.max_tokens
        return ResolvedNodeModel(
            model_str=base.model_str,
            display_str=base.display_str,
            api_key=base.api_key,
            temperature=temperature,
            region=base.region,
            extra_kwargs=extra,
            inherited=base.inherited,
        )

    def create_node_model(self, node: NodeModelConfig) -> BaseChatModel:
        """Instantiate one node's model via the central factory."""
        from openpaw.agent.model_factory import create_chat_model

        r = self.resolve_node(node)
        return create_chat_model(
            model_str=r.model_str,
            api_key=r.api_key,
            temperature=r.temperature,
            region=r.region,
            extra_kwargs=dict(r.extra_kwargs),
        )
