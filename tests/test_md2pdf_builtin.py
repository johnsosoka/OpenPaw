"""Tests for the md2pdf builtin tool.

Covers pure helper functions, mocked network/AI calls, and the
Md2pdfToolBuiltin class itself.  WeasyPrint is always mocked because it
is a heavy optional dependency that is not required to run the test suite.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from openpaw.builtins.base import BuiltinType
from openpaw.builtins.tools.md2pdf import (
    Md2pdfToolBuiltin,
    _build_result_message,
    _extract_mermaid_blocks,
    _markdown_to_html,
    _MermaidBlock,
    _render_all_blocks,
    _render_mermaid_to_svg,
    _replace_mermaid_blocks_with_svg,
    _scale_svg_to_width,
    _try_self_heal,
)
from openpaw.builtins.tools.md2pdf_themes import DEFAULT_THEME, THEMES

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Return a temporary workspace directory."""
    ws = tmp_path / "my_agent"
    ws.mkdir()
    return ws


@pytest.fixture
def source_md(workspace: Path) -> Path:
    """Write a minimal markdown file and return its path."""
    md_file = workspace / "report.md"
    md_file.write_text("# Hello\n\nSome content here.\n", encoding="utf-8")
    return md_file


@pytest.fixture
def tool(workspace: Path) -> Md2pdfToolBuiltin:
    """Return an Md2pdfToolBuiltin wired to the temp workspace."""
    return Md2pdfToolBuiltin(config={"workspace_path": str(workspace)})


@pytest.fixture
def tool_fn(tool: Md2pdfToolBuiltin):
    """Return the inner callable from get_langchain_tool()."""
    return tool.get_langchain_tool().func


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_block(source: str, start: int = 0, end: int = 50) -> _MermaidBlock:
    return _MermaidBlock(source=source, start_pos=start, end_pos=end)


def _simple_svg(width: int = 100, height: int = 50) -> str:
    return f'<svg width="{width}" height="{height}"><rect/></svg>'


# ---------------------------------------------------------------------------
# TestMermaidExtraction
# ---------------------------------------------------------------------------


class TestMermaidExtraction:
    def test_empty_markdown_returns_no_blocks(self) -> None:
        blocks = _extract_mermaid_blocks("")
        assert blocks == []

    def test_plain_markdown_returns_no_blocks(self) -> None:
        blocks = _extract_mermaid_blocks("# Title\n\nJust a paragraph.\n")
        assert blocks == []

    def test_single_block_extracted(self) -> None:
        md = "```mermaid\nflowchart LR\n  A --> B\n```"
        blocks = _extract_mermaid_blocks(md)
        assert len(blocks) == 1
        assert blocks[0].source == "flowchart LR\n  A --> B"

    def test_multiple_blocks_extracted_in_order(self) -> None:
        md = (
            "```mermaid\nflowchart LR\n  A --> B\n```\n\n"
            "Some text.\n\n"
            "```mermaid\nsequenceDiagram\n  Alice->>Bob: Hi\n```"
        )
        blocks = _extract_mermaid_blocks(md)
        assert len(blocks) == 2
        assert "flowchart" in blocks[0].source
        assert "sequenceDiagram" in blocks[1].source

    def test_start_and_end_positions_are_set(self) -> None:
        md = "```mermaid\nflowchart LR\n  A --> B\n```"
        blocks = _extract_mermaid_blocks(md)
        assert blocks[0].start_pos == 0
        assert blocks[0].end_pos == len(md)

    def test_source_is_stripped(self) -> None:
        md = "```mermaid\n   flowchart LR\n   A --> B\n   \n```"
        blocks = _extract_mermaid_blocks(md)
        assert not blocks[0].source.startswith(" ")
        assert not blocks[0].source.endswith(" ")

    def test_initial_block_state(self) -> None:
        md = "```mermaid\nflowchart LR\n  A --> B\n```"
        block = _extract_mermaid_blocks(md)[0]
        assert block.svg is None
        assert block.error is None
        assert block.ai_repaired is False
        assert block.repair_notes is None


# ---------------------------------------------------------------------------
# TestSvgScaling
# ---------------------------------------------------------------------------


