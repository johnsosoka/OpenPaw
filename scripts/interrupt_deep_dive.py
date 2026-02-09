#!/usr/bin/env python3
"""Deep dive into interrupt() mechanism.

This script tests interrupt() in different contexts to understand where it works.
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
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode, create_react_agent
from langgraph.types import Command, interrupt


def load_api_key():
    """Load API key from config.yaml."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        config_path = Path(__file__).parent.parent / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                api_key = config.get("agent", {}).get("api_key")
                if api_key:
                    os.environ["ANTHROPIC_API_KEY"] = api_key
    return os.getenv("ANTHROPIC_API_KEY")


async def test_interrupt_in_custom_node():
    """Test if interrupt() works in a custom graph node."""
    print("\n=== Test: interrupt() in custom graph node ===")

    from typing import Annotated, TypedDict
    from langgraph.graph.message import add_messages

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    def approval_node(state: State) -> dict:
        """Custom node that always interrupts."""
        print("→ approval_node called")
        interrupt({"reason": "approval_required"})
        print("→ This should not print if interrupt works")
        return state

    def continue_node(state: State) -> dict:
        """Node after approval."""
        print("→ continue_node called after approval")
        return state

    # Build graph
    graph = StateGraph(State)
    graph.add_node("approval", approval_node)
    graph.add_node("continue", continue_node)
    graph.set_entry_point("approval")
    graph.add_edge("approval", "continue")
    graph.set_finish_point("continue")

    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test1"}}

    try:
        result = await app.ainvoke(
            {"messages": [HumanMessage(content="test")]},
            config=config
        )
        print("✗ FAIL: Graph completed without interrupting")
        return False
    except Exception as e:
        if "interrupt" in str(type(e).__name__).lower():
            print(f"✓ PASS: Graph interrupted with {type(e).__name__}")

            # Try to resume
            try:
                resume_result = await app.ainvoke(
                    Command(resume={"approved": True}),
                    config=config
                )
                print("✓ PASS: Successfully resumed")
                return True
            except Exception as resume_err:
                print(f"✗ FAIL: Resume failed: {resume_err}")
                return False
        else:
            print(f"✗ FAIL: Unexpected error: {e}")
            return False


async def test_interrupt_in_tool_node():
    """Test if interrupt() works inside a tool function."""
    print("\n=== Test: interrupt() inside tool function ===")

    def blocking_tool(action: str) -> str:
        """Tool that calls interrupt()."""
        print(f"→ blocking_tool called with: {action}")
        interrupt({"action": action, "reason": "approval_required"})
        print("→ This should not print if interrupt works")
        return f"Executed: {action}"

    tool = StructuredTool.from_function(func=blocking_tool, name="blocking_tool")

    model = ChatAnthropic(
        model="claude-haiku-4-5-20251001",
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.0,
    )

    checkpointer = MemorySaver()
    agent = create_react_agent(model=model, tools=[tool], checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test2"}}

    try:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="Use blocking_tool to delete files")]},
            config=config
        )
        print("✗ FAIL: Agent completed without interrupting")
        return False
    except Exception as e:
        if "interrupt" in str(type(e).__name__).lower():
            print(f"✓ PASS: Tool interrupted with {type(e).__name__}")
            return True
        else:
            print(f"✗ FAIL: Unexpected error: {e}")
            return False


async def test_interrupt_with_custom_wrapper():
    """Test interrupt() with a custom tool wrapper node."""
    print("\n=== Test: interrupt() with custom tool wrapper ===")

    from typing import Annotated, TypedDict
    from langgraph.graph.message import add_messages

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    def simple_tool(text: str) -> str:
        """Simple tool."""
        return f"Processed: {text}"

    tool = StructuredTool.from_function(func=simple_tool, name="simple_tool")

    def approval_wrapper(state: State) -> dict:
        """Custom node that wraps tool execution with approval."""
        messages = state.get("messages", [])
        if not messages:
            return state

        last_msg = messages[-1]
        if isinstance(last_msg, AIMessage):
            tool_calls = getattr(last_msg, "tool_calls", [])
            if tool_calls:
                print(f"→ approval_wrapper intercepted {len(tool_calls)} tool calls")
                interrupt({"tool_calls": tool_calls})
                print("→ This should not print")

        # If we get here, execute tools normally
        tool_node = ToolNode(tools=[tool])
        return tool_node.invoke(state)

    # Build custom graph with model + approval wrapper
    model = ChatAnthropic(
        model="claude-haiku-4-5-20251001",
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.0,
    )

    from langgraph.graph import END, StateGraph

    def call_model(state: State) -> dict:
        """Call the model."""
        bound_model = model.bind_tools([tool])
        response = bound_model.invoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: State) -> str:
        """Route to tools or end."""
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(State)
    graph.add_node("agent", call_model)
    graph.add_node("tools", approval_wrapper)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test3"}}

    try:
        result = await app.ainvoke(
            {"messages": [HumanMessage(content="Use simple_tool on 'test'")]},
            config=config
        )
        print("✗ FAIL: Agent completed without interrupting")
        return False
    except Exception as e:
        if "interrupt" in str(type(e).__name__).lower():
            print(f"✓ PASS: Custom wrapper interrupted with {type(e).__name__}")

            # Try to resume
            try:
                resume_result = await app.ainvoke(
                    Command(resume={"approved": True}),
                    config=config
                )
                print("✓ PASS: Successfully resumed from interrupt")
                return True
            except Exception as resume_err:
                print(f"✗ FAIL: Resume failed: {resume_err}")
                return False
        else:
            print(f"✗ FAIL: Unexpected error: {e}")
            return False


async def main():
    """Run all deep dive tests."""
    print("="*60)
    print("interrupt() Deep Dive")
    print("="*60)

    if not load_api_key():
        print("ERROR: ANTHROPIC_API_KEY not found")
        sys.exit(1)

    # Test 1: Custom node
    result1 = await test_interrupt_in_custom_node()

    # Test 2: Inside tool
    result2 = await test_interrupt_in_tool_node()

    # Test 3: Custom wrapper
    result3 = await test_interrupt_with_custom_wrapper()

    print("\n" + "="*60)
    print("Summary:")
    print(f"  Custom node interrupt: {'✓ PASS' if result1 else '✗ FAIL'}")
    print(f"  Tool function interrupt: {'✓ PASS' if result2 else '✗ FAIL'}")
    print(f"  Custom wrapper interrupt: {'✓ PASS' if result3 else '✗ FAIL'}")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
