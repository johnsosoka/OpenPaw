"""AgentHarness protocol — the seam between callers and agent-graph topology.

Captures exactly the surface that ``MessageProcessor``, ``WorkspaceRunner``,
``AgentFactory``, and command handlers consume from an agent execution engine
today. All ``create_agent``-internal knowledge (stream update-key parsing,
``aupdate_state(as_node="tools")`` recovery) lives behind this seam so callers
are topology-agnostic (ADR-101 §2).
"""

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from openpaw.agent.metrics import InvocationMetrics


class HarnessKind(StrEnum):
    """The agent harness topologies available to a workspace.

    Attributes:
        REACT: The existing single-loop create_agent path. Default;
            byte-for-byte current behavior.
        ULTRA: Triage -> (react | plan | ideate) -> execute/reflect
            multi-node graph (ADR-101).
    """

    REACT = "react"
    ULTRA = "ultra"


@runtime_checkable
class AgentHarness(Protocol):
    """Everything callers need from an agent execution engine.

    ``AgentRunner`` satisfies this protocol structurally (it is the react
    harness); ``UltraHarness`` implements it over a custom StateGraph.
    Callers hold this type and never depend on graph internals.

    Notes on the mutable-attribute contract: ``timeout_seconds`` is a plain
    attribute because ``SubAgentRunner`` overrides it per request; the
    ``checkpointer`` attribute is read by the approval-recovery path.
    """

    timeout_seconds: float

    @property
    def kind(self) -> HarnessKind:
        """Which topology this harness implements."""
        ...

    @property
    def model_id(self) -> str:
        """The configured model identifier (execution model for ultra)."""
        ...

    @property
    def last_metrics(self) -> InvocationMetrics | None:
        """Token usage from the most recent run(), or None before first run."""
        ...

    @property
    def last_tools_used(self) -> list[str]:
        """Tool names invoked during the most recent run."""
        ...

    @property
    def max_output_tokens(self) -> int | None:
        """Configured output token cap, or None if uncapped."""
        ...

    @property
    def checkpointer(self) -> Any | None:
        """The active checkpointer, or None for stateless instances."""
        ...

    @property
    def additional_tools(self) -> list[Any]:
        """The current non-filesystem tool set (builtins + workspace + MCP)."""
        ...

    async def run(
        self,
        message: str,
        session_id: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Execute one agent turn and return the final response text.

        Owns streaming, timeout handling, and metrics collection.

        Raises:
            ApprovalRequiredError: A gated tool needs human approval.
            InterruptSignalError: The run was interrupted by the user.
        """
        ...

    def rebuild_agent(self) -> None:
        """Reload workspace state and rebuild the underlying graph(s).

        The de facto hot-swap mechanism (/model, /new, skill reload funnel
        here).
        """
        ...

    def update_tools(self, extra_tools: list[Any]) -> None:
        """Replace the additional-tools set and rebuild (MCP post-start wiring)."""
        ...

    def update_model(
        self,
        model: str,
        api_key: str | None = None,
        temperature: float | None = None,
    ) -> None:
        """Apply a runtime model override and rebuild.

        On an ultra harness the override applies to the execution node only
        (ADR-103 §4).
        """
        ...

    def update_checkpointer(self, checkpointer: Any) -> None:
        """Swap the checkpointer and rebuild (deferred AsyncSqliteSaver init)."""
        ...

    async def get_context_info(self, thread_id: str) -> dict[str, Any]:
        """Report context-window utilization for the auto-compact pre-run check.

        Returns:
            dict with max_input_tokens, approximate_tokens, utilization,
            message_count.
        """
        ...

    async def resolve_orphaned_tool_calls(
        self, thread_id: str, responses: dict[str, str] | None = None
    ) -> None:
        """Repair dangling tool calls after an approval interrupt.

        The react implementation injects synthetic ToolMessages via
        ``aupdate_state(as_node="tools")``; the ultra implementation targets
        the react subgraph's namespaced checkpoint and resumes the in-flight
        plan step.
        """
        ...