class TestSvgScaling:
    def test_small_svg_width_unchanged(self) -> None:
        svg = _simple_svg(width=100, height=50)
        result = _scale_svg_to_width(svg, max_width_px=624)
        assert 'width="100"' in result

    def test_oversized_svg_is_scaled_down(self) -> None:
        svg = _simple_svg(width=1000, height=500)
        result = _scale_svg_to_width(svg, max_width_px=500)
        assert 'width="500"' in result

    def test_aspect_ratio_preserved_on_scale(self) -> None:
        svg = _simple_svg(width=1000, height=500)
        result = _scale_svg_to_width(svg, max_width_px=500)
        assert 'height="250.0"' in result

    def test_viewbox_added_when_missing(self) -> None:
        svg = _simple_svg(width=1000, height=500)
        assert "viewBox" not in svg
        result = _scale_svg_to_width(svg, max_width_px=500)
        assert "viewBox" in result

    def test_existing_viewbox_not_duplicated(self) -> None:
        svg = '<svg width="1000" height="500" viewBox="0 0 1000 500"><rect/></svg>'
        result = _scale_svg_to_width(svg, max_width_px=500)
        assert result.count("viewBox") == 1

    def test_style_attribute_added_when_absent(self) -> None:
        svg = _simple_svg(width=100, height=50)
        result = _scale_svg_to_width(svg, max_width_px=624)
        assert "max-width: 100%" in result

    def test_existing_style_attribute_extended(self) -> None:
        svg = '<svg width="100" height="50" style="display:block;"><rect/></svg>'
        result = _scale_svg_to_width(svg, max_width_px=624)
        assert "max-width: 100%" in result
        assert "display:block;" in result


# ---------------------------------------------------------------------------
# TestReplaceMermaidBlocks
# ---------------------------------------------------------------------------


class TestReplaceMermaidBlocks:
    def _build_markdown_with_block(self) -> tuple[str, _MermaidBlock]:
        md = "```mermaid\nflowchart LR\n  A --> B\n```"
        block = _make_block("flowchart LR\n  A --> B", start=0, end=len(md))
        return md, block

    def test_successful_block_replaced_with_svg_div(self) -> None:
        md, block = self._build_markdown_with_block()
        block.svg = _simple_svg()
        result = _replace_mermaid_blocks_with_svg(md, [block])
        assert "mermaid-diagram" in result
        assert "<svg" in result
        assert "```mermaid" not in result

    def test_failed_block_replaced_with_error_placeholder(self) -> None:
        md, block = self._build_markdown_with_block()
        block.error = "HTTP 500: server error"
        result = _replace_mermaid_blocks_with_svg(md, [block])
        assert "mermaid-error" in result
        assert "Diagram render failed" in result
        assert "HTTP 500" in result
        assert "Original source" in result

    def test_ai_repaired_block_uses_repaired_class(self) -> None:
        md, block = self._build_markdown_with_block()
        block.svg = _simple_svg()
        block.ai_repaired = True
        result = _replace_mermaid_blocks_with_svg(md, [block])
        assert "diagram-repaired" in result

    def test_multiple_blocks_all_replaced(self) -> None:
        part1 = "```mermaid\nflowchart LR\n  A --> B\n```"
        sep = "\n\nMiddle text.\n\n"
        part2 = "```mermaid\nsequenceDiagram\n  Alice->>Bob: Hi\n```"
        md = part1 + sep + part2

        block1 = _make_block("flowchart LR\n  A --> B", start=0, end=len(part1))
        block2 = _make_block(
            "sequenceDiagram\n  Alice->>Bob: Hi",
            start=len(part1) + len(sep),
            end=len(md),
        )
        block1.svg = _simple_svg()
        block2.svg = _simple_svg()

        result = _replace_mermaid_blocks_with_svg(md, [block1, block2])
        assert "```mermaid" not in result
        assert result.count("mermaid-diagram") == 2

    def test_unknown_error_placeholder_shown(self) -> None:
        md, block = self._build_markdown_with_block()
        # Leave both svg and error as None — should fall back to "Unknown error"
        result = _replace_mermaid_blocks_with_svg(md, [block])
        assert "Unknown error" in result


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


# ---------------------------------------------------------------------------
# TestRenderMermaidToSvg
# ---------------------------------------------------------------------------


