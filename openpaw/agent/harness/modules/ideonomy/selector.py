"""Deterministic lens selection — keyword scoring against the task, no LLM.

Ports the relevance scoring of the MIT-licensed
https://github.com/Morpheis/ideonomy-engine (``src/relevance.ts``): per
keyword, 3 points for a substring match against the task, 2 for an exact
token match, 1 for a shared 4-character prefix between tokens (fuzzy match
for morphological variants). Ties break alphabetically by division theme so
selection is fully stable across runs.
"""

import re

from openpaw.agent.harness.modules.ideonomy.divisions import DIVISIONS, Division

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokens longer than two characters (mirrors the reference)."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 2]


def score_division(division: Division, task: str) -> int:
    """Score a division's keyword relevance to the task text."""
    task_lower = task.lower()
    task_tokens = _tokenize(task)
    score = 0
    for keyword in division.keywords:
        if keyword in task_lower:
            score += 3
        for k_token in _tokenize(keyword):
            for t_token in task_tokens:
                if k_token == t_token:
                    score += 2
                elif len(k_token) >= 4 and len(t_token) >= 4 and k_token[:4] == t_token[:4]:
                    score += 1
    return score


def select_lenses(task: str, count: int = 3) -> tuple[Division, ...]:
    """Return the ``count`` most relevant divisions for the task, deterministically."""
    ranked = sorted(DIVISIONS, key=lambda d: (-score_division(d, task), d.theme))
    return tuple(ranked[:count])
