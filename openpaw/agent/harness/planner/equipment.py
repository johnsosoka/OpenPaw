"""Tool-equipping support for the planner harness (ADR-104, PRD-002 H5).

Catalog construction, always-equip floor resolution, the equip-selection
schema and prompts, and the ``request_tools`` recovery tool (H5.3). The
selection call itself runs inside the graph's equip node (graph.py); the
per-subset step executor lives on PlannerHarness.

Group and source attribution reuse the same mapping the sub-agent filter
machinery resolves against (BuiltinRegistry metadata / get_group_members) —
no parallel group system is introduced (ADR-104 §2).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

# Deliberate upward reach (agent -> builtins) for group-name resolution,
# mirroring the existing status_update -> builtins._channel_context precedent.
# No import cycle: builtins.registry does not import agent/. Callers can
# inject group_resolver to avoid the reach entirely (tests do).
from openpaw.builtins.registry import BuiltinRegistry

logger = logging.getLogger(__name__)

REQUEST_TOOLS_NAME = "request_tools"

# First-sentence cap for catalog lines (same shape as PlannerHarness._tools_summary).
_DESCRIPTION_MAX_CHARS = 150

EQUIP_SYSTEM_PROMPT = """\
You select the smallest set of tools an AI agent needs to accomplish a task.
Given the task objective and a catalog of available tools, return the tool \
names to equip (at most {max_tools}) and a one-line reason. Only use names \
from the catalog. Prefer fewer, clearly relevant tools."""

# {context_block} is the optional "Session context:" block (ADR-108 — stated
# constraints can steer selection); renders as "" when there is no brief.
EQUIP_TASK_TEMPLATE = """\
Task objective: {objective}

{context_block}Tool catalog:
{catalog}"""

EQUIP_REQUEST_BLOCK = """