class TestRenderMermaidToSvg:
    def test_successful_render_returns_svg(self) -> None:
        mock_response = MagicMock()
        mock_response.text = _simple_svg(width=100, height=50)
        mock_response.raise_for_status = MagicMock()

        with patch("openpaw.builtins.tools.md2pdf.httpx.get", return_value=mock_response):
            svg, error = _render_mermaid_to_svg("flowchart LR\n  A --> B")

        assert svg is not None
        assert error is None
        assert "<svg" in svg

    def test_http_error_returns_error_message(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"

        http_error = httpx.HTTPStatusError(
            "400 Bad Request",
            request=MagicMock(),
            response=mock_response,
        )

        with patch("openpaw.builtins.tools.md2pdf.httpx.get", side_effect=http_error):
            svg, error = _render_mermaid_to_svg("invalid diagram")

        assert svg is None
        assert error is not None
        assert "400" in error

    def test_network_error_returns_error_message(self) -> None:
        with patch(
            "openpaw.builtins.tools.md2pdf.httpx.get",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            svg, error = _render_mermaid_to_svg("flowchart LR\n  A --> B")

        assert svg is None
        assert error is not None
        assert "Mermaid render failed" in error

    def test_svg_is_scaled_before_return(self) -> None:
        wide_svg = _simple_svg(width=2000, height=1000)
        mock_response = MagicMock()
        mock_response.text = wide_svg
        mock_response.raise_for_status = MagicMock()

        with patch("openpaw.builtins.tools.md2pdf.httpx.get", return_value=mock_response):
            svg, error = _render_mermaid_to_svg("flowchart LR\n  A --> B", max_width_px=500)

        assert error is None
        assert 'width="500"' in svg


# ---------------------------------------------------------------------------
# TestTrySelfHeal
# ---------------------------------------------------------------------------


class TestTrySelfHeal:
    """Test _try_self_heal behavior.

    init_chat_model is imported lazily inside the function body with
    ``from langchain.chat_models import init_chat_model``, so it is not
    a module-level name in md2pdf.  Patching at the source location
    (``langchain.chat_models.init_chat_model``) is the correct approach.
    """

    def _failed_block(self) -> _MermaidBlock:
        block = _make_block("bad -> syntax", start=0, end=50)
        block.error = "Parse error at line 1"
        return block

    def test_successful_heal_updates_block(self) -> None:
        block = self._failed_block()
        fixed_svg = _simple_svg()

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "flowchart LR\n  A --> B"
        mock_llm.invoke.return_value = mock_response

        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "success": True,
            "fixed_source": "flowchart LR\n  A --> B",
            "fixed_svg": fixed_svg,
            "repair_notes": "Fixed after 1 iteration(s)",
        }

        with patch("langchain.chat_models.init_chat_model", return_value=mock_llm), \
             patch("openpaw.builtins.tools.md2pdf._build_repair_graph", return_value=mock_graph):
            _try_self_heal(block, 624, "openai:gpt-4o-mini", 3, "full markdown context")

        assert block.svg is not None
        assert block.error is None
        assert block.ai_repaired is True

    def test_model_init_failure_leaves_block_unchanged(self) -> None:
        block = self._failed_block()
        original_error = block.error

        with patch(
            "langchain.chat_models.init_chat_model",
            side_effect=Exception("No API key"),
        ):
            _try_self_heal(block, 624, "openai:gpt-4o-mini", 3, "context")

        # Block should not be repaired
        assert block.svg is None
        assert block.error == original_error
        assert block.ai_repaired is False
        assert block.repair_notes is not None
        assert "Self-healing skipped" in block.repair_notes

    def test_graph_failure_leaves_block_unchanged(self) -> None:
        block = self._failed_block()
        original_error = block.error

        mock_llm = MagicMock()
        mock_graph = MagicMock()
        mock_graph.invoke.side_effect = RuntimeError("Graph exploded")

        with patch("langchain.chat_models.init_chat_model", return_value=mock_llm), \
             patch("openpaw.builtins.tools.md2pdf._build_repair_graph", return_value=mock_graph):
            _try_self_heal(block, 624, "openai:gpt-4o-mini", 3, "context")

        assert block.svg is None
        assert block.error == original_error
        assert block.ai_repaired is False
        assert block.repair_notes is not None
        assert "Self-healing error" in block.repair_notes

    def test_unsuccessful_heal_leaves_error_intact(self) -> None:
        block = self._failed_block()
        original_error = block.error

        mock_llm = MagicMock()
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "success": False,
            "fixed_source": None,
            "repair_notes": "Self-healing exhausted all iterations",
        }

        with patch("langchain.chat_models.init_chat_model", return_value=mock_llm), \
             patch("openpaw.builtins.tools.md2pdf._build_repair_graph", return_value=mock_graph):
            _try_self_heal(block, 624, "openai:gpt-4o-mini", 3, "context")

        assert block.svg is None
        assert block.error == original_error
        assert block.ai_repaired is False


