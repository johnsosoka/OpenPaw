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

import base64
import html as html_module
import logging
import re
from pathlib import Path
from typing import Any, Literal

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.agent.tools.sandbox import resolve_sandboxed_path
from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools.md2pdf_themes import DEFAULT_THEME, THEMES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MERMAID_INK_BASE_URL = "https://mermaid.ink/svg"
MERMAID_PATTERN = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)

# Pixels per inch at standard screen DPI — used to convert inches to px
DPI = 96

# Markdown extensions for Python-Markdown
MARKDOWN_EXTENSIONS = [
    "tables",
    "fenced_code",
    "codehilite",
    "toc",
    "attr_list",
    "md_in_html",
]
MARKDOWN_EXTENSION_CONFIGS = {
    "codehilite": {
        "css_class": "codehilite",
        "guess_lang": True,
    }
}

# System prompt for the Mermaid self-healing LLM
REPAIR_SYSTEM_PROMPT = """You are a Mermaid diagram syntax expert. Your job is to fix broken Mermaid diagrams.

Rules:
1. Analyze the error message to understand what is wrong
2. Fix ONLY the syntax issues — do not change the diagram's meaning or structure
3. Return ONLY the fixed Mermaid code, no explanation or commentary
4. Do not include ```mermaid or ``` markers
5. Common issues to check:
   - Use --> not -> for arrows in flowcharts
   - Check spelling of diagram types (flowchart, sequenceDiagram, stateDiagram-v2)
   - Ensure proper participant declarations in sequence diagrams
   - Verify node IDs do not conflict with Mermaid keywords
   - Quote labels containing special characters

Return ONLY the corrected Mermaid source code."""


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class Md2pdfInput(BaseModel):
    """Input schema for the markdown_to_pdf tool."""

    source_path: str = Field(
        description="Path to the markdown file to convert (relative to workspace root)"
    )
    output_path: str | None = Field(
        default=None,
        description=(
            "Output PDF path (relative to workspace). "
            "Defaults to the same name as the source file with a .pdf extension."
        ),
    )
    theme: str | None = Field(
        default=None,
        description=(
            "CSS theme name. Valid values: "
            "'minimal' (clean serif font, light styling, academic feel), "
            "'professional' (indigo accents, sans-serif, business report look), "
            "'technical' (dark code blocks, monospace-heavy, engineering docs). "
            "Omit to use the workspace default."
        ),
    )


class _MermaidBlock:
    """Represents a single Mermaid code block extracted from markdown."""

    def __init__(self, source: str, start_pos: int, end_pos: int) -> None:
        self.source = source
        self.start_pos = start_pos
        self.end_pos = end_pos
        self.svg: str | None = None
        self.error: str | None = None
        self.ai_repaired: bool = False
        self.repair_notes: str | None = None


# ---------------------------------------------------------------------------
# Mermaid rendering
# ---------------------------------------------------------------------------


def _render_mermaid_to_svg(source: str, max_width_px: int = 624) -> tuple[str | None, str | None]:
    """Render Mermaid source to SVG using mermaid.ink.

    Args:
        source: Mermaid diagram source code.
        max_width_px: Maximum rendered width in pixels.

    Returns:
        Tuple of (svg_string, error_message). Exactly one will be non-None.
    """
    try:
        encoded = base64.urlsafe_b64encode(source.encode("utf-8")).decode("utf-8")
        url = f"{MERMAID_INK_BASE_URL}/{encoded}"

        response = httpx.get(url, timeout=30, headers={"User-Agent": "openpaw-md2pdf/1.0"})
        response.raise_for_status()

        svg = response.text
        svg = _scale_svg_to_width(svg, max_width_px)
        return svg, None

    except httpx.HTTPStatusError as e:
        body_preview = e.response.text[:200] if e.response.text else ""
        return None, f"Mermaid render failed (HTTP {e.response.status_code}): {body_preview}"
    except Exception as e:
        return None, f"Mermaid render failed: {e}"


