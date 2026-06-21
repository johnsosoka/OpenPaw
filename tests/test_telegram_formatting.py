"""Tests for Telegram markdown-to-HTML formatting."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest

from openpaw.channels.formatting import markdown_to_telegram_html
from openpaw.channels.telegram import TelegramChannel


class TestMarkdownToTelegramHtml:
    """Test the markdown_to_telegram_html converter."""

    def test_h1_header(self) -> None:
        result = markdown_to_telegram_html("# Header")
        assert result == "<b>Header</b>"

    def test_h2_header(self) -> None:
        result = markdown_to_telegram_html("## Subheader")
        assert result == "<b>Subheader</b>"

    def test_h3_header(self) -> None:
        result = markdown_to_telegram_html("### Section")
        assert result == "<b>Section</b>"

    def test_multiple_headers(self) -> None:
        text = "# Main\n## Sub\n### Detail"
        result = markdown_to_telegram_html(text)
        assert result == "<b>Main</b>\n<b>Sub</b>\n<b>Detail</b>"

    def test_bold_asterisks(self) -> None:
        result = markdown_to_telegram_html("This is **bold** text")
        assert result == "This is <b>bold</b> text"

    def test_bold_underscores(self) -> None:
        result = markdown_to_telegram_html("This is __bold__ text")
        assert result == "This is <b>bold</b> text"

    def test_bold_in_sentence(self) -> None:
        result = markdown_to_telegram_html("Before **middle** after")
        assert result == "Before <b>middle</b> after"

    def test_italic_asterisks(self) -> None:
        result = markdown_to_telegram_html("This is *italic* text")
        assert result == "This is <i>italic</i> text"

    def test_italic_underscores(self) -> None:
        result = markdown_to_telegram_html("This is _italic_ text")
        assert result == "This is <i>italic</i> text"

    def test_italic_not_in_filename(self) -> None:
        result = markdown_to_telegram_html("Check my_file_name.txt")
        assert result == "Check my_file_name.txt"
        assert "<i>" not in result

    def test_italic_underscores_in_parentheses(self) -> None:
        result = markdown_to_telegram_html("(_important_)")
        assert result == "(<i>important</i>)"

    def test_unclosed_bold_passthrough(self) -> None:
        result = markdown_to_telegram_html("This is **bold without closing")
        assert "**" in result
        assert "<b>" not in result

    def test_inline_code(self) -> None:
        result = markdown_to_telegram_html("Check `config.yaml` file")
        assert result == "Check <code>config.yaml</code> file"

    def test_code_block_no_language(self) -> None:
        result = markdown_to_telegram_html("```\ncode here\n```")
        assert result == "<pre>code here\n</pre>"

    def test_code_block_with_language(self) -> None:
        result = markdown_to_telegram_html("```python\nprint('hello')\n```")
        assert result == "<pre>print(&#x27;hello&#x27;)\n</pre>"

    def test_code_block_preserves_html(self) -> None:
        result = markdown_to_telegram_html("```\n<div>html</div>\n```")
        assert result == "<pre>&lt;div&gt;html&lt;/div&gt;\n</pre>"
        assert "<div>html</div>" not in result

    def test_inline_code_preserves_markdown(self) -> None:
        result = markdown_to_telegram_html("Use `**bold**` syntax")
        assert result == "Use <code>**bold**</code> syntax"
        assert "<b>" not in result

    def test_link(self) -> None:
        result = markdown_to_telegram_html("[Click here](https://example.com)")
        assert result == '<a href="https://example.com">Click here</a>'

    def test_link_with_special_chars(self) -> None:
        result = markdown_to_telegram_html("[Search](https://google.com?q=test&lang=en)")
        assert result == '<a href="https://google.com?q=test&amp;lang=en">Search</a>'

    def test_ampersand_escaped(self) -> None:
        result = markdown_to_telegram_html("A & B")
        assert result == "A &amp; B"

    def test_angle_brackets_escaped(self) -> None:
        result = markdown_to_telegram_html("x < y > z")
        assert result == "x &lt; y &gt; z"

    def test_bold_in_header(self) -> None:
        result = markdown_to_telegram_html("## The **important** part")
        assert result == "<b>The <b>important</b> part</b>"

    def test_empty_string(self) -> None:
        result = markdown_to_telegram_html("")
        assert result == ""

    def test_plain_text_passthrough(self) -> None:
        result = markdown_to_telegram_html("Just plain text here")
        assert result == "Just plain text here"

    def test_realistic_agent_output(self) -> None:
        text = """## Task Summary

