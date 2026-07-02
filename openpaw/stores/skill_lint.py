"""Content-lint deny patterns for skill writes (ADR-105 gate 3).

A seatbelt, not a guarantee — the pattern list will have false negatives;
staged mode is the real defense for programmatic write paths. Kept in a
dedicated module so the list is unit-testable in isolation.
"""

import re

# (pattern, human-readable reason) pairs, checked against the skill body.
DENY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\b(sk-[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{16})\b"),
        "credential-shaped string",
    ),
    (
        re.compile(r"(?i)api[_-]?key\s*[:=]\s*\S{12,}"),
        "inline API key assignment",
    ),
    (
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]{20,}"),
        "bearer token",
    ),
    (
        re.compile(r"(?i)\bpassword\s*[:=]\s*\S+"),
        "inline password assignment",
    ),
    (
        re.compile(r"(?i)bypass\w*\s+(the\s+)?approval"),
        "instructs bypassing approval gates",
    ),
    (
        re.compile(r"(?i)(escape|ignore|disable)\w*\s+(the\s+)?sandbox"),
        "instructs sandbox bypass",
    ),
    (
        re.compile(r"(?i)ignore\s+\[SYSTEM\]"),
        "tampers with [SYSTEM] event handling",
    ),
)


def lint_skill_content(content: str) -> list[str]:
    """Check skill body content against the deny-pattern list.

    Args:
        content: The skill body (markdown, frontmatter excluded).

    Returns:
        List of human-readable reasons for every matching pattern.
        Empty list means the content passed the lint.
    """
    return [reason for pattern, reason in DENY_PATTERNS if pattern.search(content)]
