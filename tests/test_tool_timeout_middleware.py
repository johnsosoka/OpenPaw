"""Tests for per-tool-call timeout middleware."""

import asyncio

import pytest
from langchain_core.messages import ToolMessage

from openpaw.agent.middleware.tool_timeout import ToolTimeoutMiddleware
from openpaw.core.config.models import ToolTimeoutsConfig


class FakeRequest:
    """Mock request object for tool calls."""

    def __init__(self, name: str, tool_call_id: str):
        self.tool_call = {
            "name": name,
            "args": {},
            "id": tool_call_id,
        }


async def fast_handler(request: FakeRequest) -> str:
    """Handler that completes quickly."""
    await asyncio.sleep(0.01)  # 10ms
    return f"Result from {request.tool_call['name']}"


async def slow_handler(request: FakeRequest) -> str:
    """Handler that takes too long."""
    await asyncio.sleep(5.0)  # 5 seconds
    return f"Result from {request.tool_call['name']}"


@pytest.mark.asyncio
async def test_timeout_fires():
    """Test that slow tool gets killed and returns timeout ToolMessage."""
    config = ToolTimeoutsConfig(default_seconds=1)
    middleware = ToolTimeoutMiddleware(config)

    request = FakeRequest(name="slow_tool", tool_call_id="test-123")
    result = await middleware._execute_with_timeout(request, slow_handler)

    # Should get a ToolMessage with timeout content
    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "test-123"
    assert "timed out after 1s" in result.content
    assert "slow_tool" in result.content


@pytest.mark.asyncio
async def test_fast_tool_passes():
    """Test that tool under timeout executes normally."""
    config = ToolTimeoutsConfig(default_seconds=5)
    middleware = ToolTimeoutMiddleware(config)

    request = FakeRequest(name="fast_tool", tool_call_id="test-456")
    result = await middleware._execute_with_timeout(request, fast_handler)

    # Should get normal result, not a ToolMessage
    assert isinstance(result, str)
    assert result == "Result from fast_tool"


@pytest.mark.asyncio
async def test_config_override():
    """Test that tool-specific override is used instead of default."""
    config = ToolTimeoutsConfig(
        default_seconds=10,
        overrides={"browser_navigate": 2, "shell": 60},
    )
    middleware = ToolTimeoutMiddleware(config)

    # browser_navigate should use 2s timeout (will timeout)
    request1 = FakeRequest(name="browser_navigate", tool_call_id="test-nav")
    result1 = await middleware._execute_with_timeout(request1, slow_handler)
    assert isinstance(result1, ToolMessage)
    assert "timed out after 2s" in result1.content

    # read_file (no override) should use 10s default (won't timeout)
    request2 = FakeRequest(name="read_file", tool_call_id="test-read")
    result2 = await middleware._execute_with_timeout(request2, fast_handler)
    assert isinstance(result2, str)
    assert result2 == "Result from read_file"


@pytest.mark.asyncio
async def test_tool_message_format():
    """Test that returned ToolMessage has correct structure."""
    config = ToolTimeoutsConfig(default_seconds=1)
    middleware = ToolTimeoutMiddleware(config)

    request = FakeRequest(name="my_tool", tool_call_id="call-xyz-789")
    result = await middleware._execute_with_timeout(request, slow_handler)

    # Verify ToolMessage structure
    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "call-xyz-789"
    assert "my_tool" in result.content
    assert "1s" in result.content
    assert "Try a different approach" in result.content


@pytest.mark.asyncio
async def test_default_config():
    """Test middleware works with default config (no overrides)."""
    config = ToolTimeoutsConfig()  # Uses defaults (120s)
    middleware = ToolTimeoutMiddleware(config)

    # Fast tool should pass
    request = FakeRequest(name="any_tool", tool_call_id="test-default")
    result = await middleware._execute_with_timeout(request, fast_handler)
    assert isinstance(result, str)
    assert result == "Result from any_tool"


@pytest.mark.asyncio
async def test_agent_continues_after_timeout():
    """Test that timed-out tool returns gracefully, doesn't crash middleware."""
    config = ToolTimeoutsConfig(default_seconds=1)
    middleware = ToolTimeoutMiddleware(config)

    # First call times out
    request1 = FakeRequest(name="tool1", tool_call_id="call-1")
    result1 = await middleware._execute_with_timeout(request1, slow_handler)
    assert isinstance(result1, ToolMessage)

    # Second call should still work (middleware not broken)
    request2 = FakeRequest(name="tool2", tool_call_id="call-2")
    result2 = await middleware._execute_with_timeout(request2, fast_handler)
    assert isinstance(result2, str)
    assert result2 == "Result from tool2"


@pytest.mark.asyncio
async def test_unknown_tool_name():
    """Test handling of missing/unknown tool names in request."""
    config = ToolTimeoutsConfig(default_seconds=1)
    middleware = ToolTimeoutMiddleware(config)

    # Request with no name key (edge case)
    class BadRequest:
        def __init__(self):
            self.tool_call = {"args": {}, "id": "bad-id"}

    request = BadRequest()
    result = await middleware._execute_with_timeout(request, slow_handler)

    # Should still work, use "unknown" as name
    assert isinstance(result, ToolMessage)
    assert result.tool_call_id == "bad-id"
    assert "timed out" in result.content


@pytest.mark.asyncio
async def test_multiple_overrides():
    """Test that multiple tool overrides are all respected."""
    config = ToolTimeoutsConfig(
        default_seconds=10,
        overrides={
            "tool_a": 1,
            "tool_b": 2,
            "tool_c": 3,
        },
    )
    middleware = ToolTimeoutMiddleware(config)

    # Verify each override is used
    assert middleware._get_timeout("tool_a") == 1
    assert middleware._get_timeout("tool_b") == 2
    assert middleware._get_timeout("tool_c") == 3
    assert middleware._get_timeout("tool_d") == 10  # Falls back to default