I've completed the following:
- **Fixed** the authentication bug
- Updated `config.yaml` with new settings
- Added tests for the _edge cases_

Next steps:
1. Review the [documentation](https://docs.example.com)
2. Deploy to staging

Here's the code:
```python
def hello():
    return "world"
```

The system now handles `<script>` tags properly."""

        result = markdown_to_telegram_html(text)

        # Header converted
        assert "<b>Task Summary</b>" in result

        # Bold converted
        assert "<b>Fixed</b>" in result

        # Inline code converted
        assert "<code>config.yaml</code>" in result

        # Italic converted
        assert "<i>edge cases</i>" in result

        # Link converted
        assert '<a href="https://docs.example.com">documentation</a>' in result

        # Code block converted and HTML-escaped
        assert "<pre>def hello():\n    return &quot;world&quot;\n</pre>" in result

        # HTML entities escaped outside code
        assert "&lt;script&gt;" in result

        # Original markdown removed
        assert "**Fixed**" not in result
        assert "```python" not in result


class TestTelegramSendMessageFormatting:
    """Test Telegram adapter markdown integration."""

    @pytest.fixture
    def channel(self) -> TelegramChannel:
        channel = TelegramChannel(token="test-token", allowed_users=[12345], workspace_name="test")
        mock_app = MagicMock()
        mock_bot = AsyncMock()
        mock_bot.id = 999
        mock_app.bot = mock_bot
        channel._app = mock_app
        return channel

    @pytest.mark.asyncio
    async def test_sends_with_html_parse_mode(self, channel: TelegramChannel) -> None:
        mock_message = MagicMock()
        mock_message.message_id = 123
        channel._app.bot.send_message = AsyncMock(return_value=mock_message)  # type: ignore[union-attr]

        await channel.send_message("telegram:12345", "**Bold** text")

        channel._app.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        call_kwargs = channel._app.bot.send_message.call_args[1]  # type: ignore[union-attr]
        assert call_kwargs["parse_mode"] == "HTML"
        assert call_kwargs["text"] == "<b>Bold</b> text"

    @pytest.mark.asyncio
    async def test_falls_back_on_bad_request(self, channel: TelegramChannel) -> None:
        mock_message = MagicMock()
        mock_message.message_id = 123

        call_count = 0
        async def mock_send(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise BadRequest("Can't parse entities: unclosed tag")
            return mock_message

        channel._app.bot.send_message = mock_send  # type: ignore[union-attr]

        content = "**Bold** text"
        result = await channel.send_message("telegram:12345", content)

        # Should have been called twice: HTML attempt + plain fallback
        assert call_count == 2
        assert result.content == content

    @pytest.mark.asyncio
    async def test_respects_explicit_parse_mode(self, channel: TelegramChannel) -> None:
        mock_message = MagicMock()
        mock_message.message_id = 123
        channel._app.bot.send_message = AsyncMock(return_value=mock_message)  # type: ignore[union-attr]

        await channel.send_message("telegram:12345", "**Bold** text", parse_mode="Markdown")

        channel._app.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        call_kwargs = channel._app.bot.send_message.call_args[1]  # type: ignore[union-attr]
        # Should respect explicit parse_mode and NOT convert to HTML
        assert call_kwargs["parse_mode"] == "Markdown"
        assert call_kwargs["text"] == "**Bold** text"

    @pytest.mark.asyncio
    async def test_non_parse_bad_request_reraises(self, channel: TelegramChannel) -> None:
        async def mock_send(*args: Any, **kwargs: Any) -> Any:
            raise BadRequest("Chat not found")

        channel._app.bot.send_message = mock_send  # type: ignore[union-attr]

        # Other BadRequest errors should propagate
        with pytest.raises(BadRequest, match="Chat not found"):
            await channel.send_message("telegram:12345", "**Bold** text")

    @pytest.mark.asyncio
    async def test_inline_code_in_message(self, channel: TelegramChannel) -> None:
        mock_message = MagicMock()
        mock_message.message_id = 123
        channel._app.bot.send_message = AsyncMock(return_value=mock_message)  # type: ignore[union-attr]

        await channel.send_message("telegram:12345", "Check `config.yaml` file")

        channel._app.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        call_kwargs = channel._app.bot.send_message.call_args[1]  # type: ignore[union-attr]
        assert call_kwargs["text"] == "Check <code>config.yaml</code> file"
        assert call_kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_code_block_in_message(self, channel: TelegramChannel) -> None:
        mock_message = MagicMock()
        mock_message.message_id = 123
        channel._app.bot.send_message = AsyncMock(return_value=mock_message)  # type: ignore[union-attr]

        content = "```python\nprint('hello')\n```"
        await channel.send_message("telegram:12345", content)

        channel._app.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        call_kwargs = channel._app.bot.send_message.call_args[1]  # type: ignore[union-attr]
        assert call_kwargs["text"] == "<pre>print(&#x27;hello&#x27;)\n</pre>"
        assert call_kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_link_in_message(self, channel: TelegramChannel) -> None:
        mock_message = MagicMock()
        mock_message.message_id = 123
        channel._app.bot.send_message = AsyncMock(return_value=mock_message)  # type: ignore[union-attr]

        await channel.send_message("telegram:12345", "[Click here](https://example.com)")

        channel._app.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        call_kwargs = channel._app.bot.send_message.call_args[1]  # type: ignore[union-attr]
        assert call_kwargs["text"] == '<a href="https://example.com">Click here</a>'
        assert call_kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_mixed_formatting_in_message(self, channel: TelegramChannel) -> None:
        mock_message = MagicMock()
        mock_message.message_id = 123
        channel._app.bot.send_message = AsyncMock(return_value=mock_message)  # type: ignore[union-attr]

        content = "**Bold** and *italic* with `code`"
        await channel.send_message("telegram:12345", content)

        channel._app.bot.send_message.assert_called_once()  # type: ignore[union-attr]
        call_kwargs = channel._app.bot.send_message.call_args[1]  # type: ignore[union-attr]
        assert call_kwargs["text"] == "<b>Bold</b> and <i>italic</i> with <code>code</code>"
        assert call_kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_per_chunk_fallback(self, channel: TelegramChannel) -> None:
        """If HTML fails on one chunk, only that chunk falls back to plain text."""
        mock_message = MagicMock()
        mock_message.message_id = 123

        call_count = 0
        calls: list[dict[str, Any]] = []

        async def mock_send(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            calls.append(kwargs)
            # Fail the second HTML attempt
            if call_count == 2 and kwargs.get("parse_mode") == "HTML":
                raise BadRequest("Can't parse entities: unclosed tag")
            return mock_message

        channel._app.bot.send_message = mock_send  # type: ignore[union-attr]

        # Create a message that splits into 2 chunks (just over limit)
        chunk1 = "**Bold** " + "A" * 4080
        chunk2 = "\n\n**More bold** text"
        content = chunk1 + chunk2
        await channel.send_message("telegram:12345", content)

        # Should have 3 calls: chunk1 HTML (ok), chunk2 HTML (fail), chunk2 plain (ok)
        assert call_count == 3
        # First call: HTML parse mode
        assert calls[0].get("parse_mode") == "HTML"
        # Second call: HTML parse mode (failed)
        assert calls[1].get("parse_mode") == "HTML"
        # Third call: plain text fallback (no parse_mode)
        assert "parse_mode" not in calls[2]
