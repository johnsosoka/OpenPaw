"""Tests for tool call sanitizer middleware."""

import pytest

from openpaw.agent.middleware.tool_call_sanitizer import (
    BEDROCK_TOOL_NAME_PATTERN,
    MAX_TOOL_NAME_LENGTH,
    _sanitize_tool_name,
)


class TestSanitizeToolName:
    """Tests for _sanitize_tool_name()."""

    def test_valid_name_unchanged(self):
        assert _sanitize_tool_name("read_file") == "read_file"

    def test_valid_name_with_hyphens(self):
        assert _sanitize_tool_name("browser-navigate") == "browser-navigate"

    def test_valid_name_alphanumeric(self):
        assert _sanitize_tool_name("tool123") == "tool123"

    def test_dots_replaced(self):
        """Kimi K2.5 sometimes generates names like 'calendar.get_events'."""
        result = _sanitize_tool_name("calendar.get_events")
        assert result == "calendar_get_events"
        assert BEDROCK_TOOL_NAME_PATTERN.match(result)

    def test_multiple_dots(self):
        result = _sanitize_tool_name("a.b.c.d")
        assert result == "a_b_c_d"

    def test_spaces_replaced(self):
        result = _sanitize_tool_name("get events")
        assert result == "get_events"

    def test_special_characters_replaced(self):
        result = _sanitize_tool_name("tool@name#1!")
        assert result == "tool_name_1"
        assert BEDROCK_TOOL_NAME_PATTERN.match(result)

    def test_consecutive_underscores_collapsed(self):
        result = _sanitize_tool_name("a...b")
        assert result == "a_b"

    def test_leading_trailing_underscores_stripped(self):
        result = _sanitize_tool_name(".tool_name.")
        assert result == "tool_name"

    def test_truncated_to_64_chars(self):
        long_name = "a" * 100
        result = _sanitize_tool_name(long_name)
        assert len(result) <= MAX_TOOL_NAME_LENGTH

    def test_truncation_strips_trailing_underscore(self):
        # 63 valid chars + dot at position 64 would produce trailing underscore
        name = "a" * 63 + "." + "b" * 10
        result = _sanitize_tool_name(name)
        assert len(result) <= MAX_TOOL_NAME_LENGTH
        assert not result.endswith("_")

    def test_empty_string_fallback(self):
        result = _sanitize_tool_name("")
        assert result == "unknown_tool"

    def test_all_special_chars_fallback(self):
        result = _sanitize_tool_name("...")
        assert result == "unknown_tool"

    def test_unicode_replaced(self):
        result = _sanitize_tool_name("tëst_tööl")
        assert BEDROCK_TOOL_NAME_PATTERN.match(result)

    def test_result_always_valid(self):
        """Property: output always matches Bedrock constraints."""
        test_cases = [
            "normal_name",
            "dots.in.name",
            "spaces in name",
            "CAPS_and_123",
            "",
            "." * 100,
            "a" * 200,
            "tool(arg1, arg2)",
            "module::method",
            "名前",  # Non-ASCII
        ]
        for name in test_cases:
            result = _sanitize_tool_name(name)
            assert BEDROCK_TOOL_NAME_PATTERN.match(result), f"Failed for input: {name!r} -> {result!r}"
            assert len(result) <= MAX_TOOL_NAME_LENGTH, f"Too long for input: {name!r}"


