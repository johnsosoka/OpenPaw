"""Prompt text for the ultra harness nodes (ADR-101).

Kept ultra-local: ``core/prompts`` is owned by a parallel workstream; these
constants are harness-internal and not user-visible configuration.
"""

TRIAGE_SYSTEM_PROMPT = """\
You are a triage classifier for an AI agent. Classify ONLY the LATEST \
MESSAGE into exactly one route. The recent conversation is context for \
resolving references (e.g. "do it", "summarize that") — it is NOT work to \
resume or continue. A short acknowledgment, thanks, or compliment is `react`, \
even when the prior task was large.

- react: simple or conversational — a direct answer or a couple of tool \
calls suffices; also acknowledgments and small talk. When in doubt, choose react.
- plan: genuinely multi-step work — several distinct actions that benefit \
from an explicit ordered plan (research + build + verify, long-horizon tasks).
- ideate: open-ended creative work where exploring directions first would \
improve the result (brainstorming, naming, design concepts).

Restate the objective of the LATEST MESSAGE only, in one sentence."""

# Triage input: the recent conversation as reference-only context, plus the
# latest message set apart as the thing to classify (ADR-101; triage
# short-circuit design §B). The prompt classifies the latter, using the
# former only to resolve references.
TRIAGE_INPUT_TEMPLATE = """\
Recent conversation (context only — do NOT treat as work to continue or resume):
{digest}

LATEST MESSAGE TO CLASSIFY:
{latest}"""

# {context_block} is the optional "Session context:" block (ADR-108) —
# render_context_block() yields "" (byte-identical prompt) when no brief.
STEP_EXECUTION_TEMPLATE = """\
Objective: {objective}

{context_block}Plan so far:
{checklist}

Execute step {step_id}: {description}

Focus only on this step. Report what you did and the outcome."""

SYNTHESIZE_TEMPLATE = """\
Objective: {objective}

{context_block}Executed plan:
{checklist}

Step results:
{results}
{abort_block}
Write the final response to the user: summarize what was accomplished, \
surface anything important from the step results, and be direct about \
anything that failed or was skipped."""

SYNTHESIZE_ABORT_BLOCK = """
The plan was aborted before completion. Reason: {reason}
Explain this to the user and describe what was completed so far.
"""

# Last-resort plan when every planning module fails (never dead-end).
FALLBACK_STEP_DESCRIPTION = "Complete the task directly"
