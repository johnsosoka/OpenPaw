"""Markdown to PDF conversion via md2pdf rendering service.

Sends markdown content to a local Next.js service that renders it with
browser-quality styling and native mermaid.js diagram support.

Rendering Service
-----------------
This tool depends on the md2pdf-service running locally or on the network.

  Source:  https://github.com/user/md2pdf-service (or local clone)
  Start:   cd md2pdf-service && npm run dev
  Health:  curl http://localhost:3000/api/health

The service is a Next.js app that renders markdown (including mermaid diagrams)
to PDF via Playwright page.pdf(). It will eventually be replaced by a full
reports service — see llm_memory/reports-service-project-idea.md for plans.

Set MD2PDF_SERVICE_URL in .env to override the default http://localhost:3000.
"""
import json
import logging
import os
import urllib.request
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path(os.getenv("OPENPAW_WORKSPACE_PATH", ".")).resolve()
_SERVICE_URL = os.getenv("MD2PDF_SERVICE_URL", "http://localhost:3000")


@tool
def markdown_to_pdf(markdown_path: str, output_filename: str = "") -> str:
    """Convert a markdown file to a styled PDF with rendered mermaid diagrams.

    Sends the markdown to a rendering service that uses browser-based rendering
    for professional output with native mermaid.js diagram support, syntax
    highlighting, and Tailwind Typography styling.

    Args:
        markdown_path: Path to markdown file (workspace-relative or absolute)
        output_filename: Optional output PDF filename (defaults to input name with .pdf extension)

    Returns:
        JSON string with status and output path, or error message.
    """
    logger.info(f"markdown_to_pdf called with markdown_path='{markdown_path}', output_filename='{output_filename}'")

    try:
        # Resolve input path
        input_path = Path(markdown_path)
        if not input_path.is_absolute():
            input_path = _WORKSPACE_ROOT / input_path
        input_path = input_path.resolve()

        # Validate input exists
        if not input_path.exists():
            error_msg = f"Markdown file not found: {input_path}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        # Validate input is within workspace
        try:
            input_path.relative_to(_WORKSPACE_ROOT)
        except ValueError:
            error_msg = f"Input path must be within workspace: {input_path}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        # Determine output path
        if output_filename:
            output_path = Path(output_filename)
            if not output_path.is_absolute():
                output_path = input_path.parent / output_filename
        else:
            output_path = input_path.with_suffix(".pdf")

        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Read markdown content
        logger.info(f"Reading markdown from {input_path}")
        markdown_content = input_path.read_text(encoding="utf-8")

        # Prepare request payload
        payload = json.dumps({
            "markdown": markdown_content,
            "options": {
                "format": "Letter"
            }
        }).encode("utf-8")

        # Send to rendering service
        logger.info(f"Sending {len(markdown_content)} chars to {_SERVICE_URL}/api/render")

        request = urllib.request.Request(
            f"{_SERVICE_URL}/api/render",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "OpenPaw-Krieger/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status == 200:
                    pdf_data = response.read()
                    logger.info(f"Received PDF ({len(pdf_data)} bytes)")

                    # Write PDF to workspace
                    output_path.write_bytes(pdf_data)
                    logger.info(f"PDF written to {output_path}")

                    result_data = {
                        "status": "success",
                        "output_path": str(output_path.relative_to(_WORKSPACE_ROOT)),
                        "size_kb": round(len(pdf_data) / 1024, 2),
                    }

                    return json.dumps(result_data, indent=2)
                else:
                    error_msg = f"Service returned status {response.status}"
                    logger.error(error_msg)
                    return json.dumps({"error": error_msg})

        except urllib.error.HTTPError as e:
            # Try to read error response
            try:
                error_body = e.read().decode("utf-8")
                error_data = json.loads(error_body)
                error_msg = f"Service error ({e.code}): {error_data.get('error', 'Unknown error')}"
            except Exception:
                error_msg = f"Service error ({e.code}): {e.reason}"

            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        except urllib.error.URLError as e:
            error_msg = f"Cannot reach md2pdf service at {_SERVICE_URL}. Is it running? Error: {e.reason}"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        except TimeoutError:
            error_msg = f"Service timeout after 60 seconds (mermaid rendering can be slow)"
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

    except Exception as e:
        error_msg = f"PDF conversion failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({"error": error_msg})
