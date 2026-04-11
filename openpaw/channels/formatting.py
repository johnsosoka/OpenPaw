"""Markdown formatting for channel adapters.

Provides markdown-to-HTML conversion for Telegram and shared utilities
for channels that lack native table rendering.

Telegram supports a limited subset of HTML tags:
- <b>bold</b>, <strong>bold</strong>
- <i>italic</i>, <em>italic</em>
- <code>inline code</code>
- <pre>code blocks</pre>
- <a href="url">link text</a>

Standard markdown headers are converted to bold text since Telegram has no
native header support. Markdown tables are converted to aligned monospace
blocks since Telegram and Discord have no native table rendering.
"""

import html
import re


def markdown_tables_to_monospace(text: str) -> str:
    """Convert markdown pipe tables to aligned monospace code blocks.

    Detects consecutive lines that look like markdown table rows (start with |)
    and replaces each table with a ``` monospace block. Column widths are
    normalized so content aligns neatly. Separator rows (|---|---|) are replaced
    with a dashed line of the correct total width.

    This is a shared utility — usable by any channel that lacks native table
    rendering (Telegram, Discord, etc.).

    Args:
        text: Text potentially containing markdown tables.

    Returns:
        Text with tables replaced by fenced monospace blocks.
    """
    lines = text.split("\n")
    result: list[str] = []
    table_lines: list[str] = []

    def _flush_table() -> None:
        """Convert accumulated table_lines into a monospace block."""
        if not table_lines:
            return

        # Parse cells from each row
        rows: list[list[str]] = []
        separator_indices: list[int] = []

        for i, line in enumerate(table_lines):
            stripped = line.strip()
            # Remove leading/trailing pipes and split
            if stripped.startswith("|"):
                stripped = stripped[1:]
            if stripped.endswith("|"):
                stripped = stripped[:-1]
            cells = [c.strip() for c in stripped.split("|")]

            # Detect separator rows (all cells match ---+ pattern)
            if all(re.match(r"^:?-{2,}:?$", c) for c in cells):
                separator_indices.append(i)

            rows.append(cells)

        if not rows:
            result.extend(table_lines)
            return

        # Compute max column widths
        num_cols = max(len(row) for row in rows)
        col_widths = [0] * num_cols
        for i, row in enumerate(rows):
            if i in separator_indices:
                continue
            for j, cell in enumerate(row):
                if j < num_cols:
                    col_widths[j] = max(col_widths[j], len(cell))

        # Ensure minimum width of 3 per column
        col_widths = [max(w, 3) for w in col_widths]

        # Build aligned output
        total_width = sum(col_widths) + (num_cols - 1) * 3  # 3 = " | " separator
        aligned: list[str] = []

        for i, row in enumerate(rows):
            if i in separator_indices:
                aligned.append("-" * total_width)
                continue
            padded = []
            for j in range(num_cols):
                cell = row[j] if j < len(row) else ""
                padded.append(cell.ljust(col_widths[j]))
            aligned.append(" | ".join(padded))

        result.append("```")
        result.extend(aligned)
        result.append("```")

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines.append(line)
        else:
            if table_lines:
                _flush_table()
                table_lines = []
            result.append(line)

    # Flush any trailing table
    if table_lines:
        _flush_table()

    return "\n".join(result)


def markdown_to_telegram_html(text: str) -> str:
    """Convert standard markdown to Telegram-compatible HTML.

    Conversion rules:
    - Headers (## Text) → <b>Text</b>
    - Bold (**text**) → <b>text</b>
    - Italic (*text*) → <i>text</i>
    - Inline code (`text`) → <code>text</code>
    - Code blocks (```text```) → <pre>text</pre>
    - Links ([text](url)) → <a href="url">text</a>

    Special handling:
    - Code content is HTML-escaped but not markdown-converted
    - HTML entities (<, >, &) are escaped in non-code content
    - Nested formatting (e.g., bold within headers) is preserved

    Args:
        text: Standard markdown text.

    Returns:
        Telegram-compatible HTML text.

    Example:
        >>> markdown_to_telegram_html("**Hello** world!")
        '<b>Hello</b> world!'
        >>> markdown_to_telegram_html("Check `config.yaml` file")
        'Check <code>config.yaml</code> file'
    """
    # Step 0: Convert markdown tables to fenced monospace blocks.
    # This runs before code block extraction so the ``` fences are picked up
    # naturally by the code block handler below.
    text = markdown_tables_to_monospace(text)

    # Step 1: Extract and protect code blocks
    code_blocks: list[str] = []

    def save_code_block(match: re.Match[str]) -> str:
        # Extract code content (with optional language tag)
        code = match.group(2) if match.lastindex and match.lastindex >= 2 else match.group(1)
        # HTML-escape the code content
        escaped_code = html.escape(code)
        # Store and return placeholder
        placeholder = f"\x00CODEBLOCK{len(code_blocks)}\x00"
        code_blocks.append(escaped_code)
        return placeholder

    # Match ```optional-lang\ncode\n``` or ```code```
    text = re.sub(
        r'```(?:\w+)?\n(.*?)```|```(.*?)```',
        save_code_block,
        text,
        flags=re.DOTALL
    )

    # Step 2: Extract and protect inline code
    inline_code: list[str] = []

    def save_inline_code(match: re.Match[str]) -> str:
        code = match.group(1)
        escaped_code = html.escape(code)
        placeholder = f"\x00INLINE{len(inline_code)}\x00"
        inline_code.append(escaped_code)
        return placeholder

    # Match `code` (non-greedy, no newlines)
    text = re.sub(r'`([^`\n]+)`', save_inline_code, text)

    # Step 3: HTML-escape the remaining text
    text = html.escape(text)

    # Step 4: Convert headers (must come before bold to preserve bold in headers)
    # Match ^#{1,6} <space> <content> (multiline mode)
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)

    # Step 5: Convert bold (**text** or __text__)
    # Non-greedy match, no newlines
    text = re.sub(r'\*\*([^\*\n]+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__([^_\n]+?)__', r'<b>\1</b>', text)

    # Step 6: Convert italic (*text* or _text_)
    # Must come after bold to avoid conflicts
    # Use negative lookbehind/lookahead to avoid matching ** or __
    text = re.sub(r'(?<!\*)\*(?!\*)([^\*\n]+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    # For underscores, use negative lookaround for word chars to avoid my_file_name issues
    text = re.sub(r'(?<!\w)_([^_\n]+?)_(?!\w)', r'<i>\1</i>', text)

    # Step 7: Convert links [text](url)
    # Non-greedy match, no newlines in text or url
    text = re.sub(r'\[([^\]\n]+?)\]\(([^\)\n]+?)\)', r'<a href="\2">\1</a>', text)

    # Step 8: Restore code blocks
    for i, code in enumerate(code_blocks):
        placeholder = f"\x00CODEBLOCK{i}\x00"
        text = text.replace(placeholder, f"<pre>{code}</pre>")

    # Step 9: Restore inline code
    for i, code in enumerate(inline_code):
        placeholder = f"\x00INLINE{i}\x00"
        text = text.replace(placeholder, f"<code>{code}</code>")

    return text
