"""Tests for GptResearcherTool builtin.

Covers metadata, config extraction, tool creation, research execution (mocked
WebSocket), and document upload (mocked httpx).
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.builtins.base import BuiltinType
from openpaw.builtins.tools.gpt_researcher import GptResearcherTool

try:
    import websockets.exceptions as _ws_exc

    _has_websockets = True
except ImportError:
    _has_websockets = False

try:
    import httpx as _httpx  # noqa: F401

    _has_httpx = True
except ImportError:
    _has_httpx = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ws_messages(*payloads: dict) -> list[str]:
    """Serialise a sequence of dicts to JSON strings (WebSocket message bodies)."""
    return [json.dumps(p) for p in payloads]


def _ws_mock(messages: list[str]) -> MagicMock:
    """Return an async-context-manager mock that yields a WebSocket mock.

    The WebSocket's ``recv()`` iterates through *messages* then raises
    ``StopAsyncIteration`` (simulating connection close).
    """
    ws = AsyncMock()
    ws.send = AsyncMock()

    # Each call to recv() returns the next message, then ConnectionClosedOK.
    recv_side_effects = list(messages)
    recv_side_effects.append(
        _ws_exc.ConnectionClosedOK(None, None)  # type: ignore[union-attr]
    )
    ws.recv = AsyncMock(side_effect=recv_side_effects)

    # Async context manager protocol.
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=ws)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_config() -> dict:
    """Config with only the required endpoint set."""
    return {"endpoint": "ws://localhost:8765"}


@pytest.fixture
def full_config(tmp_path: Path) -> dict:
    """Config with all optional fields set, including upload endpoint."""
    return {
        "endpoint": "ws://localhost:8765",
        "upload_endpoint": "http://localhost:8765/upload",
        "timeout_seconds": 60,
        "default_report_type": "detailed_report",
        "default_report_source": "local",
        "default_tone": "Analytical",
        "workspace_path": str(tmp_path),
    }


@pytest.fixture
def tool_minimal(minimal_config: dict) -> GptResearcherTool:
    return GptResearcherTool(config=minimal_config)


@pytest.fixture
def tool_full(full_config: dict) -> GptResearcherTool:
    return GptResearcherTool(config=full_config)


# ---------------------------------------------------------------------------
# TestMetadata
# ---------------------------------------------------------------------------


class TestMetadata:
    """Verify the class-level metadata is correct."""

    def test_name(self) -> None:
        assert GptResearcherTool.metadata.name == "gpt_researcher"

    def test_display_name(self) -> None:
        assert GptResearcherTool.metadata.display_name == "GPT-Researcher"

    def test_builtin_type_is_tool(self) -> None:
        assert GptResearcherTool.metadata.builtin_type == BuiltinType.TOOL

    def test_group_is_research(self) -> None:
        assert GptResearcherTool.metadata.group == "research"

    def test_prerequisite_package_is_websockets(self) -> None:
        assert "websockets" in GptResearcherTool.metadata.prerequisites.packages

    def test_no_env_var_prerequisites(self) -> None:
        """No API key should be required."""
        assert GptResearcherTool.metadata.prerequisites.env_vars == []


# ---------------------------------------------------------------------------
# TestConfig
# ---------------------------------------------------------------------------


class TestConfig:
    """Verify config values are correctly extracted during __init__."""

    def test_endpoint_extracted(self, tool_minimal: GptResearcherTool) -> None:
        assert tool_minimal._endpoint == "ws://localhost:8765"

    def test_upload_endpoint_defaults_to_empty_string(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        assert tool_minimal._upload_endpoint == ""

    def test_upload_endpoint_extracted(self, tool_full: GptResearcherTool) -> None:
        assert tool_full._upload_endpoint == "http://localhost:8765/upload"

    def test_timeout_defaults_to_300(self, tool_minimal: GptResearcherTool) -> None:
        assert tool_minimal._timeout == 300

    def test_timeout_overridden(self, tool_full: GptResearcherTool) -> None:
        assert tool_full._timeout == 60

    def test_default_report_type_defaults(self, tool_minimal: GptResearcherTool) -> None:
        assert tool_minimal._default_report_type == "research_report"

    def test_default_report_type_overridden(self, tool_full: GptResearcherTool) -> None:
        assert tool_full._default_report_type == "detailed_report"

    def test_default_report_source_defaults(self, tool_minimal: GptResearcherTool) -> None:
        assert tool_minimal._default_report_source == "web"

    def test_default_report_source_overridden(self, tool_full: GptResearcherTool) -> None:
        assert tool_full._default_report_source == "local"

    def test_default_tone_defaults(self, tool_minimal: GptResearcherTool) -> None:
        assert tool_minimal._default_tone == "Objective"

    def test_default_tone_overridden(self, tool_full: GptResearcherTool) -> None:
        assert tool_full._default_tone == "Analytical"

    def test_workspace_path_none_when_absent(self, tool_minimal: GptResearcherTool) -> None:
        assert tool_minimal._workspace_path is None

    def test_workspace_path_extracted_as_path(
        self, tool_full: GptResearcherTool, full_config: dict
    ) -> None:
        assert tool_full._workspace_path == Path(full_config["workspace_path"])

    def test_no_config_uses_all_defaults(self) -> None:
        tool = GptResearcherTool()
        assert tool._endpoint == ""
        assert tool._upload_endpoint == ""
        assert tool._timeout == 300
        assert tool._default_report_type == "research_report"
        assert tool._default_report_source == "web"
        assert tool._default_tone == "Objective"
        assert tool._workspace_path is None


# ---------------------------------------------------------------------------
# TestToolCreation
# ---------------------------------------------------------------------------


class TestToolCreation:
    """Verify get_langchain_tool() returns the right structure."""

    def test_returns_list(self, tool_minimal: GptResearcherTool) -> None:
        tools = tool_minimal.get_langchain_tool()
        assert isinstance(tools, list)

    def test_one_tool_without_upload_endpoint(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        tools = tool_minimal.get_langchain_tool()
        assert len(tools) == 1

    def test_two_tools_with_upload_endpoint(
        self, tool_full: GptResearcherTool
    ) -> None:
        tools = tool_full.get_langchain_tool()
        assert len(tools) == 2

    def test_research_tool_name(self, tool_minimal: GptResearcherTool) -> None:
        tools = tool_minimal.get_langchain_tool()
        assert tools[0].name == "research"

    def test_upload_tool_name(self, tool_full: GptResearcherTool) -> None:
        tools = tool_full.get_langchain_tool()
        names = {t.name for t in tools}
        assert "upload_research_document" in names

    def test_research_tool_has_description(self, tool_minimal: GptResearcherTool) -> None:
        tools = tool_minimal.get_langchain_tool()
        research_tool = tools[0]
        assert research_tool.description
        assert len(research_tool.description) > 20

    def test_upload_tool_has_description(self, tool_full: GptResearcherTool) -> None:
        tools = tool_full.get_langchain_tool()
        upload_tool = next(t for t in tools if t.name == "upload_research_document")
        assert upload_tool.description
        assert len(upload_tool.description) > 20

    def test_upload_tool_absent_without_endpoint(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        tools = tool_minimal.get_langchain_tool()
        names = {t.name for t in tools}
        assert "upload_research_document" not in names


# ---------------------------------------------------------------------------
# TestResearchExecution
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_websockets, reason="websockets not installed")
class TestResearchExecution:
    """Test _run_research via mocked WebSocket connection."""

    @pytest.mark.asyncio
    async def test_successful_research_returns_report(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        messages = _make_ws_messages(
            {"type": "logs", "output": "Searching the web..."},
            {"type": "report", "output": "# AI Landscape\n\n"},
            {"type": "report", "output": "Big models are everywhere."},
            {"type": "path", "output": "/tmp/report.pdf"},
        )

        with patch(
            "websockets.connect", return_value=_ws_mock(messages)
        ):
            result = await tool_minimal._run_research("AI landscape 2025")

        assert "AI Landscape" in result
        assert "Big models are everywhere." in result

    @pytest.mark.asyncio
    async def test_report_chunks_are_concatenated(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        messages = _make_ws_messages(
            {"type": "report", "output": "Part one. "},
            {"type": "report", "output": "Part two. "},
            {"type": "report", "output": "Part three."},
            {"type": "path", "output": "/tmp/report.pdf"},
        )

        with patch(
            "websockets.connect", return_value=_ws_mock(messages)
        ):
            result = await tool_minimal._run_research("Some query")

        assert result == "Part one. Part two. Part three."

    @pytest.mark.asyncio
    async def test_path_message_stops_iteration(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        """Messages after 'path' should not be processed."""
        messages = _make_ws_messages(
            {"type": "report", "output": "Final report."},
            {"type": "path", "output": "/tmp/report.pdf"},
            # This message arrives after path — should be ignored.
            {"type": "report", "output": "SHOULD NOT APPEAR"},
        )

        with patch(
            "websockets.connect", return_value=_ws_mock(messages)
        ):
            result = await tool_minimal._run_research("query")

        assert "SHOULD NOT APPEAR" not in result
        assert "Final report." in result

    @pytest.mark.asyncio
    async def test_empty_report_returns_error_message(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        """A path message with no preceding report chunks should surface cleanly."""
        messages = _make_ws_messages(
            {"type": "logs", "output": "Starting..."},
            {"type": "path", "output": "/tmp/report.pdf"},
        )

        with patch(
            "websockets.connect", return_value=_ws_mock(messages)
        ):
            result = await tool_minimal._run_research("empty query")

        assert "empty report" in result.lower()

    @pytest.mark.asyncio
    async def test_missing_endpoint_returns_error(self) -> None:
        """No endpoint configured should return a helpful error immediately."""
        tool = GptResearcherTool(config={})

        result = await tool._run_research("some query")

        assert "Error" in result
        assert "endpoint" in result.lower()

    @pytest.mark.asyncio
    async def test_connection_error_returns_error_string(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        with patch(
            "websockets.connect",
            side_effect=OSError("Connection refused"),
        ):
            result = await tool_minimal._run_research("query")

        assert "Error" in result
        assert "GPT-Researcher" in result

    @pytest.mark.asyncio
    async def test_timeout_breaks_loop_and_returns_partial_report(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        """asyncio.TimeoutError on recv() should break the loop; partial
        content accumulated before the timeout is returned."""
        ws = AsyncMock()
        ws.send = AsyncMock()

        call_count = 0

        async def recv_with_timeout():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps({"type": "report", "output": "Partial content."})
            raise TimeoutError()

        ws.recv = recv_with_timeout

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=ws)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("websockets.connect", return_value=cm):
            result = await tool_minimal._run_research("slow query")

        assert "Partial content." in result

    @pytest.mark.asyncio
    async def test_payload_includes_query_as_task(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        """Verify the WebSocket send payload contains the query as 'task'."""
        captured_payload: dict = {}

        ws = AsyncMock()

        async def capture_send(data: str) -> None:
            prefix, payload_json = data.split(" ", 1)
            captured_payload.update(json.loads(payload_json))

        ws.send = capture_send
        ws.recv = AsyncMock(
            side_effect=[
                json.dumps({"type": "path", "output": "/tmp/r.pdf"}),
            ]
        )

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=ws)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("websockets.connect", return_value=cm):
            await tool_minimal._run_research("quantum computing")

        assert captured_payload.get("task") == "quantum computing"

    @pytest.mark.asyncio
    async def test_payload_uses_default_report_type(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        captured_payload: dict = {}

        ws = AsyncMock()

        async def capture_send(data: str) -> None:
            _, payload_json = data.split(" ", 1)
            captured_payload.update(json.loads(payload_json))

        ws.send = capture_send
        ws.recv = AsyncMock(
            side_effect=[json.dumps({"type": "path", "output": "/tmp/r.pdf"})]
        )

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=ws)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("websockets.connect", return_value=cm):
            await tool_minimal._run_research("query")

        assert captured_payload.get("report_type") == "research_report"

    @pytest.mark.asyncio
    async def test_explicit_report_type_overrides_default(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        captured_payload: dict = {}

        ws = AsyncMock()

        async def capture_send(data: str) -> None:
            _, payload_json = data.split(" ", 1)
            captured_payload.update(json.loads(payload_json))

        ws.send = capture_send
        ws.recv = AsyncMock(
            side_effect=[json.dumps({"type": "path", "output": "/tmp/r.pdf"})]
        )

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=ws)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("websockets.connect", return_value=cm):
            await tool_minimal._run_research(
                "query", report_type="outline_report"
            )

        assert captured_payload.get("report_type") == "outline_report"

    @pytest.mark.asyncio
    async def test_source_urls_included_in_payload(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        captured_payload: dict = {}

        ws = AsyncMock()

        async def capture_send(data: str) -> None:
            _, payload_json = data.split(" ", 1)
            captured_payload.update(json.loads(payload_json))

        ws.send = capture_send
        ws.recv = AsyncMock(
            side_effect=[json.dumps({"type": "path", "output": "/tmp/r.pdf"})]
        )

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=ws)
        cm.__aexit__ = AsyncMock(return_value=False)

        urls = ["https://example.com", "https://docs.python.org"]
        with patch("websockets.connect", return_value=cm):
            await tool_minimal._run_research("query", source_urls=urls)

        assert captured_payload.get("source_urls") == urls

    @pytest.mark.asyncio
    async def test_logs_messages_do_not_appear_in_report(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        messages = _make_ws_messages(
            {"type": "logs", "output": "DEBUG: internal log detail"},
            {"type": "report", "output": "Clean report text."},
            {"type": "path", "output": "/tmp/report.pdf"},
        )

        with patch(
            "websockets.connect", return_value=_ws_mock(messages)
        ):
            result = await tool_minimal._run_research("query")

        assert "DEBUG: internal log detail" not in result
        assert "Clean report text." in result


# ---------------------------------------------------------------------------
# TestDocumentUpload
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_httpx, reason="httpx not installed")
class TestDocumentUpload:
    """Test _upload_document via mocked httpx."""

    @pytest.mark.asyncio
    async def test_missing_upload_endpoint_returns_error(
        self, tool_minimal: GptResearcherTool
    ) -> None:
        """Tool without upload_endpoint should return a config error."""
        result = await tool_minimal._upload_document("report.pdf")

        assert "Error" in result
        assert "upload_endpoint" in result

    @pytest.mark.asyncio
    async def test_missing_workspace_path_returns_error(self) -> None:
        """upload_endpoint present but no workspace_path should error."""
        tool = GptResearcherTool(
            config={"upload_endpoint": "http://localhost/upload"}
        )
        result = await tool._upload_document("file.pdf")

        assert "Error" in result
        assert "workspace" in result.lower()

    @pytest.mark.asyncio
    async def test_successful_upload(self, tmp_path: Path) -> None:
        """Happy path: file exists, HTTP 200 → success message."""
        sample_file = tmp_path / "paper.pdf"
        sample_file.write_bytes(b"%PDF-1.4 content")

        tool = GptResearcherTool(
            config={
                "upload_endpoint": "http://localhost:8765/upload",
                "workspace_path": str(tmp_path),
            }
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool._upload_document("paper.pdf")

        assert "Successfully uploaded" in result
        assert "paper.pdf" in result
        assert "local" in result.lower()

    @pytest.mark.asyncio
    async def test_file_not_found_returns_error(self, tmp_path: Path) -> None:
        tool = GptResearcherTool(
            config={
                "upload_endpoint": "http://localhost/upload",
                "workspace_path": str(tmp_path),
            }
        )

        result = await tool._upload_document("nonexistent.pdf")

        assert "Error" in result
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_http_error_returns_error_string(self, tmp_path: Path) -> None:
        """HTTP errors from the server should surface as user-friendly strings."""
        sample_file = tmp_path / "report.pdf"
        sample_file.write_bytes(b"content")

        tool = GptResearcherTool(
            config={
                "upload_endpoint": "http://localhost/upload",
                "workspace_path": str(tmp_path),
            }
        )

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        http_error = httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=mock_response,
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=http_error)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool._upload_document("report.pdf")

        assert "Error" in result

    @pytest.mark.asyncio
    async def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """Path traversal attempts must be caught by sandbox validation."""
        tool = GptResearcherTool(
            config={
                "upload_endpoint": "http://localhost/upload",
                "workspace_path": str(tmp_path),
            }
        )

        result = await tool._upload_document("../etc/passwd")

        assert "Error" in result

    @pytest.mark.asyncio
    async def test_absolute_path_rejected(self, tmp_path: Path) -> None:
        """Absolute paths must be rejected by sandbox validation."""
        tool = GptResearcherTool(
            config={
                "upload_endpoint": "http://localhost/upload",
                "workspace_path": str(tmp_path),
            }
        )

        result = await tool._upload_document("/etc/passwd")

        assert "Error" in result

    @pytest.mark.asyncio
    async def test_upload_sends_file_to_correct_endpoint(
        self, tmp_path: Path
    ) -> None:
        """Verify the POST goes to the configured upload_endpoint."""
        sample_file = tmp_path / "data.txt"
        sample_file.write_text("data content")

        upload_url = "http://myresearcher.internal/v1/upload"
        tool = GptResearcherTool(
            config={
                "upload_endpoint": upload_url,
                "workspace_path": str(tmp_path),
            }
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await tool._upload_document("data.txt")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == upload_url

    @pytest.mark.asyncio
    async def test_upload_uses_filename_as_form_key(self, tmp_path: Path) -> None:
        """The multipart POST should use ``file`` as the form field name."""
        sample_file = tmp_path / "notes.txt"
        sample_file.write_text("notes")

        tool = GptResearcherTool(
            config={
                "upload_endpoint": "http://localhost/upload",
                "workspace_path": str(tmp_path),
            }
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await tool._upload_document("notes.txt")

        call_kwargs = mock_client.post.call_args[1]
        assert "files" in call_kwargs
        assert "file" in call_kwargs["files"]

    @pytest.mark.asyncio
    async def test_upload_from_subdirectory(self, tmp_path: Path) -> None:
        """Files nested in workspace subdirectories should be uploadable."""
        subdir = tmp_path / "reports"
        subdir.mkdir()
        sample_file = subdir / "q4.pdf"
        sample_file.write_bytes(b"%PDF content")

        tool = GptResearcherTool(
            config={
                "upload_endpoint": "http://localhost/upload",
                "workspace_path": str(tmp_path),
            }
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await tool._upload_document("reports/q4.pdf")

        assert "Error" not in result
        assert "q4.pdf" in result
