"""Tests for the md2pdf builtin class and tool function.

Covers the Md2pdfToolBuiltin class, its inner callable, and registry
integration.  WeasyPrint is always mocked because it is a heavy optional
dependency that is not required to run the test suite.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from openpaw.builtins.base import BuiltinType
from openpaw.builtins.tools.md2pdf import (
    Md2pdfToolBuiltin,
    _build_result_message,
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
