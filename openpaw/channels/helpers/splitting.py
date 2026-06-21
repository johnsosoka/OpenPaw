"""Message splitting utilities for channel adapters.

Provides a platform-agnostic message splitter that respects configurable
character limits, trying to break at natural boundaries first.
"""


def split_message(text: str, max_length: int) -> list[str]:
    """Split text into chunks that fit a message length limit.

    Tries to break at paragraph boundaries (double newline), falls back
    to single newlines, then hard-splits as a last resort.

    Args:
        text: The full message text to split.
        max_length: Maximum character length per chunk.

    Returns:
        List of message chunks, each within max_length.
    """
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        # Prefer paragraph boundary
        split_at = remaining.rfind("\n\n", 0, max_length)

        # Fall back to single newline
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, max_length)

        # Hard split as last resort
        if split_at == -1:
            split_at = max_length

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")

    return chunks
