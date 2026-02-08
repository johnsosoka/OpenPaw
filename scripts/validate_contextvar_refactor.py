#!/usr/bin/env python3
"""Validation script for SendMessageTool and FollowupTool contextvar refactoring.

This script verifies that the tools correctly isolate per-session state using
contextvars instead of instance attributes, preventing race conditions when
main_concurrency > 1.
"""

import asyncio
import contextvars
from typing import Any
from unittest.mock import AsyncMock, Mock

from openpaw.builtins.tools.followup import FollowupRequest, FollowupTool
from openpaw.builtins.tools.send_message import SendMessageTool


async def test_send_message_isolation():
    """Test that SendMessageTool isolates state per async task."""
    print("\n=== Testing SendMessageTool State Isolation ===")

    tool = SendMessageTool()

    # Create mock channels and session keys
    channel1 = AsyncMock()
    channel2 = AsyncMock()

    async def session1():
        """Simulates session 1."""
        tool.set_session_context(channel1, "session1")
        await asyncio.sleep(0.1)  # Simulate work

        # Get the tool and verify context
        langchain_tool = tool.get_langchain_tool()
        result = await langchain_tool.coroutine("Test message 1")

        assert "Message sent" in result, f"Expected success, got: {result}"
        channel1.send_message.assert_called_once_with("session1", "Test message 1")

        tool.clear_session_context()
        print("✓ Session 1 completed successfully")

    async def session2():
        """Simulates session 2."""
        await asyncio.sleep(0.05)  # Start slightly later
        tool.set_session_context(channel2, "session2")

        # Get the tool and verify context
        langchain_tool = tool.get_langchain_tool()
        result = await langchain_tool.coroutine("Test message 2")

        assert "Message sent" in result, f"Expected success, got: {result}"
        channel2.send_message.assert_called_once_with("session2", "Test message 2")

        tool.clear_session_context()
        print("✓ Session 2 completed successfully")

    # Run both sessions concurrently
    await asyncio.gather(session1(), session2())

    print("✓ SendMessageTool correctly isolates state between concurrent sessions")


async def test_followup_isolation():
    """Test that FollowupTool isolates state per async task."""
    print("\n=== Testing FollowupTool State Isolation ===")

    tool = FollowupTool()

    async def session1():
        """Simulates session 1."""
        tool.set_chain_depth(1)
        await asyncio.sleep(0.1)  # Simulate work

        # Request a followup
        langchain_tool = tool.get_langchain_tool()
        result = langchain_tool.func("Continue session 1", 0)

        assert "Followup scheduled" in result, f"Expected success, got: {result}"

        # Get pending followup
        followup = tool.get_pending_followup()
        assert followup is not None, "Expected followup to be set"
        assert followup.prompt == "Continue session 1", f"Unexpected prompt: {followup.prompt}"

        tool.reset()
        print("✓ Session 1 completed successfully")

    async def session2():
        """Simulates session 2."""
        await asyncio.sleep(0.05)  # Start slightly later
        tool.set_chain_depth(2)

        # Request a different followup
        langchain_tool = tool.get_langchain_tool()
        result = langchain_tool.func("Continue session 2", 5)

        assert "Followup scheduled" in result, f"Expected success, got: {result}"

        # Get pending followup
        followup = tool.get_pending_followup()
        assert followup is not None, "Expected followup to be set"
        assert followup.prompt == "Continue session 2", f"Unexpected prompt: {followup.prompt}"

        tool.reset()
        print("✓ Session 2 completed successfully")

    # Run both sessions concurrently
    await asyncio.gather(session1(), session2())

    print("✓ FollowupTool correctly isolates state between concurrent sessions")


async def test_contextvar_defaults():
    """Test that contextvar defaults work correctly."""
    print("\n=== Testing ContextVar Defaults ===")

    send_tool = SendMessageTool()
    followup_tool = FollowupTool()

    # Without setting context, tools should handle gracefully
    send_langchain = send_tool.get_langchain_tool()
    send_result = await send_langchain.coroutine("Test")
    assert "Error" in send_result, f"Expected error without context, got: {send_result}"
    print("✓ SendMessageTool returns error without context")

    # Followup should return None when nothing pending
    followup = followup_tool.get_pending_followup()
    assert followup is None, f"Expected None, got: {followup}"
    print("✓ FollowupTool returns None when nothing pending")


async def main():
    """Run all validation tests."""
    print("=" * 60)
    print("Validating SendMessageTool and FollowupTool Refactoring")
    print("=" * 60)

    try:
        await test_contextvar_defaults()
        await test_send_message_isolation()
        await test_followup_isolation()

        print("\n" + "=" * 60)
        print("✓ All validation tests passed!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n✗ Validation failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
