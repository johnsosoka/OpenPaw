#!/usr/bin/env python3
"""LangGraph mechanism validation spike for approval gates sprint.

Tests 6 critical mechanisms:
1. interrupt() inside post_model_hook
2. astream(stream_mode="updates") behavioral parity with ainvoke()
3. ToolNode(awrap_tool_call=...) with async tools
4. create_react_agent(version="v2")
5. Multi-mode streaming (updates + custom)
6. interrupt() + checkpointer interaction

Run with: poetry run python scripts/langgraph_spike.py
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool


# Color output for terminal
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"


def print_pass(message: str) -> None:
    """Print a passing test message."""
    print(f"{Colors.GREEN}✓ PASS:{Colors.RESET} {message}")


def print_fail(message: str, error: Exception | None = None) -> None:
    """Print a failing test message."""
    print(f"{Colors.RED}✗ FAIL:{Colors.RESET} {message}")
    if error:
        print(f"  {Colors.RED}Error: {error}{Colors.RESET}")


def print_warn(message: str) -> None:
    """Print a warning message."""
    print(f"{Colors.YELLOW}⚠ WARN:{Colors.RESET} {message}")


def print_info(message: str) -> None:
    """Print an informational message."""
    print(f"{Colors.BLUE}ℹ INFO:{Colors.RESET} {message}")


def print_section(title: str) -> None:
    """Print a test section header."""
    print(f"\n{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BLUE}TEST: {title}{Colors.RESET}")
    print(f"{Colors.BLUE}{'='*60}{Colors.RESET}\n")


# ============================================================================
# Test 1: interrupt() inside post_model_hook
# ============================================================================


async def test_interrupt_in_hook() -> None:
    """Test interrupt() inside post_model_hook for approval gates."""
    print_section("interrupt() inside post_model_hook")

    try:
        # Import interrupt and Command
        from langgraph.types import Command, interrupt
        from langgraph.prebuilt import create_react_agent
        from langgraph.checkpoint.memory import MemorySaver

        print_info("Imports successful: interrupt, Command")

        # Create a test tool that triggers approval
        def dangerous_tool(action: str) -> str:
            """A tool that requires approval before execution.

            Args:
                action: The dangerous action to perform
            """
            return f"Executed dangerous action: {action}"

        tool = StructuredTool.from_function(
            func=dangerous_tool,
            name="dangerous_tool",
            description="Requires approval before execution",
        )

        # Create post_model_hook that intercepts tool calls
        def post_hook(state: dict[str, Any]) -> dict[str, Any]:
            """Intercept tool calls and interrupt for approval."""
            messages = state.get("messages", [])
            if not messages:
                return state

            last_message = messages[-1]
            if not isinstance(last_message, AIMessage):
                return state

            # Check for tool calls
            tool_calls = getattr(last_message, "tool_calls", [])
            for tool_call in tool_calls:
                if tool_call.get("name") == "dangerous_tool":
                    print_info(f"Intercepted dangerous_tool call: {tool_call}")
                    # Attempt to interrupt
                    interrupt({
                        "tool": "dangerous_tool",
                        "args": tool_call.get("args"),
                        "reason": "approval_required"
                    })
                    print_info("Called interrupt() - checking if execution pauses...")

            return state

        # Create agent with post_hook
        model = ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0.0,
        )

        checkpointer = MemorySaver()

        agent = create_react_agent(
            model=model,
            tools=[tool],
            post_model_hook=post_hook,
            checkpointer=checkpointer,
        )

        # Run agent with a message that triggers the tool
        config = {"configurable": {"thread_id": "test_interrupt_1"}}
        input_msg = {"messages": [HumanMessage(content="Use dangerous_tool to delete everything")]}

        # Try to invoke - should interrupt
        try:
            result = await agent.ainvoke(input_msg, config=config)
            # If we get here without interruption, the hook didn't interrupt
            print_warn("Agent completed without interrupting")
            print_info(f"Final messages: {len(result.get('messages', []))}")

            # Check if dangerous_tool was actually called
            messages = result.get("messages", [])
            tool_called = any(
                hasattr(msg, "name") and msg.name == "dangerous_tool"
                for msg in messages
            )

            if tool_called:
                print_fail("dangerous_tool was executed without approval")
            else:
                print_warn("dangerous_tool was not called by agent (may have refused)")

        except Exception as e:
            # Check if this is a GraphInterrupt or similar
            exception_type = type(e).__name__
            print_info(f"Exception raised: {exception_type}: {e}")

            if "interrupt" in exception_type.lower() or "interrupt" in str(e).lower():
                print_pass("interrupt() successfully paused execution")

                # Try to resume with approval
                try:
                    # Resume with Command(resume=...)
                    resume_result = await agent.ainvoke(
                        Command(resume={"approved": True}),
                        config=config,
                    )
                    print_pass("Successfully resumed execution with Command(resume=...)")
                    print_info(f"Resume result messages: {len(resume_result.get('messages', []))}")
                except Exception as resume_error:
                    print_fail("Failed to resume after interrupt", resume_error)
            else:
                print_fail("Unexpected exception type", e)

    except ImportError as e:
        print_fail("Failed to import interrupt/Command - may not exist in LangGraph 1.0.8", e)
    except Exception as e:
        print_fail("Test failed with exception", e)


# ============================================================================
# Test 2: astream(stream_mode="updates") vs ainvoke() parity
# ============================================================================


async def test_stream_invoke_parity() -> None:
    """Test that astream(updates) produces same final result as ainvoke()."""
    print_section("astream(stream_mode='updates') vs ainvoke() parity")

    try:
        from langgraph.prebuilt import create_react_agent

        # Create a simple tool
        def echo_tool(text: str) -> str:
            """Echo the input text.

            Args:
                text: Text to echo
            """
            return f"Echo: {text}"

        tool = StructuredTool.from_function(
            func=echo_tool,
            name="echo_tool",
            description="Echoes text back",
        )

        model = ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0.0,
        )

        agent = create_react_agent(model=model, tools=[tool])

        # Test input
        input_msg = {"messages": [HumanMessage(content="Use echo_tool to repeat 'hello world'")]}

        # Test 1: ainvoke
        print_info("Running ainvoke()...")
        invoke_result = await agent.ainvoke(input_msg)
        invoke_messages = invoke_result.get("messages", [])
        invoke_response = invoke_messages[-1].content if invoke_messages else ""
        print_info(f"ainvoke response: {invoke_response[:100]}")

        # Test 2: astream with updates
        print_info("Running astream(stream_mode='updates')...")
        stream_messages = []
        async for update in agent.astream(input_msg, stream_mode="updates"):
            # Collect all updates
            if "messages" in update.get("agent", {}):
                stream_messages.extend(update["agent"]["messages"])

        stream_response = stream_messages[-1].content if stream_messages else ""
        print_info(f"astream response: {stream_response[:100]}")

        # Compare responses
        if invoke_response == stream_response:
            print_pass("ainvoke() and astream() produce identical responses")
        else:
            print_warn("Responses differ (may be acceptable if semantically equivalent)")
            print_info(f"Invoke: {invoke_response[:200]}")
            print_info(f"Stream: {stream_response[:200]}")

        # Show how to extract final message from stream
        print_info("Pattern for extracting final message from stream:")
        print_info("  final_message = stream_messages[-1] if stream_messages else None")
        print_pass("Stream extraction pattern validated")

    except Exception as e:
        print_fail("Test failed with exception", e)


# ============================================================================
# Test 3: ToolNode(awrap_tool_call=...) with async tools
# ============================================================================


async def test_tool_node_wrapper() -> None:
    """Test ToolNode with custom awrap_tool_call wrapper."""
    print_section("ToolNode(awrap_tool_call=...) with async tools")

    try:
        from langgraph.prebuilt import ToolNode

        # Create sync and async versions of a tool
        def sync_calculator(operation: str, a: int, b: int) -> int:
            """Perform calculation.

            Args:
                operation: Operation to perform (add, multiply)
                a: First number
                b: Second number
            """
            if operation == "add":
                return a + b
            elif operation == "multiply":
                return a * b
            return 0

        async def async_calculator(operation: str, a: int, b: int) -> int:
            """Async version of calculator."""
            await asyncio.sleep(0.01)  # Simulate async work
            if operation == "add":
                return a + b
            elif operation == "multiply":
                return a * b
            return 0

        tool = StructuredTool.from_function(
            func=sync_calculator,
            coroutine=async_calculator,
            name="calculator",
            description="Performs calculations",
        )

        # Create wrapper function
        wrapper_calls = []

        async def tool_wrapper(tool_call: dict[str, Any], tool_instance: Any) -> Any:
            """Custom wrapper that logs and modifies tool calls."""
            wrapper_calls.append({
                "tool_name": tool_call.get("name"),
                "args": tool_call.get("args"),
            })
            print_info(f"Wrapper intercepted: {tool_call.get('name')} with {tool_call.get('args')}")

            # Could skip execution here:
            # return {"result": "skipped", "approved": False}

            # Or delegate to actual tool
            result = await tool_instance.ainvoke(tool_call.get("args", {}))
            return result

        # Create ToolNode with wrapper
        try:
            tool_node = ToolNode(tools=[tool], awrap_tool_call=tool_wrapper)
            print_pass("ToolNode created with awrap_tool_call")

            # Simulate a tool call invocation
            test_tool_call = {
                "name": "calculator",
                "args": {"operation": "add", "a": 5, "b": 3},
                "id": "test_call_1",
            }

            # Create state with tool call
            state = {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[test_tool_call],
                    )
                ]
            }

            # Invoke the tool node
            result = await tool_node.ainvoke(state)
            print_info(f"ToolNode result: {result}")

            if wrapper_calls:
                print_pass("awrap_tool_call was invoked successfully")
                print_info(f"Wrapper received: {wrapper_calls[0]}")
            else:
                print_fail("awrap_tool_call was not invoked")

        except TypeError as e:
            if "awrap_tool_call" in str(e):
                print_fail("awrap_tool_call parameter not supported in this LangGraph version", e)
            else:
                raise

    except Exception as e:
        print_fail("Test failed with exception", e)


# ============================================================================
# Test 4: create_react_agent(version="v2")
# ============================================================================


async def test_agent_version_v2() -> None:
    """Test create_react_agent with version='v2' for per-tool nodes."""
    print_section("create_react_agent(version='v2')")

    try:
        from langgraph.prebuilt import create_react_agent

        def tool_a(text: str) -> str:
            """Tool A.

            Args:
                text: Input text
            """
            return f"A: {text}"

        def tool_b(text: str) -> str:
            """Tool B.

            Args:
                text: Input text
            """
            return f"B: {text}"

        tools = [
            StructuredTool.from_function(func=tool_a, name="tool_a"),
            StructuredTool.from_function(func=tool_b, name="tool_b"),
        ]

        model = ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0.0,
        )

        # Try to create v2 agent
        try:
            agent_v2 = create_react_agent(
                model=model,
                tools=tools,
                version="v2",
            )
            print_pass("create_react_agent(version='v2') succeeded")

            # Inspect graph structure
            print_info("Checking graph structure for per-tool nodes...")

            # Get node names from graph
            if hasattr(agent_v2, "nodes"):
                node_names = list(agent_v2.nodes.keys())
                print_info(f"Graph nodes: {node_names}")

                # v2 should have separate nodes for each tool
                if "tool_a" in node_names or "tool_b" in node_names:
                    print_pass("v2 creates separate nodes per tool")
                else:
                    print_warn("Could not confirm separate tool nodes in graph structure")
            else:
                print_warn("Cannot inspect graph structure (nodes not accessible)")

            # Test with post_model_hook to see if tool calls are still visible
            hook_calls = []

            def post_hook_v2(state: dict[str, Any]) -> dict[str, Any]:
                messages = state.get("messages", [])
                if messages:
                    last = messages[-1]
                    if isinstance(last, AIMessage):
                        tool_calls = getattr(last, "tool_calls", [])
                        if tool_calls:
                            hook_calls.append(tool_calls)
                            print_info(f"post_hook saw {len(tool_calls)} tool calls")
                return state

            agent_v2_with_hook = create_react_agent(
                model=model,
                tools=tools,
                version="v2",
                post_model_hook=post_hook_v2,
            )

            # Run a simple test
            result = await agent_v2_with_hook.ainvoke({
                "messages": [HumanMessage(content="Use tool_a to process 'test'")]
            })

            if hook_calls:
                print_pass("post_model_hook still sees tool calls in v2")
            else:
                print_warn("post_model_hook did not see tool calls (may affect approval gates)")

        except TypeError as e:
            if "version" in str(e):
                print_fail("version parameter not supported in this LangGraph version", e)
            else:
                raise

    except Exception as e:
        print_fail("Test failed with exception", e)


# ============================================================================
# Test 5: Multi-mode streaming
# ============================================================================


async def test_multi_mode_streaming() -> None:
    """Test astream with multiple stream modes simultaneously."""
    print_section("Multi-mode streaming (updates + custom)")

    try:
        from langgraph.prebuilt import create_react_agent

        def simple_tool(text: str) -> str:
            """Simple tool.

            Args:
                text: Input text
            """
            return f"Processed: {text}"

        tool = StructuredTool.from_function(func=simple_tool, name="simple_tool")

        model = ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0.0,
        )

        agent = create_react_agent(model=model, tools=[tool])

        # Test multi-mode streaming
        print_info("Testing astream(stream_mode=['updates', 'custom'])...")

        updates_seen = False
        custom_seen = False

        try:
            async for event in agent.astream(
                {"messages": [HumanMessage(content="Use simple_tool on 'hello'")]},
                stream_mode=["updates", "custom"],
            ):
                # Event should be tuple of (mode, data)
                print_info(f"Received event type: {type(event)}, content: {str(event)[:100]}")

                if isinstance(event, tuple) and len(event) == 2:
                    mode, data = event
                    if mode == "updates":
                        updates_seen = True
                    elif mode == "custom":
                        custom_seen = True
                elif isinstance(event, dict):
                    # Single mode events are returned as dict
                    updates_seen = True

            if updates_seen:
                print_pass("Received 'updates' events")
            if custom_seen:
                print_pass("Received 'custom' events")

            if not updates_seen:
                print_warn("No 'updates' events received")

        except TypeError as e:
            if "stream_mode" in str(e):
                print_fail("Multi-mode streaming not supported", e)
            else:
                raise

    except Exception as e:
        print_fail("Test failed with exception", e)


# ============================================================================
# Test 6: interrupt() + checkpointer interaction
# ============================================================================


async def test_interrupt_with_checkpointer() -> None:
    """Test interrupt() with MemorySaver checkpointer for state preservation."""
    print_section("interrupt() + checkpointer interaction")

    try:
        from langgraph.types import Command, interrupt
        from langgraph.prebuilt import create_react_agent
        from langgraph.checkpoint.memory import MemorySaver

        # Create approval tool
        def approval_required_tool(action: str) -> str:
            """Tool requiring approval.

            Args:
                action: Action to perform
            """
            return f"Approved action: {action}"

        tool = StructuredTool.from_function(
            func=approval_required_tool,
            name="approval_tool",
        )

        # Hook to interrupt
        interrupt_count = [0]

        def hook_with_interrupt(state: dict[str, Any]) -> dict[str, Any]:
            messages = state.get("messages", [])
            if messages:
                last = messages[-1]
                if isinstance(last, AIMessage):
                    tool_calls = getattr(last, "tool_calls", [])
                    for tc in tool_calls:
                        if tc.get("name") == "approval_tool":
                            interrupt_count[0] += 1
                            print_info(f"Interrupting for approval (count: {interrupt_count[0]})")
                            interrupt({"action": tc.get("args"), "approved": False})
            return state

        model = ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0.0,
        )

        checkpointer = MemorySaver()

        agent = create_react_agent(
            model=model,
            tools=[tool],
            post_model_hook=hook_with_interrupt,
            checkpointer=checkpointer,
        )

        config = {"configurable": {"thread_id": "interrupt_checkpoint_test"}}

        # First call - should interrupt
        try:
            result1 = await agent.ainvoke(
                {"messages": [HumanMessage(content="Use approval_tool to delete files")]},
                config=config,
            )
            print_warn("Agent did not interrupt (returned normally)")

        except Exception as e:
            exception_name = type(e).__name__
            if "interrupt" in exception_name.lower() or "interrupt" in str(e).lower():
                print_pass("Agent interrupted successfully")

                # Check if state is preserved in checkpointer
                try:
                    # Get state from checkpointer
                    state_snapshot = await agent.aget_state(config)
                    print_info(f"State preserved: {bool(state_snapshot)}")

                    if state_snapshot:
                        print_pass("Checkpointer preserved state after interrupt")

                        # Try to resume
                        try:
                            resume_result = await agent.ainvoke(
                                Command(resume={"approved": True}),
                                config=config,
                            )
                            print_pass("Successfully resumed from checkpoint")
                            print_info(f"Final messages: {len(resume_result.get('messages', []))}")

                        except Exception as resume_err:
                            print_fail("Failed to resume from checkpoint", resume_err)
                    else:
                        print_fail("Checkpointer did not preserve state")

                except AttributeError:
                    print_warn("aget_state not available on agent (cannot verify state preservation)")
                except Exception as state_err:
                    print_fail("Failed to get state from checkpointer", state_err)
            else:
                print_fail("Unexpected exception type", e)

    except ImportError as e:
        print_fail("Failed to import interrupt/Command/MemorySaver", e)
    except Exception as e:
        print_fail("Test failed with exception", e)


# ============================================================================
# Main runner
# ============================================================================


async def main() -> None:
    """Run all spike tests."""
    print(f"\n{Colors.BLUE}{'='*60}")
    print("LangGraph Mechanism Validation Spike")
    print(f"LangGraph version: 1.0.8 (from poetry env)")
    print(f"{'='*60}{Colors.RESET}\n")

    # Load API key from config.yaml if not in environment
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        config_path = Path(__file__).parent.parent / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                api_key = config.get("agent", {}).get("api_key")
                if api_key:
                    os.environ["ANTHROPIC_API_KEY"] = api_key
                    print_info("Loaded ANTHROPIC_API_KEY from config.yaml")

    if not os.getenv("ANTHROPIC_API_KEY"):
        print_fail("ANTHROPIC_API_KEY not set in environment or config.yaml")
        print_info("Set it with: export ANTHROPIC_API_KEY='your-key'")
        sys.exit(1)

    # Run all tests
    await test_interrupt_in_hook()
    await test_stream_invoke_parity()
    await test_tool_node_wrapper()
    await test_agent_version_v2()
    await test_multi_mode_streaming()
    await test_interrupt_with_checkpointer()

    print(f"\n{Colors.BLUE}{'='*60}")
    print("Spike tests complete")
    print(f"{'='*60}{Colors.RESET}\n")

    print_info("Next steps:")
    print_info("1. Review test output above")
    print_info("2. Document findings in llm_memory/langgraph-spike-results.md")
    print_info("3. Update sprint plan based on mechanism availability")


if __name__ == "__main__":
    asyncio.run(main())