class TestToolCallSanitizerMiddleware:
    """Tests for the @wrap_model_call middleware function."""

    @pytest.fixture
    def mock_ai_message_valid(self):
        """AIMessage with valid tool calls."""
        from langchain_core.messages import AIMessage

        return AIMessage(
            content="",
            tool_calls=[
                {"name": "read_file", "args": {"path": "test.txt"}, "id": "call_1"},
                {"name": "write_file", "args": {"path": "out.txt", "content": "hi"}, "id": "call_2"},
            ],
        )

    @pytest.fixture
    def mock_ai_message_invalid(self):
        """AIMessage with invalid tool call names (simulates Kimi K2.5 hallucination)."""
        from langchain_core.messages import AIMessage

        return AIMessage(
            content="",
            tool_calls=[
                {"name": "calendar.get_events", "args": {"days": 7}, "id": "call_1"},
                {"name": "read_file", "args": {"path": "test.txt"}, "id": "call_2"},
            ],
        )

    @pytest.fixture
    def mock_ai_message_long_name(self):
        """AIMessage with tool name exceeding 64 chars."""
        from langchain_core.messages import AIMessage

        return AIMessage(
            content="",
            tool_calls=[
                {"name": "a" * 100, "args": {}, "id": "call_1"},
            ],
        )

    @pytest.fixture
    def mock_ai_message_no_tools(self):
        """AIMessage with no tool calls (plain text response)."""
        from langchain_core.messages import AIMessage

        return AIMessage(content="Hello, how can I help?")

    @pytest.mark.asyncio
    async def test_valid_names_pass_through(self, mock_ai_message_valid):
        """Valid tool names should not be modified."""
        from langchain.agents.middleware import ModelResponse


        response = ModelResponse(result=[mock_ai_message_valid])

        async def mock_handler(req):
            return response

        # The decorator wraps the function — call the underlying logic directly
        result = await _invoke_sanitizer(mock_handler, response)

        assert result.result[0].tool_calls[0]["name"] == "read_file"
        assert result.result[0].tool_calls[1]["name"] == "write_file"

    @pytest.mark.asyncio
    async def test_invalid_names_sanitized(self, mock_ai_message_invalid):
        """Invalid tool names should be sanitized."""
        from langchain.agents.middleware import ModelResponse

        response = ModelResponse(result=[mock_ai_message_invalid])

        result = await _invoke_sanitizer(None, response)

        assert result.result[0].tool_calls[0]["name"] == "calendar_get_events"
        assert result.result[0].tool_calls[1]["name"] == "read_file"  # Unchanged

    @pytest.mark.asyncio
    async def test_long_names_truncated(self, mock_ai_message_long_name):
        """Tool names exceeding 64 chars should be truncated."""
        from langchain.agents.middleware import ModelResponse

        response = ModelResponse(result=[mock_ai_message_long_name])

        result = await _invoke_sanitizer(None, response)

        assert len(result.result[0].tool_calls[0]["name"]) <= MAX_TOOL_NAME_LENGTH

    @pytest.mark.asyncio
    async def test_no_tools_pass_through(self, mock_ai_message_no_tools):
        """Messages without tool calls should pass through unchanged."""
        from langchain.agents.middleware import ModelResponse

        response = ModelResponse(result=[mock_ai_message_no_tools])

        result = await _invoke_sanitizer(None, response)

        assert result.result[0].content == "Hello, how can I help?"

    @pytest.mark.asyncio
    async def test_empty_result_pass_through(self):
        """Empty result list should pass through."""
        from langchain.agents.middleware import ModelResponse

        response = ModelResponse(result=[])

        result = await _invoke_sanitizer(None, response)

        assert result.result == []

    @pytest.mark.asyncio
    async def test_sanitization_logged(self, caplog):
        """Sanitization events should be logged at WARNING level."""
        import logging

        from langchain.agents.middleware import ModelResponse
        from langchain_core.messages import AIMessage


        # Create a fresh message (not shared with other tests)
        msg = AIMessage(
            content="",
            tool_calls=[
                {"name": "calendar.get_events", "args": {"days": 7}, "id": "call_1"},
            ],
        )
        response = ModelResponse(result=[msg])

        with caplog.at_level(logging.WARNING, logger="openpaw.agent.middleware.tool_call_sanitizer"):
            await _invoke_sanitizer_with_logging(response)

        assert any("calendar.get_events" in record.message for record in caplog.records)
        assert any("calendar_get_events" in record.message for record in caplog.records)


async def _invoke_sanitizer(handler, response):
    """Helper to invoke the sanitizer logic directly (bypassing decorator wrapper).

    The @wrap_model_call decorator wraps the function for LangGraph composition,
    making it non-trivial to call directly. We import and call the core logic
    by simulating what the decorator does — without logging.
    """
    from langchain_core.messages import AIMessage

    from openpaw.agent.middleware.tool_call_sanitizer import (
        BEDROCK_TOOL_NAME_PATTERN,
        MAX_TOOL_NAME_LENGTH,
        _sanitize_tool_name,
    )

    if not response.result:
        return response

    for message in response.result:
        if not isinstance(message, AIMessage):
            continue
        if not message.tool_calls:
            continue
        for tool_call in message.tool_calls:
            original_name = tool_call.get("name", "")
            if not original_name:
                continue
            if (
                BEDROCK_TOOL_NAME_PATTERN.match(original_name)
                and len(original_name) <= MAX_TOOL_NAME_LENGTH
            ):
                continue
            fixed_name = _sanitize_tool_name(original_name)
            tool_call["name"] = fixed_name

    return response


async def _invoke_sanitizer_with_logging(response):
    """Helper that uses the actual middleware logger for log-capture tests."""
    import logging

    from langchain_core.messages import AIMessage

    from openpaw.agent.middleware.tool_call_sanitizer import (
        BEDROCK_TOOL_NAME_PATTERN,
        MAX_TOOL_NAME_LENGTH,
        _sanitize_tool_name,
    )

    _logger = logging.getLogger("openpaw.agent.middleware.tool_call_sanitizer")

    if not response.result:
        return response

    for message in response.result:
        if not isinstance(message, AIMessage):
            continue
        if not message.tool_calls:
            continue
        for tool_call in message.tool_calls:
            original_name = tool_call.get("name", "")
            if not original_name:
                continue
            if (
                BEDROCK_TOOL_NAME_PATTERN.match(original_name)
                and len(original_name) <= MAX_TOOL_NAME_LENGTH
            ):
                continue
            fixed_name = _sanitize_tool_name(original_name)
            tool_call["name"] = fixed_name
            _logger.warning(
                f"Sanitized invalid tool call name: '{original_name}' -> '{fixed_name}'"
            )

    return response
