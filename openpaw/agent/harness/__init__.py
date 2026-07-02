"""Agent harness layer — the seam between message processing and graph topology.

An :class:`~openpaw.agent.harness.base.AgentHarness` is what
``MessageProcessor``/``WorkspaceRunner``/``AgentFactory`` consume: run a turn,
rebuild, swap tools/model/checkpointer, report context info and metrics, and
repair orphaned tool calls. Callers never see the underlying LangGraph shape.

Implementations:
- react: the existing single-loop ``create_agent`` path (``AgentRunner``
  satisfies the protocol structurally — see ``react.py``).
- planner: triage -> (react | plan | ideate) -> execute/reflect multi-node
  graph (``planner/``, ADR-101).
"""

from openpaw.agent.harness.base import AgentHarness, HarnessKind
from openpaw.agent.harness.react import ReactHarness

__all__ = ["AgentHarness", "HarnessKind", "ReactHarness"]
