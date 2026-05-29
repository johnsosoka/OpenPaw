"""Core markdown-to-PDF conversion pipeline for md2pdf."""

import logging
from pathlib import Path

from openpaw.builtins.tools.md2pdf.mermaid import (
    _extract_mermaid_blocks,
    _render_all_blocks,
    _replace_mermaid_blocks_with_svg,
)
from openpaw.builtins.tools.md2pdf.models import _MermaidBlock

logger = logging.getLogger(__name__)

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