# ---------------------------------------------------------------------------
# TestRenderAllBlocks
# ---------------------------------------------------------------------------


class TestRenderAllBlocks:
    def _block(self) -> _MermaidBlock:
        return _make_block("flowchart LR\n  A --> B")

    def test_successful_render_populates_svg(self) -> None:
        block = self._block()
        svg = _simple_svg()

        with patch(
            "openpaw.builtins.tools.md2pdf._render_mermaid_to_svg",
            return_value=(svg, None),
        ):
            _render_all_blocks(
                [block], 624, self_heal=False,
                model_spec="gpt-4o-mini", max_iterations=3, markdown_context="",
            )

        assert block.svg == svg
        assert block.error is None

    def test_failed_render_populates_error(self) -> None:
        block = self._block()

        with patch(
            "openpaw.builtins.tools.md2pdf._render_mermaid_to_svg",
            return_value=(None, "HTTP 400"),
        ):
            _render_all_blocks(
                [block], 624, self_heal=False,
                model_spec="gpt-4o-mini", max_iterations=3, markdown_context="",
            )

        assert block.svg is None
        assert block.error == "HTTP 400"

    def test_self_heal_true_triggers_heal_on_failure(self) -> None:
        block = self._block()

        with patch(
            "openpaw.builtins.tools.md2pdf._render_mermaid_to_svg",
            return_value=(None, "Parse error"),
        ), patch("openpaw.builtins.tools.md2pdf._try_self_heal") as mock_heal:
            _render_all_blocks(
                [block], 624, self_heal=True,
                model_spec="gpt-4o-mini", max_iterations=3, markdown_context="ctx",
            )

        mock_heal.assert_called_once_with(block, 624, "gpt-4o-mini", 3, "ctx")

    def test_self_heal_false_skips_heal_on_failure(self) -> None:
        block = self._block()

        with patch(
            "openpaw.builtins.tools.md2pdf._render_mermaid_to_svg",
            return_value=(None, "Parse error"),
        ), patch("openpaw.builtins.tools.md2pdf._try_self_heal") as mock_heal:
            _render_all_blocks(
                [block], 624, self_heal=False,
                model_spec="gpt-4o-mini", max_iterations=3, markdown_context="ctx",
            )

        mock_heal.assert_not_called()

    def test_self_heal_not_triggered_on_success(self) -> None:
        block = self._block()

        with patch(
            "openpaw.builtins.tools.md2pdf._render_mermaid_to_svg",
            return_value=(_simple_svg(), None),
        ), patch("openpaw.builtins.tools.md2pdf._try_self_heal") as mock_heal:
            _render_all_blocks(
                [block], 624, self_heal=True,
                model_spec="gpt-4o-mini", max_iterations=3, markdown_context="ctx",
            )

        mock_heal.assert_not_called()

    def test_multiple_blocks_all_rendered(self) -> None:
        blocks = [self._block(), self._block()]
        svgs = [_simple_svg(), _simple_svg()]
        call_count = 0

        def fake_render(source: str, max_width_px: int = 624):
            nonlocal call_count
            result = (svgs[call_count], None)
            call_count += 1
            return result

        with patch("openpaw.builtins.tools.md2pdf._render_mermaid_to_svg", side_effect=fake_render):
            _render_all_blocks(
                blocks, 624, self_heal=False,
                model_spec="gpt-4o-mini", max_iterations=3, markdown_context="",
            )

        assert call_count == 2
        for b in blocks:
            assert b.svg is not None


