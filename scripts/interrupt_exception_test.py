#!/usr/bin/env python3
"""Test if GraphInterrupt is raised but caught internally."""

import asyncio
import os
from pathlib import Path
from typing import Annotated, Any, TypedDict

import yaml
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage
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


class State(TypedDict):
    messages: Annotated[list, add_messages]


def interrupt_node(state: State) -> dict:
    """Node that calls interrupt()."""
    print("→ interrupt_node: Before interrupt()")
    try:
        result = interrupt({"reason": "approval_required"})
        print(f"→ interrupt_node: After interrupt(), got result: {result}")
    except GraphInterrupt as e:
        print(f"→ interrupt_node: Caught GraphInterrupt: {e}")
        raise
    except Exception as e:
        print(f"→ interrupt_node: Caught other exception: {type(e).__name__}: {e}")
        raise
    return state


async def test_raw_interrupt():
    """Test interrupt with explicit exception handling."""
    print("="*60)
    print("Testing interrupt() with explicit exception handling")
    print("="*60)

    graph = StateGraph(State)
    graph.add_node("interrupt", interrupt_node)
    graph.set_entry_point("interrupt")
    graph.set_finish_point("interrupt")

    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": "test1"}}

    print("\n→ Invoking graph (should interrupt)...")
    try:
        result = await app.ainvoke(
            {"messages": [HumanMessage(content="test")]},
            config=config
        )
        print(f"✗ FAIL: Graph completed, result: {result}")
    except GraphInterrupt as e:
        print(f"✓ SUCCESS: Caught GraphInterrupt at top level: {e}")
        print(f"  Exception data: {e.value if hasattr(e, 'value') else 'no value'}")

        print("\n→ Attempting to resume with Command...")
        try:
            resume_result = await app.ainvoke(
                Command(resume={"approved": True}),
                config=config
            )
            print(f"✓ SUCCESS: Resumed, result: {resume_result}")
        except Exception as resume_err:
            print(f"✗ FAIL: Resume error: {type(resume_err).__name__}: {resume_err}")
    except Exception as e:
        print(f"✗ FAIL: Unexpected exception: {type(e).__name__}: {e}")


async def test_interrupt_with_stream():
    """Test if interrupt is surfaced via astream."""
    print("\n" + "="*60)
    print("Testing interrupt() via astream")
    print("="*60)

    graph = StateGraph(State)
    graph.add_node("interrupt", interrupt_node)
    graph.set_entry_point("interrupt")
    graph.set_finish_point("interrupt")

    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer, interrupt_before=["interrupt"])

    config = {"configurable": {"thread_id": "test2"}}

    print("\n→ Streaming graph events...")
    events_seen = []
    try:
        async for event in app.astream(
            {"messages": [HumanMessage(content="test")]},
            config=config,
            stream_mode=["values", "updates"],
        ):
            events_seen.append(event)
            print(f"  Event: {type(event)}: {str(event)[:100]}")
    except GraphInterrupt as e:
        print(f"✓ GraphInterrupt raised during stream: {e}")
    except Exception as e:
        print(f"Exception during stream: {type(e).__name__}: {e}")

    print(f"\n  Total events: {len(events_seen)}")

    # Check state
    print("\n→ Checking state after interrupt...")
    state = await app.aget_state(config)
    print(f"  State: {state}")
    print(f"  Next nodes: {state.next if hasattr(state, 'next') else 'N/A'}")


async def test_interrupt_before():
    """Test interrupt_before compile option."""
    print("\n" + "="*60)
    print("Testing interrupt_before (compile-time interrupts)")
    print("="*60)

    def normal_node(state: State) -> dict:
        print("→ normal_node executed")
        return state

    graph = StateGraph(State)
    graph.add_node("normal", normal_node)
    graph.set_entry_point("normal")
    graph.set_finish_point("normal")

    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer, interrupt_before=["normal"])

    config = {"configurable": {"thread_id": "test3"}}

    print("\n→ Invoking with interrupt_before=['normal']...")
    result = await app.ainvoke(
        {"messages": [HumanMessage(content="test")]},
        config=config
    )
    print(f"  Result: {result}")

    # Check state
    state = await app.aget_state(config)
    print(f"  State.next: {state.next if hasattr(state, 'next') else 'N/A'}")

    if hasattr(state, 'next') and state.next:
        print("✓ SUCCESS: interrupt_before worked, graph paused before node")

        print("\n→ Resuming with None input...")
        resume_result = await app.ainvoke(None, config=config)
        print(f"  Resume result: {resume_result}")
    else:
        print("✗ FAIL: interrupt_before did not pause execution")


async def main():
    if not load_api_key():
        print("ERROR: ANTHROPIC_API_KEY not found")
        return

    await test_raw_interrupt()
    await test_interrupt_with_stream()
    await test_interrupt_before()


if __name__ == "__main__":
    asyncio.run(main())
