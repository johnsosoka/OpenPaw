"""GPT-Researcher integration builtin.

Provides agents with deep research capabilities via a self-hosted
GPT-Researcher instance. Communicates over WebSocket for streaming
research reports and REST for document uploads.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import StructuredTool

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)

logger = logging.getLogger(__name__)


class GptResearcherTool(BaseBuiltinTool):
    """Deep research via a self-hosted GPT-Researcher instance.

    Connects to a GPT-Researcher WebSocket API to submit research queries
    and stream back full reports. Optionally supports uploading documents
    for local-source research.

    Config options:
        endpoint: WebSocket endpoint URL (required)
        upload_endpoint: REST upload endpoint URL (optional)
        timeout_seconds: Max seconds to wait for research (default: 300)
        default_report_type: Default report type (default: research_report)
        default_report_source: Default report source (default: web)
        default_tone: Default research tone (default: Objective)
    """

    metadata = BuiltinMetadata(
        name="gpt_researcher",
        display_name="GPT-Researcher",
        description="Deep research via self-hosted GPT-Researcher instance",
        builtin_type=BuiltinType.TOOL,
        group="research",
        prerequisites=BuiltinPrerequisite(packages=["websockets", "httpx"]),
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._endpoint: str = self.config.get("endpoint", "")
        self._upload_endpoint: str = self.config.get("upload_endpoint", "")
        self._timeout: int = self.config.get("timeout_seconds", 300)
        self._default_report_type: str = self.config.get(
            "default_report_type", "research_report"
        )
        self._default_report_source: str = self.config.get(
            "default_report_source", "web"
        )
        self._default_tone: str = self.config.get("default_tone", "Objective")
        self._workspace_path: Path | None = (
            Path(self.config["workspace_path"])
            if "workspace_path" in self.config
            else None
        )

    async def _run_research(
        self,
        query: str,
        report_type: Literal[
            "research_report",
            "outline_report",
            "detailed_report",
            "resource_report",
        ] | None = None,
        report_source: Literal["web", "local"] | None = None,
        tone: Literal[
            "Objective",
            "Formal",
            "Analytical",
            "Persuasive",
            "Informative",
            "Explanatory",
            "Descriptive",
            "Critical",
            "Comparative",
            "Speculative",
            "Reflective",
            "Narrative",
            "Humorous",
            "Optimistic",
            "Pessimistic",
        ] | None = None,
        source_urls: list[str] | None = None,
        query_domains: list[str] | None = None,
    ) -> str:
        """Execute a research query via GPT-Researcher WebSocket API.

        Args:
            query: The research question or topic.
            report_type: Type of report to generate.
            report_source: Source for research. 'web' for internet, 'local' for uploaded docs.
            tone: Writing tone for the report.
            source_urls: Restrict research to these specific URLs.
            query_domains: Restrict research to these domains.

        Returns:
            The full research report as markdown text.
        """
        import websockets

        if not self._endpoint:
            return "Error: GPT-Researcher endpoint not configured. Set endpoint in builtins.gpt_researcher.config."

        payload = {
            "task": query,
            "report_type": report_type or self._default_report_type,
            "report_source": report_source or self._default_report_source,
            "tone": tone or self._default_tone,
            "headers": {},
            "source_urls": source_urls or [],
            "document_urls": [],
            "query_domains": query_domains or [],
        }

        report_chunks: list[str] = []

        try:
            async with websockets.connect(
                self._endpoint, ping_interval=None
            ) as ws:
                await ws.send("start " + json.dumps(payload))

                while True:
                    try:
                        msg = await asyncio.wait_for(
                            ws.recv(), timeout=self._timeout
                        )
                        data = json.loads(msg)
                        msg_type = data.get("type", "")

                        if msg_type == "report":
                            report_chunks.append(data.get("output", ""))
                        elif msg_type == "path":
                            break
                        elif msg_type == "logs":
                            log_msg = data.get("output", "")
                            if log_msg:
                                logger.debug(
                                    f"GPT-Researcher progress: {log_msg}"
                                )
                    except TimeoutError:
                        logger.warning(
                            f"GPT-Researcher timed out after {self._timeout}s"
                        )
                        break
        except websockets.exceptions.ConnectionClosedOK:
            pass  # Server closed cleanly — return whatever was accumulated
        except Exception as e:
            logger.error(f"GPT-Researcher connection error: {e}")
            return f"Error connecting to GPT-Researcher: {e}"

        report = "".join(report_chunks)
        if not report:
            return "GPT-Researcher returned an empty report. Check the server logs for details."

        return report

    async def _upload_document(
        self,
        file_path: str,
    ) -> str:
        """Upload a workspace file to GPT-Researcher for local research.

        After uploading, use the research tool with report_source='local'
        to research against the uploaded document.

        Args:
            file_path: Path to the file within the workspace to upload.

        Returns:
            Upload status message.
        """
        import httpx

        if not self._upload_endpoint:
            return (
                "Error: GPT-Researcher upload endpoint not configured. "
                "Set upload_endpoint in builtins.gpt_researcher.config."
            )

        if not self._workspace_path:
            return "Error: Workspace path not available."

        from openpaw.agent.tools.sandbox import resolve_sandboxed_path

        try:
            resolved = resolve_sandboxed_path(self._workspace_path, file_path)
        except ValueError as e:
            return f"Error: {e}"

        if not resolved.exists():
            return f"Error: File not found: {file_path}"

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                with open(resolved, "rb") as f:
                    response = await client.post(
                        self._upload_endpoint,
                        files={"file": (resolved.name, f)},
                    )
                response.raise_for_status()
                return (
                    f"Successfully uploaded '{resolved.name}' to GPT-Researcher. "
                    "Use report_source='local' to research against uploaded documents."
                )
        except Exception as e:
            logger.error(f"GPT-Researcher upload error: {e}")
            return f"Error uploading file: {e}"

    def get_langchain_tool(self) -> list[StructuredTool]:
        """Return GPT-Researcher tools."""
        tools: list[StructuredTool] = []

        tools.append(
            StructuredTool.from_function(
                coroutine=self._run_research,
                name="research",
                description=(
                    "Submit a deep research query to GPT-Researcher. "
                    "Returns a comprehensive research report with citations. "
                    "Use for questions that need thorough web research, "
                    "literature review, or multi-source analysis. "
                    "Reports take 1-5 minutes to generate."
                ),
            )
        )

        if self._upload_endpoint:
            tools.append(
                StructuredTool.from_function(
                    coroutine=self._upload_document,
                    name="upload_research_document",
                    description=(
                        "Upload a workspace file to GPT-Researcher for "
                        "local document research. After uploading, call "
                        "the research tool with report_source='local' to "
                        "analyze the uploaded document(s)."
                    ),
                )
            )

        return tools