While executing, the agent requested additional capability: {requested}
Re-select the toolset with that request in mind."""


class EquipDecision(BaseModel):
    """Structured output of the equip-selection call (ADR-104 §2)."""

    equip: list[str] = Field(description="Tool names to equip, from the catalog")
    reason: str = Field(description="One-line rationale for the selection")


@dataclass(frozen=True)
class ToolCatalogEntry:
    """One catalog line: cheap text, not a full JSON schema (ADR-104 §2)."""

    name: str
    description: str
    group: str | None
    source: str


@dataclass(frozen=True)
class EquipmentContext:
    """Everything the equip node needs, built once per harness compile.

    Attributes:
        catalog: Catalog entries for the inner runner's additional tools.
        floor: Resolved always-equip tool names (never filterable, H5.2).
            ``group:filesystem`` resolves to nothing here by design —
            filesystem tools are added inside AgentRunner._build_agent on
            every build, so their floor is structural, not name-based.
        model: The selection model (cfg.model pointer, workspace default
            when unset).
        max_tools: Clamp applied to the LLM selection before the floor union.
    """

    catalog: list[ToolCatalogEntry]
    floor: frozenset[str]
    model: BaseChatModel
    max_tools: int


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", tool))


def _first_sentence(description: str) -> str:
    """First sentence of the first line, capped."""
    return description.split("\n")[0].split(". ")[0].strip()[:_DESCRIPTION_MAX_CHARS]


def _builtin_groups() -> dict[str, str]:
    """Tool name -> group, from registered builtin metadata.

    Same name-based mapping filter.py's group resolution matches against;
    multi-tool builtins whose LangChain tool names differ from the builtin
    name (e.g. browser_*) attribute as group None — a known limitation of
    the existing machinery, not worked around here.
    """
    registry = BuiltinRegistry.get_instance()
    return {
        meta.name: meta.group
        for meta in registry.list_all()["tools"]
        if meta.group is not None
    }


def build_tool_catalog(tools: list[Any]) -> list[ToolCatalogEntry]:
    """Build the equip catalog from the inner runner's additional tools.

    Emits a single lint warning listing tools with missing or one-word
    descriptions (ADR-104 consequence: catalogs need decent descriptions).
    """
    groups = _builtin_groups()
    entries: list[ToolCatalogEntry] = []
    poorly_described: list[str] = []
    for tool in tools:
        name = _tool_name(tool)
        description = _first_sentence(str(getattr(tool, "description", "") or ""))
        if len(description.split()) <= 1:
            poorly_described.append(name)
        entries.append(
            ToolCatalogEntry(
                name=name,
                description=description,
                group=groups.get(name),
                # ponytail: source is a prompt hint only; MCP-vs-workspace is
                # not distinguishable from the flat tool list the harness holds.
                source="builtin" if name in groups else "workspace",
            )
        )
    if poorly_described:
        logger.warning(
            "Tool-equipping catalog: missing/one-word descriptions for %s — "
            "the equip selector cannot judge these tools well",
            sorted(poorly_described),
        )
    return entries


def render_catalog(catalog: list[ToolCatalogEntry]) -> str:
    """Render catalog lines for the equip prompt."""
    return "\n".join(
        f"- {e.name} [{e.group or e.source}]: {e.description or '(no description)'}"
        for e in catalog
    )


def resolve_equip_floor(
    always_equip: list[str],
    tools: list[Any],
    group_resolver: Callable[[str], list[str]] | None = None,
) -> set[str]:
    """Expand ``group:`` prefixes in the always-equip floor to concrete names.

    Uses the same group resolution as the sub-agent filter machinery
    (BuiltinRegistry.get_group_members). Entries that do not match any tool
    in ``tools`` are kept: they are either structural (``group:filesystem``
    — filesystem tools live inside AgentRunner, not the additional set) or
    harmless no-ops when filtering by name.
    """
    if group_resolver is None:
        group_resolver = BuiltinRegistry.get_instance().get_group_members

    resolved: set[str] = set()
    for entry in always_equip:
        if entry.startswith("group:"):
            group = entry[6:]
            try:
                resolved.update(group_resolver(group))
            except Exception:
                logger.warning("Failed to resolve always_equip group '%s'", group, exc_info=True)
        else:
            resolved.add(entry)

    tool_names = {_tool_name(t) for t in tools}
    structural = resolved - tool_names
    if structural:
        logger.debug(
            "always_equip entries not in the additional toolset (structural or unknown): %s",
            sorted(structural),
        )
    return resolved


def detect_tool_request(messages: list[Any]) -> str | None:
    """Extract the request_tools ask from an inner run's messages, if any.

    Detection is on tool_calls (which carry the args) rather than
    ToolMessages; a matching ToolMessage only exists because the call did.
    """
    requests: list[str] = []
    for msg in messages:
        for tc in getattr(msg, "tool_calls", None) or []:
            if tc.get("name") == REQUEST_TOOLS_NAME:
                needed = tc.get("args", {}).get("tools_needed")
                if needed:
                    requests.append(str(needed))
    return "; ".join(requests) or None


class _RequestToolsArgs(BaseModel):
    """Arguments for the request_tools recovery tool."""

    tools_needed: str = Field(description="What capability or tools you need, and why")


def _request_tools(tools_needed: str) -> str:
    return (
        "Request recorded. Stop working on this step — the toolset will be "
        "rebuilt and the step will re-run."
    )


def create_request_tools_tool() -> StructuredTool:
    """The always-equipped mis-equip escape hatch (ADR-104 §3, H5.3).

    Appended structurally to every equipped step executor; its call is
    intercepted after the step and routes back to equip.
    """
    return StructuredTool.from_function(
        func=_request_tools,
        name=REQUEST_TOOLS_NAME,
        description=(
            "Request tools you need but do not currently have. Use ONLY when "
            "the current step cannot be completed with your current tools."
        ),
        args_schema=_RequestToolsArgs,
    )