def _scale_svg_to_width(svg: str, max_width_px: int) -> str:
    """Scale an SVG to fit within max_width_px while preserving aspect ratio.

    Modifies width/height attributes and ensures a viewBox is present so the
    SVG renders correctly in WeasyPrint.

    Args:
        svg: Raw SVG string from mermaid.ink.
        max_width_px: Target maximum width in pixels.

    Returns:
        Modified SVG string.
    """
    width_match = re.search(r'width="(\d+(?:\.\d+)?)"', svg)
    height_match = re.search(r'height="(\d+(?:\.\d+)?)"', svg)
    viewbox_match = re.search(r'viewBox="([^"]+)"', svg)

    if width_match and height_match:
        orig_width = float(width_match.group(1))
        orig_height = float(height_match.group(1))

        if orig_width > max_width_px:
            scale = max_width_px / orig_width
            new_width = max_width_px
            new_height = orig_height * scale

            # Guarantee a viewBox so browsers/WeasyPrint can scale properly
            if not viewbox_match:
                svg = svg.replace(
                    "<svg",
                    f'<svg viewBox="0 0 {orig_width} {orig_height}"',
                    1,
                )

            svg = re.sub(r'width="[\d.]+"', f'width="{new_width}"', svg)
            svg = re.sub(r'height="[\d.]+"', f'height="{new_height}"', svg)

    # Prevent overflow in WeasyPrint's fixed layout
    if 'style="' in svg:
        svg = svg.replace('style="', 'style="max-width: 100%; height: auto; ', 1)
    else:
        svg = svg.replace("<svg", '<svg style="max-width: 100%; height: auto;"', 1)

    return svg


# ---------------------------------------------------------------------------
# LangGraph self-healing subgraph
# ---------------------------------------------------------------------------




def _build_repair_graph(llm: Any) -> Any:
    """Build and compile the LangGraph repair subgraph.

    The graph follows a simple loop:
        repair → validate → (loop back to repair | END)

    Args:
        llm: An instantiated LangChain chat model.

    Returns:
        A compiled LangGraph CompiledGraph.
    """
    from typing import TypedDict

    from langchain_core.messages import HumanMessage, SystemMessage
    from langgraph.graph import END, StateGraph

    class RepairState(TypedDict):
        original_source: str
        error_message: str
        context: str
        current_source: str
        iteration: int
        max_iterations: int
        fixed_source: str | None
        fixed_svg: str | None
        repair_notes: str
        success: bool

    def attempt_repair(state: RepairState) -> RepairState:
        """Ask the LLM to fix the broken Mermaid source."""
        context_snippet = state["context"][:500] if state["context"] else "No context available"
        messages = [
            SystemMessage(content=REPAIR_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Fix this broken Mermaid diagram.\n\n"
                    f"Error: {state['error_message']}\n\n"
                    f"Broken code:\n{state['current_source']}\n\n"
                    f"Context (surrounding markdown):\n{context_snippet}\n\n"
                    f"Return ONLY the fixed Mermaid code."
                )
            ),
        ]

        response = llm.invoke(messages)
        fixed = response.content.strip()

        # Strip any accidental markdown fencing the LLM may have included
        for prefix in ("```mermaid", "```"):
            if fixed.startswith(prefix):
                fixed = fixed[len(prefix):]
        if fixed.endswith("```"):
            fixed = fixed[:-3]
        fixed = fixed.strip()

        return {
            **state,
            "current_source": fixed,
            "iteration": state["iteration"] + 1,
            "repair_notes": f"Iteration {state['iteration'] + 1}: LLM suggested a fix",
        }

    def validate_repair(state: RepairState) -> RepairState:
        """Re-render the repaired source to confirm it now works."""
        svg, error = _render_mermaid_to_svg(state["current_source"])
        if svg:
            return {
                **state,
                "success": True,
                "fixed_source": state["current_source"],
                "fixed_svg": svg,
                "repair_notes": f"Fixed after {state['iteration']} iteration(s)",
            }
        return {
            **state,
            "error_message": error or "Unknown render error",
            "repair_notes": f"Iteration {state['iteration']} still failing: {error}",
        }

    def should_continue(state: RepairState) -> Literal["repair", "end"]:
        if state["success"]:
            return "end"
        if state["iteration"] >= state["max_iterations"]:
            return "end"
        return "repair"

    workflow = StateGraph(RepairState)
    workflow.add_node("repair", attempt_repair)
    workflow.add_node("validate", validate_repair)
    workflow.set_entry_point("repair")
    workflow.add_edge("repair", "validate")
    workflow.add_conditional_edges("validate", should_continue, {"repair": "repair", "end": END})

    return workflow.compile()


