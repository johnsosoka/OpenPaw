"""Research tools using GPT Researcher.

Provides deep research capabilities via GPT Researcher library and report management.
Requires gpt-researcher>=0.14.6 and appropriate API keys in workspace .env.
"""
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Capture workspace root at module import
_WORKSPACE_ROOT = Path(os.getenv("OPENPAW_WORKSPACE_PATH", ".")).resolve()
_REPORTS_DIR = _WORKSPACE_ROOT / "reports"


def _ensure_reports_dir() -> None:
    """Ensure reports directory exists."""
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(text: str, max_words: int = 5) -> str:
    """Convert text to filesystem-safe slug.

    Args:
        text: Text to slugify
        max_words: Maximum number of words to include

    Returns:
        Lowercase hyphenated slug with only alphanumeric characters
    """
    # Take first N words
    words = text.strip().split()[:max_words]
    slug = "-".join(words)

    # Keep only alphanumeric and hyphens, lowercase
    slug = re.sub(r"[^a-z0-9-]", "", slug.lower())

    # Remove consecutive hyphens
    slug = re.sub(r"-+", "-", slug)

    return slug.strip("-")


def _save_report_with_frontmatter(
    report_content: str,
    filepath: Path,
    query: str,
    report_type: str,
    source_count: int,
) -> None:
    """Save report with YAML frontmatter.

    Args:
        report_content: The report markdown content
        filepath: Path to save report
        query: Original research query
        report_type: Type of report generated
        source_count: Number of sources used
    """
    word_count = len(report_content.split())
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Quote query to handle special YAML chars (colons, brackets, etc.)
    safe_query = query.replace('"', '\\"')

    frontmatter = f"""---
title: Research Report
date: "{timestamp}"
query: "{safe_query}"
report_type: {report_type}
sources_count: {source_count}
word_count: {word_count}
---

"""

    full_content = frontmatter + report_content
    filepath.write_text(full_content, encoding="utf-8")


@tool
async def deep_research(query: str, report_type: str = "research_report") -> str:
    """Conduct deep research using GPT Researcher and save the report.

    Runs a comprehensive research process using multiple sources, analyzes
    the information, and generates a detailed report saved to the workspace
    reports directory.

    Valid report types:
    - research_report: Standard comprehensive report (default)
    - deep: Extra thorough research with more sources
    - resource_report: Focus on finding and listing resources
    - outline_report: Structured outline format

    Args:
        query: Research question or topic to investigate
        report_type: Type of report to generate (default: research_report)

    Returns:
        JSON string with research summary including word count, source count,
        report path, and first 500 characters of the report.
    """
    logger.info(f"deep_research called with query='{query}', report_type='{report_type}'")

    # Validate dependencies
    try:
        from gpt_researcher import GPTResearcher
    except ImportError:
        error_msg = (
            "GPT Researcher not installed. "
            "Run: pip install gpt-researcher>=0.14.6"
        )
        logger.error(error_msg)
        return json.dumps({"error": error_msg})

    # Validate report type
    valid_types = ["research_report", "deep", "resource_report", "outline_report"]
    if report_type not in valid_types:
        error_msg = f"Invalid report_type '{report_type}'. Valid options: {', '.join(valid_types)}"
        logger.error(error_msg)
        return json.dumps({"error": error_msg})

    # Ensure reports directory exists
    _ensure_reports_dir()

    try:
        # Initialize researcher
        logger.info("Initializing GPT Researcher...")
        researcher = GPTResearcher(
            query=query,
            report_type=report_type,
            report_source="web",
        )

        # Conduct research
        logger.info("Conducting research...")
        await researcher.conduct_research()

        # Get metadata and validate research results
        sources = researcher.get_research_sources()
        source_count = len(sources) if sources else 0

        try:
            costs = researcher.get_costs()
            logger.info(f"Research completed: {source_count} sources, costs: ${costs}")
        except Exception as e:
            logger.warning(f"Could not get research costs: {e}")
            costs = 0.0

        # CRITICAL: Validate that research actually found sources
        if source_count == 0:
            error_details = {
                "error": "Research returned no sources",
                "query": query,
                "report_type": report_type,
                "execution_time_seconds": "6-12 (abnormally fast)",
                "costs": f"${costs}",
                "diagnostic_hints": [
                    "Check TAVILY_API_KEY validity and quota",
                    "The tvly-dev- prefix suggests a development key with rate limits",
                    "Verify network connectivity to Tavily API",
                    "Consider switching RETRIEVER to 'duckduckgo' in .env as fallback",
                    "Development keys may have concurrent request limits (100/min)"
                ],
                "tavily_key_prefix": os.getenv("TAVILY_API_KEY", "")[:8] + "...",
                "retriever_config": os.getenv("RETRIEVER", "not set"),
            }
            logger.error(f"Research failed: {error_details}")
            return json.dumps(error_details, indent=2)

        # Log warning if costs are suspiciously low
        if costs == 0.0:
            logger.warning(
                f"Research completed with $0.00 costs. This suggests the research phase "
                f"may not have executed properly. Found {source_count} sources."
            )

        # Generate report
        logger.info("Writing report...")
        report = await researcher.write_report()

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _slugify(query)
        filename = f"{timestamp}_{slug}.md"
        filepath = _REPORTS_DIR / filename

        # Save with frontmatter
        _save_report_with_frontmatter(
            report_content=report,
            filepath=filepath,
            query=query,
            report_type=report_type,
            source_count=source_count,
        )

        logger.info(f"Report saved to {filepath}")

        # Prepare compact summary — agent can read_file for full content
        word_count = len(report.split())
        report_path = str(filepath.relative_to(_WORKSPACE_ROOT))

        result = {
            "status": "success",
            "word_count": word_count,
            "source_count": source_count,
            "report_path": report_path,
            "message": f"Report saved to {report_path}. Use read_file to review the full content.",
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        error_msg = f"Research failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({"error": error_msg})


@tool
def list_reports() -> str:
    """List all saved research reports in the workspace.

    Returns:
        JSON string with list of reports including filename and size,
        or empty list if no reports exist.
    """
    logger.info("list_reports called")

    if not _REPORTS_DIR.exists():
        return json.dumps({"reports": []})

    try:
        reports = []
        for filepath in sorted(_REPORTS_DIR.glob("*.md"), reverse=True):
            size_kb = filepath.stat().st_size / 1024
            reports.append({
                "filename": filepath.name,
                "size_kb": round(size_kb, 2),
                "path": str(filepath.relative_to(_WORKSPACE_ROOT)),
            })

        result = {
            "reports": reports,
            "count": len(reports),
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        error_msg = f"Failed to list reports: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return json.dumps({"error": error_msg})
