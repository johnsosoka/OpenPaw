"""Markdown to Telegram HTML converter.

Converts standard markdown formatting to Telegram-compatible HTML for proper
rendering in the Telegram Bot API.

Telegram supports a limited subset of HTML tags:
- <b>bold</b>, <strong>bold</strong>
- <i>italic</i>, <em>italic</em>
- <code>inline code</code>
- <pre>code blocks</pre>
- <a href="url">link text</a>

Standard markdown headers are converted to bold text since Telegram has no
native header support.
"""

import html
import re


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