# ---------------------------------------------------------------------------
# TestMd2pdfToolBuiltin
# ---------------------------------------------------------------------------


class TestMd2pdfToolBuiltin:
    def test_metadata_name(self) -> None:
        assert Md2pdfToolBuiltin.metadata.name == "md2pdf"

    def test_metadata_group(self) -> None:
        assert Md2pdfToolBuiltin.metadata.group == "document"

    def test_metadata_builtin_type(self) -> None:
        assert Md2pdfToolBuiltin.metadata.builtin_type == BuiltinType.TOOL

    def test_metadata_display_name(self) -> None:
        assert Md2pdfToolBuiltin.metadata.display_name == "Markdown to PDF"

    def test_metadata_prerequisites_include_weasyprint(self) -> None:
        assert "weasyprint" in Md2pdfToolBuiltin.metadata.prerequisites.packages

    def test_default_config_values(self) -> None:
        tool = Md2pdfToolBuiltin()
        assert tool.theme == DEFAULT_THEME
        assert tool.max_diagram_width == 6.5
        assert tool.self_heal is True
        assert tool.self_heal_model == "gpt-4o-mini"
        assert tool.max_heal_iterations == 3
        assert tool.workspace_path is None

    def test_custom_config_applied(self, workspace: Path) -> None:
        tool = Md2pdfToolBuiltin(
            config={
                "workspace_path": str(workspace),
                "theme": "professional",
                "max_diagram_width": 5.0,
                "self_heal": False,
                "self_heal_model": "anthropic:claude-haiku-4-5",
                "max_heal_iterations": 1,
            }
        )
        assert tool.theme == "professional"
        assert tool.max_diagram_width == 5.0
        assert tool.self_heal is False
        assert tool.self_heal_model == "anthropic:claude-haiku-4-5"
        assert tool.max_heal_iterations == 1
        assert tool.workspace_path == workspace.resolve()

    def test_get_langchain_tool_returns_structured_tool(self, tool: Md2pdfToolBuiltin) -> None:
        from langchain_core.tools import StructuredTool

        lt = tool.get_langchain_tool()
        assert isinstance(lt, StructuredTool)

    def test_langchain_tool_name(self, tool: Md2pdfToolBuiltin) -> None:
        lt = tool.get_langchain_tool()
        assert lt.name == "markdown_to_pdf"

    def test_langchain_tool_has_description(self, tool: Md2pdfToolBuiltin) -> None:
        lt = tool.get_langchain_tool()
        assert lt.description
        assert "markdown" in lt.description.lower()

    def test_langchain_tool_schema_has_source_path(self, tool: Md2pdfToolBuiltin) -> None:
        lt = tool.get_langchain_tool()
        schema = lt.args_schema.model_json_schema()
        assert "source_path" in schema["properties"]

    def test_langchain_tool_schema_has_output_path(self, tool: Md2pdfToolBuiltin) -> None:
        lt = tool.get_langchain_tool()
        schema = lt.args_schema.model_json_schema()
        assert "output_path" in schema["properties"]

    def test_langchain_tool_schema_has_theme(self, tool: Md2pdfToolBuiltin) -> None:
        lt = tool.get_langchain_tool()
        schema = lt.args_schema.model_json_schema()
        assert "theme" in schema["properties"]


# ---------------------------------------------------------------------------
# TestToolFunction
# ---------------------------------------------------------------------------


