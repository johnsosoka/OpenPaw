"""Tests for md2pdf core conversion pipeline helpers."""

from pathlib import Path

from openpaw.builtins.tools.md2pdf import (
    _build_result_message,
    _markdown_to_html,
    _MermaidBlock,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_block(source: str, start: int = 0, end: int = 50) -> _MermaidBlock:
    return _MermaidBlock(source=source, start_pos=start, end_pos=end)


def _simple_svg(width: int = 100, height: int = 50) -> str:
    return f'<svg width="{width}" height="{height}"><rect/></svg>'


# ---------------------------------------------------------------------------
# TestMarkdownToHtml
# ---------------------------------------------------------------------------


class TestMarkdownToHtml:
    def test_basic_heading_converted(self) -> None:
        html = _markdown_to_html("# Hello World")
        assert "<h1" in html
        assert "Hello World" in html

    def test_table_converted(self) -> None:
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        html = _markdown_to_html(md)
        assert "<table" in html
        assert "<th" in html

    def test_fenced_code_block_converted(self) -> None:
        md = "```python\nprint('hello')\n```"
        html = _markdown_to_html(md)
        assert "<code" in html

    def test_empty_string_returns_empty_string(self) -> None:
        html = _markdown_to_html("")
        assert html == ""

    def test_inline_svg_passes_through(self) -> None:
        svg = _simple_svg()
        html = _markdown_to_html(svg)
        assert "<svg" in html


# ---------------------------------------------------------------------------
# TestBuildResultMessage
# ---------------------------------------------------------------------------


class TestBuildResultMessage:
    def test_no_diagrams(self) -> None:
        path = Path("/workspace/report.pdf")
        msg = _build_result_message(path, [])
        assert "PDF created" in msg
        assert str(path) in msg
        # No diagram stats when there are no blocks
        assert "Mermaid" not in msg

    def test_all_rendered_ok(self) -> None:
        block = _make_block("flowchart LR\n  A --> B")
        block.svg = _simple_svg()
        msg = _build_result_message(Path("/out/report.pdf"), [block])
        assert "1 total" in msg
        assert "rendered successfully" in msg
        assert "repaired" not in msg
        assert "failed" not in msg

    def test_mixed_results(self) -> None:
        ok_block = _make_block("flowchart LR\n  A --> B")
        ok_block.svg = _simple_svg()

        repaired_block = _make_block("sequenceDiagram\n  Alice->>Bob: Hi")
        repaired_block.svg = _simple_svg()
        repaired_block.ai_repaired = True

        failed_block = _make_block("stateDiagram-v2\n  [*] --> S1")
        failed_block.error = "HTTP 400"

        blocks = [ok_block, repaired_block, failed_block]
        msg = _build_result_message(Path("/out/report.pdf"), blocks)
        assert "3 total" in msg
        assert "1 rendered successfully" in msg
        assert "1 repaired by AI" in msg
        assert "1 failed" in msg

    def test_only_failed(self) -> None:
        block = _make_block("bad diagram")
        block.error = "Parse error"
        msg = _build_result_message(Path("/out/report.pdf"), [block])
        assert "failed" in msg
        assert "rendered successfully" not in msg
        assert "repaired" not in msg
