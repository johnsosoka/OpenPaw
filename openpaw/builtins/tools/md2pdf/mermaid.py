"""Mermaid diagram rendering and self-healing for md2pdf."""

import base64
import html as html_module
import logging
import re
from typing import Any, Literal

import httpx

from openpaw.builtins.tools.md2pdf.models import (
    RepairState,
    _MermaidBlock,
)

logger = logging.getLogger(__name__)

MERMAID_INK_BASE_URL = "https://mermaid.ink/svg"
MERMAID_PATTERN = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)

# Pixels per inch at standard screen DPI — used to convert inches to px
DPI = 96

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

    except httpx.HTTPError as e:
        return None, f"Mermaid render failed (network error): {e}"
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


def _build_repair_graph(llm: Any) -> Any:
    """Build and compile the LangGraph repair subgraph.

    The graph follows a simple loop:
        repair → validate → (loop back to repair | END)

    Args:
        llm: An instantiated LangChain chat model.

    Returns:
        A compiled LangGraph CompiledGraph.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from langgraph.graph import END, StateGraph

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