class TestToolFunction:
    """Test the inner markdown_to_pdf callable via get_langchain_tool().func."""

    def _mock_convert_success(self, output_path: Path, blocks=None):
        """Return a mock for _convert that writes a dummy PDF and succeeds."""
        if blocks is None:
            blocks = []

        def fake_convert(source_path, output_path, css, max_width_px, self_heal, model_spec, max_iterations):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"%PDF-1.4 fake")
            msg = _build_result_message(output_path, blocks)
            return True, msg, blocks

        return fake_convert

    def test_no_workspace_path_returns_error(self) -> None:
        tool = Md2pdfToolBuiltin(config={})
        fn = tool.get_langchain_tool().func
        result = fn(source_path="report.md")
        assert "[Error:" in result
        assert "workspace_path" in result

    def test_source_not_found_returns_error(self, tool: Md2pdfToolBuiltin, workspace: Path) -> None:
        fn = tool.get_langchain_tool().func
        result = fn(source_path="nonexistent.md")
        assert "[Error:" in result
        assert "not found" in result

    def test_invalid_source_path_returns_error(self, tool: Md2pdfToolBuiltin) -> None:
        fn = tool.get_langchain_tool().func
        # Path traversal is rejected by sandbox
        result = fn(source_path="../escape.md")
        assert "[Error:" in result

    def test_success_returns_workspace_relative_path(
        self, tool: Md2pdfToolBuiltin, workspace: Path, source_md: Path
    ) -> None:
        fake_convert = self._mock_convert_success(workspace / "report.pdf")

        with patch("openpaw.builtins.tools.md2pdf._convert", side_effect=fake_convert):
            result = fn = tool.get_langchain_tool().func
            result = fn(source_path="report.md")

        assert "[Error:" not in result
        assert "report.pdf" in result
        # Must be workspace-relative, not absolute
        assert str(workspace) not in result

    def test_default_output_path_uses_pdf_extension(
        self, tool: Md2pdfToolBuiltin, workspace: Path, source_md: Path
    ) -> None:
        captured = {}

        def capturing_convert(source_path, output_path, **kwargs):
            captured["output_path"] = output_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"%PDF fake")
            return True, _build_result_message(output_path, []), []

        with patch("openpaw.builtins.tools.md2pdf._convert", side_effect=capturing_convert):
            fn = tool.get_langchain_tool().func
            fn(source_path="report.md")

        assert captured["output_path"].suffix == ".pdf"
        assert captured["output_path"].stem == "report"

    def test_invalid_theme_falls_back_to_default(
        self, tool: Md2pdfToolBuiltin, workspace: Path, source_md: Path
    ) -> None:
        captured = {}

        def capturing_convert(source_path, output_path, css, **kwargs):
            captured["css"] = css
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"%PDF fake")
            return True, _build_result_message(output_path, []), []

        with patch("openpaw.builtins.tools.md2pdf._convert", side_effect=capturing_convert):
            fn = tool.get_langchain_tool().func
            fn(source_path="report.md", theme="nonexistent_theme")

        assert captured["css"] == THEMES[DEFAULT_THEME]

    def test_valid_theme_passed_to_convert(
        self, tool: Md2pdfToolBuiltin, workspace: Path, source_md: Path
    ) -> None:
        captured = {}

        def capturing_convert(source_path, output_path, css, **kwargs):
            captured["css"] = css
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"%PDF fake")
            return True, _build_result_message(output_path, []), []

        with patch("openpaw.builtins.tools.md2pdf._convert", side_effect=capturing_convert):
            fn = tool.get_langchain_tool().func
            fn(source_path="report.md", theme="technical")

        assert captured["css"] == THEMES["technical"]

    def test_convert_failure_returns_error_string(
        self, tool: Md2pdfToolBuiltin, workspace: Path, source_md: Path
    ) -> None:
        with patch(
            "openpaw.builtins.tools.md2pdf._convert",
            return_value=(False, "PDF generation failed: disk full", []),
        ):
            fn = tool.get_langchain_tool().func
            result = fn(source_path="report.md")

        assert "[Error:" in result
        assert "PDF generation failed" in result

    def test_invalid_output_path_returns_error(
        self, tool: Md2pdfToolBuiltin, workspace: Path, source_md: Path
    ) -> None:
        fn = tool.get_langchain_tool().func
        result = fn(source_path="report.md", output_path="../outside.pdf")
        assert "[Error:" in result


# ---------------------------------------------------------------------------
# TestRegistry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_md2pdf_builtin_is_registered(self) -> None:
        from openpaw.builtins.registry import BuiltinRegistry

        BuiltinRegistry.reset()
        registry = BuiltinRegistry.get_instance()

        assert "md2pdf" in registry._tools
        assert registry._tools["md2pdf"] is Md2pdfToolBuiltin

    def test_md2pdf_in_document_group(self) -> None:
        from openpaw.builtins.registry import BuiltinRegistry

        BuiltinRegistry.reset()
        registry = BuiltinRegistry.get_instance()

        groups = registry._groups
        assert "document" in groups
        assert "md2pdf" in groups["document"]