def _try_self_heal(
    block: _MermaidBlock,
    max_width_px: int,
    model_spec: str,
    max_iterations: int,
    markdown_context: str,
) -> None:
    """Attempt to repair a failed Mermaid block using a LangGraph subgraph.

    Mutates `block` in place: sets svg, clears error, and marks ai_repaired
    on success. Leaves the block unchanged on failure (error remains set).

    Args:
        block: The failed Mermaid block.
        max_width_px: Maximum diagram width for the final re-render.
        model_spec: LangChain model spec string (e.g., "openai:gpt-4o-mini").
        max_iterations: Maximum repair loop iterations.
        markdown_context: Surrounding markdown for LLM context window.
    """
    try:
        from langchain.chat_models import init_chat_model

        llm = init_chat_model(model_spec, temperature=0)
        graph = _build_repair_graph(llm)
    except Exception as e:
        logger.warning(f"md2pdf: could not initialize self-heal model '{model_spec}': {e}")
        block.repair_notes = f"Self-healing skipped: {e}"
        return

    # Extract a window of context around this block
    context_start = max(0, block.start_pos - 500)
    context_end = min(len(markdown_context), block.end_pos + 500)
    local_context = markdown_context[context_start:context_end]

    initial_state = {
        "original_source": block.source,
        "error_message": block.error or "Unknown render error",
        "context": local_context,
        "current_source": block.source,
        "iteration": 0,
        "max_iterations": max_iterations,
        "fixed_source": None,
        "fixed_svg": None,
        "repair_notes": "",
        "success": False,
    }

    try:
        final_state = graph.invoke(initial_state)
    except Exception as e:
        logger.warning(f"md2pdf: self-heal graph failed: {e}")
        block.repair_notes = f"Self-healing error: {e}"
        return

    if final_state.get("success") and final_state.get("fixed_svg"):
        # SVG was already validated by the graph's validate_repair node —
        # no need for a second render call (avoids transient network failures
        # discarding a confirmed-good repair).
        svg = _scale_svg_to_width(final_state["fixed_svg"], max_width_px)
        block.svg = svg
        block.error = None
        block.ai_repaired = True
        block.repair_notes = final_state.get("repair_notes", "Repaired by AI")
        logger.info(f"md2pdf: successfully repaired Mermaid diagram — {block.repair_notes}")
    else:
        block.repair_notes = final_state.get("repair_notes", "Self-healing exhausted all iterations")


# ---------------------------------------------------------------------------
# Mermaid block extraction and replacement
# ---------------------------------------------------------------------------


def _extract_mermaid_blocks(markdown: str) -> list[_MermaidBlock]:
    """Extract all Mermaid code blocks from a markdown string.

    Args:
        markdown: Full markdown source.

    Returns:
        List of _MermaidBlock instances, in document order.
    """
    blocks = []
    for match in MERMAID_PATTERN.finditer(markdown):
        blocks.append(
            _MermaidBlock(
                source=match.group(1).strip(),
                start_pos=match.start(),
                end_pos=match.end(),
            )
        )
    return blocks


def _render_all_blocks(
    blocks: list[_MermaidBlock],
    max_width_px: int,
    self_heal: bool,
    model_spec: str,
    max_iterations: int,
    markdown_context: str,
) -> None:
    """Render all Mermaid blocks, optionally running self-healing on failures.

    Mutates each block in-place with the rendered SVG or error details.

    Args:
        blocks: Mermaid blocks to process.
        max_width_px: Maximum diagram width in pixels.
        self_heal: Whether to attempt AI repair on render failures.
        model_spec: LangChain model spec for self-healing.
        max_iterations: Maximum self-heal iterations per diagram.
        markdown_context: Full markdown source (for self-heal context window).
    """
    for block in blocks:
        svg, error = _render_mermaid_to_svg(block.source, max_width_px)
        block.svg = svg
        block.error = error

        if error and self_heal:
            logger.debug(f"md2pdf: Mermaid render failed, attempting self-heal: {error[:100]}")
            _try_self_heal(block, max_width_px, model_spec, max_iterations, markdown_context)


def _replace_mermaid_blocks_with_svg(markdown: str, blocks: list[_MermaidBlock]) -> str:
    """Substitute Mermaid code blocks with inline SVG (or error placeholders).

    Processes blocks in reverse document order so that position indices
    remain valid after each substitution.

    Args:
        markdown: Original markdown source.
        blocks: Rendered Mermaid blocks in document order.

    Returns:
        Modified markdown with SVG or error HTML in place of code blocks.
    """
    result = markdown

    for block in reversed(blocks):
        if block.svg:
            if block.ai_repaired:
                replacement = (
                    '\n<div class="mermaid-diagram diagram-repaired">\n'
                    f"{block.svg}\n"
                    "</div>\n"
                )
            else:
                replacement = (
                    '\n<div class="mermaid-diagram">\n'
                    f"{block.svg}\n"
                    "</div>\n"
                )
        else:
            error_text = html_module.escape(block.error or "Unknown error")
            source_text = html_module.escape(block.source)
            replacement = (
                '\n<div class="mermaid-error">\n'
                "<p><strong>Diagram render failed</strong></p>\n"
                f"<pre>{error_text}</pre>\n"
                "<details><summary>Original source</summary>\n"
                f"<pre><code>{source_text}</code></pre>\n"
                "</details>\n"
                "</div>\n"
            )

        result = result[: block.start_pos] + replacement + result[block.end_pos :]

    return result


