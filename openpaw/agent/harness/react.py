"""ReactHarness — the existing AgentRunner as the react agent harness.

``AgentHarness`` is a structural protocol and ``AgentRunner`` already
satisfies its entire surface (the ``update["model"]`` stream parsing and
``as_node="tools"`` recovery knowledge live inside it). A pure-delegation
wrapper would add fifteen forwarding members with no behavior, so the react
harness IS ``AgentRunner`` — this module just pins the protocol conformance
and the alias that gives the ultra harness a symmetric import site.

Deviation from the ADR-101 sketch (which drew a wrapper class) is deliberate:
the seam is the protocol, not a wrapper. See llm_memory/0-5-0-release/.
"""

from openpaw.agent.harness.base import AgentHarness, HarnessKind
from openpaw.agent.runner import AgentRunner

# The react harness is the existing runner, unchanged.
ReactHarness = AgentRunner


def _protocol_conformance(harness: AgentRunner) -> AgentHarness:
    """Compile-time check that AgentRunner satisfies AgentHarness.

    mypy strict verifies the structural match here; a drift in either
    surface fails type checking rather than exploding at runtime.
    """
    return harness


__all__ = ["ReactHarness", "HarnessKind"]
