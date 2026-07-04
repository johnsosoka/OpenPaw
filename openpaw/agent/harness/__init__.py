"""Agent harness layer — the seam between message processing and graph topology.

An :class:`~openpaw.agent.harness.base.AgentHarness` is what
``MessageProcessor``/``WorkspaceRunner``/``AgentFactory`` consume: run a turn,
rebuild, swap tools/model/checkpointer, report context info and metrics, and
repair orphaned tool calls. Callers never see the underlying LangGraph shape.

Implementations:
- react: the existing single-loop ``create_agent`` path (``AgentRunner``
  satisfies the protocol structurally — see ``react.py``).
- balanced: the react loop plus todo-driven plan middleware
  (``balanced.py``, ADR-111).
- ultra: triage -> (react | plan | ideate) -> execute/reflect multi-node
  graph (``ultra/``, ADR-101).
"""

from openpaw.agent.harness.base import AgentHarness, HarnessKind
from openpaw.agent.harness.react import ReactHarness

__all__ = ["AgentHarness", "HarnessKind", "ReactHarness"]

# UltraHarness is imported from openpaw.agent.harness.ultra directly —
# re-exporting here would import the full ultra graph stack for every
# consumer of the seam types.
