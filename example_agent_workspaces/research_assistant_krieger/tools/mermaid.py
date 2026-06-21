"""Mermaid diagram rendering tools.

Renders Mermaid diagrams to PNG using mermaid.ink API (primary) or kroki.io (fallback).
Zero external Python dependencies - uses stdlib urllib only.
"""
import base64
import json
import logging
import os
import urllib.request
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Capture workspace root at module import
_WORKSPACE_ROOT = Path(os.getenv("OPENPAW_WORKSPACE_PATH", ".")).resolve()
_REPORTS_DIR = _WORKSPACE_ROOT / "reports"


def _ensure_reports_dir() -> None:
    """Ensure reports directory exists."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _render_via_mermaid_ink(mermaid_code: str) -> bytes | None:
    """Render diagram using mermaid.ink API.

    Args:
        mermaid_code: Mermaid diagram source code

    Returns:
        PNG bytes or None if failed
    """
    try:
        # Base64 encode the diagram
        encoded = base64.urlsafe_b64encode(mermaid_code.encode("utf-8")).decode("utf-8")
        url = f"https://mermaid.ink/img/{encoded}"

        logger.info(f"Fetching from mermaid.ink: {url[:100]}...")

        req = urllib.request.Request(url, headers={"User-Agent": "OpenPaw-Mermaid/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                return response.read()

        return None

    except Exception as e:
        logger.warning(f"mermaid.ink failed: {e}")
        return None


def _render_via_kroki(mermaid_code: str) -> bytes | None:
    """Render diagram using kroki.io API.

    Args:
        mermaid_code: Mermaid diagram source code

    Returns:
        PNG bytes or None if failed
    """
    try:
        url = "https://kroki.io/mermaid/png"
        payload = json.dumps({"diagram_source": mermaid_code}).encode("utf-8")

        logger.info("Rendering via kroki.io...")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "OpenPaw-Mermaid/1.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                return response.read()

        return None

    except Exception as e:
        logger.warning(f"kroki.io failed: {e}")
        return None


@tool
def render_mermaid(mermaid_code: str, output_filename: str = "diagram.png") -> str:
    """Render a Mermaid diagram to PNG.

    Converts Mermaid markup to a PNG image using online rendering services.
    Tries mermaid.ink first, falls back to kroki.io if needed. Output is saved
    to the workspace reports directory.

    Example Mermaid code:
        graph TD
            A[Start] --> B[Process]
            B --> C[End]

    Args:
        mermaid_code: Mermaid diagram source code
        output_filename: Output PNG filename (default: diagram.png)

    Returns:
        JSON string with status, output path, and renderer used.
    """
    logger.info(f"render_mermaid called with output_filename='{output_filename}'")

    # Ensure reports directory exists
    _ensure_reports_dir()

    try:
        # Determine output path
        output_path = Path(output_filename)
        if not output_path.is_absolute():
            output_path = _REPORTS_DIR / output_filename
        output_path = output_path.resolve()

        # Ensure .png extension
        if output_path.suffix.lower() != ".png":
            output_path = output_path.with_suffix(".png")

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Try mermaid.ink first
        png_data = _render_via_mermaid_ink(mermaid_code)
        renderer = "mermaid.ink"

        # Fall back to kroki.io
        if png_data is None:
            logger.info("Falling back to kroki.io...")
            png_data = _render_via_kroki(mermaid_code)
            renderer = "kroki.io"

        # Check if rendering succeeded
        if png_data is None:
            error_msg = "All rendering services failed"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        # Save PNG
        output_path.write_bytes(png_data)
        logger.info(f"Diagram saved to {output_path}")

        result_data = {
            "status": "success",
            "output_path": str(output_path.relative_to(_WORKSPACE_ROOT)),
            "size_kb": round(len(png_data) / 1024, 2),
            "renderer": renderer,
        }

        return json.dumps(result_data, indent=2)

    except Exception as e:
        error_msg = f"Diagram rendering failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({"error": error_msg})
