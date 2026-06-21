"""Tests for markdown table to monospace conversion."""

from openpaw.channels.formatting import markdown_tables_to_monospace, markdown_to_telegram_html


class TestMarkdownTablesToMonospace:
    """Tests for the standalone table conversion utility."""

    def test_simple_table(self) -> None:
        """Basic 2-column table converts to aligned monospace."""
        md = (
            "| Name  | Score |\n"
            "|-------|-------|\n"
            "| Alice | 95    |\n"
            "| Bob   | 87    |"
        )
        result = markdown_tables_to_monospace(md)
        assert "```" in result
        assert "Alice" in result
        assert "Bob" in result
        # Should not contain pipe delimiters inside the code block
        lines = result.split("\n")
        code_lines = [l for l in lines if l not in ("```", "")]
        # Separator row becomes dashes
        assert any(set(l.strip()) == {"-"} for l in code_lines)

    def test_preserves_non_table_text(self) -> None:
        """Text before and after a table is preserved."""
        md = "Hello world\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nGoodbye"
        result = markdown_tables_to_monospace(md)
        assert result.startswith("Hello world")
        assert result.endswith("Goodbye")
        assert "```" in result

    def test_no_table(self) -> None:
        """Text without tables passes through unchanged."""
        md = "Just some text\nwith no tables."
        result = markdown_tables_to_monospace(md)
        assert result == md

    def test_column_alignment(self) -> None:
        """Columns are padded to equal widths."""
        md = (
            "| Short | LongerColumn |\n"
            "|-------|----------|\n"
            "| A     | B        |"
        )
        result = markdown_tables_to_monospace(md)
        # Find the data rows inside the code block
        lines = result.split("\n")
        code_lines = [l for l in lines if l not in ("```", "") and not all(c == "-" for c in l.strip())]
        # Both header and data rows should have same length (aligned)
        lengths = [len(l) for l in code_lines]
        assert len(set(lengths)) == 1, f"Row lengths differ: {lengths}"

    def test_multiple_tables(self) -> None:
        """Multiple tables in the same text are each converted."""
        md = (
            "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
            "Some text\n\n"
            "| X | Y |\n|---|---|\n| 3 | 4 |"
        )
        result = markdown_tables_to_monospace(md)
        assert result.count("```") == 4  # 2 tables × 2 fences each

    def test_separator_becomes_dashes(self) -> None:
        """The |---|---| separator row becomes a clean dash line."""
        md = "| H1 | H2 |\n|---|---|\n| v1 | v2 |"
        result = markdown_tables_to_monospace(md)
        lines = result.split("\n")
        dash_lines = [l for l in lines if l.strip() and set(l.strip()) == {"-"}]
        assert len(dash_lines) == 1

    def test_uneven_columns(self) -> None:
        """Rows with fewer columns than the header don't crash."""
        md = "| A | B | C |\n|---|---|---|\n| 1 | 2 |"
        result = markdown_tables_to_monospace(md)
        assert "```" in result
        assert "1" in result


class TestTelegramHtmlTableIntegration:
    """Verify tables render inside <pre> tags in Telegram HTML output."""

    def test_table_becomes_pre_block(self) -> None:
        """A markdown table in Telegram HTML output becomes a <pre> block."""
        md = "Results:\n\n| Name | Score |\n|------|-------|\n| Alice | 95 |\n| Bob | 87 |"
        html = markdown_to_telegram_html(md)
        assert "<pre>" in html
        assert "Alice" in html
        assert "Bob" in html
        # No raw pipes should remain (they'd be inside <pre>)
        # The table pipes are replaced by " | " alignment in monospace

    def test_table_with_surrounding_markdown(self) -> None:
        """Table conversion doesn't break other markdown elements."""
        md = "**Bold title**\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n*italic footer*"
        html = markdown_to_telegram_html(md)
        assert "<b>Bold title</b>" in html
        assert "<pre>" in html
        assert "<i>italic footer</i>" in html
