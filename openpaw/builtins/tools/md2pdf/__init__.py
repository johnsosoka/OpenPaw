"""Markdown-to-PDF conversion builtin tool.

Converts workspace markdown files to polished PDF documents with:
- Three CSS themes: minimal, professional, technical
- Mermaid diagram rendering via mermaid.ink HTTP API
- Optional LangGraph self-healing for broken Mermaid diagrams
- Syntax-highlighted code blocks via Pygments
- Tables, TOC, and other standard markdown extensions

Dependencies (optional, checked at runtime via prerequisites):
    weasyprint: HTML-to-PDF rendering
    markdown: Markdown-to-HTML conversion
    pygments: Syntax highlighting (pulled in by markdown[codehilite])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from openpaw.agent.tools.sandbox import resolve_sandboxed_path
from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools.md2pdf.converter import (
    _build_result_message,
    _convert,
    _html_to_pdf,
    _markdown_to_html,
)
from openpaw.builtins.tools.md2pdf.mermaid import (
    DPI,
    MERMAID_INK_BASE_URL,
    MERMAID_PATTERN,
    REPAIR_SYSTEM_PROMPT,
    _build_repair_graph,
    _extract_mermaid_blocks,
    _render_all_blocks,
    _render_mermaid_to_svg,
    _replace_mermaid_blocks_with_svg,
    _scale_svg_to_width,
    _try_self_heal,
)
from openpaw.builtins.tools.md2pdf.models import (
    Md2pdfInput,
    RepairState,
    _MermaidBlock,
)
from openpaw.builtins.tools.md2pdf_themes import DEFAULT_THEME, THEMES

logger = logging.getLogger(__name__)

# Re-export all public symbols so existing imports continue to work
__all__ = [
    "Md2pdfToolBuiltin",
    "Md2pdfInput",
    "RepairState",
    "_MermaidBlock",
    "MERMAID_INK_BASE_URL",
    "MERMAID_PATTERN",
    "DPI",
    "REPAIR_SYSTEM_PROMPT",
    "_render_mermaid_to_svg",
    "_scale_svg_to_width",
    "_build_repair_graph",
    "_try_self_heal",
    "_extract_mermaid_blocks",
    "_render_all_blocks",
    "_replace_mermaid_blocks_with_svg",
    "_markdown_to_html",
    "_html_to_pdf",
    "_convert",
    "_build_result_message",
]


class Md2pdfToolBuiltin(BaseBuiltinTool):
    """Markdown-to-PDF conversion tool for agent workspaces.

    Converts workspace markdown files to polished PDF documents. Supports
    three CSS themes, Mermaid diagram rendering via mermaid.ink, and optional
    AI self-healing for broken diagrams.

    Config options (from workspace agent.yaml or global config):
        theme: CSS theme name — "minimal", "professional", or "technical" (default: "minimal")
        max_diagram_width: Max Mermaid diagram width in inches (default: 6.5)
        self_heal: Enable AI repair for broken Mermaid diagrams (default: True)
        self_heal_model: LangChain model spec for self-healing (default: "gpt-4o-mini")
        max_heal_iterations: Max repair attempts per diagram (default: 3)
    """

    metadata = BuiltinMetadata(
        name="md2pdf",
        display_name="Markdown to PDF",
        description="Convert markdown files to PDF with theme support and Mermaid diagrams",
        builtin_type=BuiltinType.TOOL,
        group="document",
        prerequisites=BuiltinPrerequisite(packages=["weasyprint", "markdown", "pygments"]),
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)

        cfg = config or {}

        self.workspace_path: Path | None = (
            Path(cfg["workspace_path"]).resolve() if cfg.get("workspace_path") else None
        )
        self.theme: str = cfg.get("theme", DEFAULT_THEME)
        self.max_diagram_width: float = cfg.get("max_diagram_width", 6.5)
        self.self_heal: bool = cfg.get("self_heal", True)
        # Accept both bare model names ("gpt-4o-mini") and provider-prefixed specs
        # ("openai:gpt-4o-mini", "anthropic:claude-haiku").  init_chat_model handles both.
        self.self_heal_model: str = cfg.get("self_heal_model", "gpt-4o-mini")
        self.max_heal_iterations: int = cfg.get("max_heal_iterations", 3)

    def get_langchain_tool(self) -> Any:
        """Return the markdown_to_pdf tool as a LangChain StructuredTool."""

        def markdown_to_pdf(
            source_path: str,
            output_path: str | None = None,
            theme: str | None = None,
        ) -> str:
            """Convert a workspace markdown file to a PDF document.

            Args:
                source_path: Relative path to the markdown file within the workspace.
                output_path: Optional output PDF path (relative to workspace).
                             Defaults to the source filename with a .pdf extension.
                theme: Optional CSS theme override: 'minimal', 'professional', or 'technical'.

            Returns:
                Success message with the PDF path, or a descriptive error string.
            """
            if not self.workspace_path:
                return "[Error: markdown_to_pdf is not available (workspace_path not configured)]"

            # Resolve and validate source path
            try:
                resolved_source = resolve_sandboxed_path(self.workspace_path, source_path)
            except ValueError as e:
                return f"[Error: Invalid source path: {e}]"

            if not resolved_source.exists():
                return f"[Error: Source file not found: {source_path}]"
            if not resolved_source.is_file():
                return f"[Error: Source path is not a file: {source_path}]"

            # Resolve and validate output path
            if output_path:
                try:
                    resolved_output = resolve_sandboxed_path(self.workspace_path, output_path)
                except ValueError as e:
                    return f"[Error: Invalid output path: {e}]"
            else:
                # Default: same location as source, .pdf extension
                resolved_output = resolved_source.with_suffix(".pdf")

            # Select theme CSS
            active_theme = theme or self.theme
            if active_theme not in THEMES:
                known = ", ".join(sorted(THEMES.keys()))
                logger.warning(
                    f"md2pdf: unknown theme '{active_theme}', falling back to '{DEFAULT_THEME}'. "
                    f"Available: {known}"
                )
                active_theme = DEFAULT_THEME
            css = THEMES[active_theme]

            max_width_px = int(self.max_diagram_width * DPI)

            logger.info(
                f"md2pdf: converting '{source_path}' → '{resolved_output.name}' "
                f"(theme={active_theme}, self_heal={self.self_heal})"
            )

            success, message, _blocks = _convert(
                source_path=resolved_source,
                output_path=resolved_output,
                css=css,
                max_width_px=max_width_px,
                self_heal=self.self_heal,
                model_spec=self.self_heal_model,
                max_iterations=self.max_heal_iterations,
            )

            if success:
                # Return a workspace-relative path so the agent can reference it
                try:
                    relative_output = resolved_output.relative_to(self.workspace_path)
                    return message.replace(str(resolved_output), str(relative_output), 1)
                except ValueError:
                    return message
            else:
                return f"[Error: {message}]"

        return StructuredTool.from_function(
            func=markdown_to_pdf,
            name="markdown_to_pdf",
            description=(
                "Convert a markdown file in your workspace to a polished PDF document. "
                "Supports Mermaid diagrams (rendered via mermaid.ink), syntax-highlighted "
                "code blocks, tables, and a table of contents. "
                "Available themes: 'minimal' (clean, academic), 'professional' (business report), "
                "'technical' (code-dense, dark code blocks). "
                "Provide a relative path to the markdown file. "
                "The PDF will be saved alongside the source file unless output_path is specified."
            ),
            args_schema=Md2pdfInput,
        )