# ---------------------------------------------------------------------------
# HTML and PDF generation
# ---------------------------------------------------------------------------


def _markdown_to_html(content: str) -> str:
    """Convert markdown source to an HTML fragment.

    Args:
        content: Markdown text (may contain inline SVG from Mermaid rendering).

    Returns:
        HTML fragment string (no <html>/<body> wrapper).
    """
    import markdown  # type: ignore[import-untyped]

    md = markdown.Markdown(
        extensions=MARKDOWN_EXTENSIONS,
        extension_configs=MARKDOWN_EXTENSION_CONFIGS,
    )
    return str(md.convert(content))


def _html_to_pdf(html_fragment: str, output_path: Path, css: str) -> None:
    """Render an HTML fragment to a PDF file using WeasyPrint.

    Args:
        html_fragment: Inner body HTML (no <html>/<body> wrapper).
        output_path: Destination path for the generated PDF.
        css: Full CSS string to apply.
    """
    from weasyprint import CSS, HTML

    full_html = (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head><meta charset=\"utf-8\"><title>Document</title></head>\n"
        "<body>\n"
        f"{html_fragment}\n"
        "</body>\n"
        "</html>"
    )

    html_doc = HTML(string=full_html)
    stylesheet = CSS(string=css)
    html_doc.write_pdf(str(output_path), stylesheets=[stylesheet])


# ---------------------------------------------------------------------------
# Conversion summary helpers
# ---------------------------------------------------------------------------


def _build_result_message(
    output_path: Path,
    blocks: list[_MermaidBlock],
) -> str:
    """Build a human-readable success message describing the conversion.

    Args:
        output_path: Path of the generated PDF.
        blocks: All Mermaid blocks processed during conversion.

    Returns:
        Multi-line summary string suitable for agent display.
    """
    lines = [f"PDF created: {output_path}"]

    total = len(blocks)
    if total > 0:
        rendered_ok = sum(1 for b in blocks if b.svg and not b.ai_repaired)
        repaired = sum(1 for b in blocks if b.ai_repaired)
        failed = sum(1 for b in blocks if b.error)

        lines.append(f"Mermaid diagrams: {total} total")
        if rendered_ok:
            lines.append(f"  - {rendered_ok} rendered successfully")
        if repaired:
            lines.append(f"  - {repaired} repaired by AI self-healing")
        if failed:
            lines.append(f"  - {failed} failed (error placeholder inserted)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core conversion pipeline
# ---------------------------------------------------------------------------


def _convert(
    source_path: Path,
    output_path: Path,
    css: str,
    max_width_px: int,
    self_heal: bool,
    model_spec: str,
    max_iterations: int,
) -> tuple[bool, str, list[_MermaidBlock]]:
    """Execute the full markdown-to-PDF conversion pipeline.

    Args:
        source_path: Absolute path to the source markdown file.
        output_path: Absolute path for the output PDF.
        css: CSS theme string to apply.
        max_width_px: Maximum Mermaid diagram width in pixels.
        self_heal: Whether to run AI self-healing on broken diagrams.
        model_spec: LangChain model spec for self-healing.
        max_iterations: Maximum repair iterations per broken diagram.

    Returns:
        Tuple of (success, message_or_error, mermaid_blocks).
    """
    try:
        markdown_source = source_path.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Could not read source file: {e}", []

    # Extract and render Mermaid diagrams
    blocks = _extract_mermaid_blocks(markdown_source)
    if blocks:
        logger.info(f"md2pdf: found {len(blocks)} Mermaid diagram(s), rendering...")
        _render_all_blocks(
            blocks,
            max_width_px=max_width_px,
            self_heal=self_heal,
            model_spec=model_spec,
            max_iterations=max_iterations,
            markdown_context=markdown_source,
        )
        markdown_source = _replace_mermaid_blocks_with_svg(markdown_source, blocks)

    # Convert markdown to HTML
    try:
        html_fragment = _markdown_to_html(markdown_source)
    except Exception as e:
        return False, f"Markdown-to-HTML conversion failed: {e}", blocks

    # Render HTML to PDF
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _html_to_pdf(html_fragment, output_path, css)
    except Exception as e:
        return False, f"PDF generation failed: {e}", blocks

    message = _build_result_message(output_path, blocks)
    return True, message, blocks


# ---------------------------------------------------------------------------
# Builtin class
# ---------------------------------------------------------------------------


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
