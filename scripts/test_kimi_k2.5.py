#!/usr/bin/env python3
"""
Systematic test script for Kimi K2.5 (Moonshot AI) integration.

Tests the API at multiple levels:
1. Direct OpenAI client (bypass LangChain)
2. LangChain ChatOpenAI
3. LangGraph create_react_agent

Goal: Find a working configuration for multi-turn conversations with tool calls.
"""

import asyncio
import json
import os
import sys
from typing import Any, Dict, List

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from openai import OpenAI

# Load environment from Krieger's workspace
ENV_PATH = "/Users/john/code/projects/OpenPaw/agent_workspaces/krieger/.env"
load_dotenv(ENV_PATH)

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY")
if not MOONSHOT_API_KEY:
    print(f"ERROR: MOONSHOT_API_KEY not found in {ENV_PATH}")
    sys.exit(1)

MOONSHOT_BASE_URL = "https://api.moonshot.ai/v1"
MODEL = "kimi-k2.5"

# Simple test tool
@tool
def get_weather(location: str) -> str:
    """Get the weather for a location."""
    return f"The weather in {location} is sunny, 72°F."


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80 + "\n")


def print_result(test_name: str, success: bool, details: str = ""):
    """Print a test result."""
    status = "✓ PASS" if success else "✗ FAIL"
    print(f"{status} | {test_name}")
    if details:
        print(f"      {details}")
    print()


# =============================================================================
# Test 1: Direct OpenAI Client Tests
# =============================================================================

def test_direct_openai_thinking_enabled():
    """Test with thinking enabled (temperature=1.0, no extra_body)."""
    print_section("Test 1a: Direct OpenAI - Thinking Enabled (Single Turn)")

    client = OpenAI(api_key=MOONSHOT_API_KEY, base_url=MOONSHOT_BASE_URL)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "user", "content": "What is 2+2?"}
            ],
            temperature=1.0
        )

        print(f"Response: {response.choices[0].message.content}")
        print(f"Full response: {json.dumps(response.model_dump(), indent=2)}")

        print_result("Direct OpenAI - Thinking Enabled (Single Turn)", True,
                     f"Response received: {response.choices[0].message.content[:50]}...")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        print_result("Direct OpenAI - Thinking Enabled (Single Turn)", False, str(e))
        return False


def test_direct_openai_thinking_disabled():
    """Test with thinking disabled (temperature=0.6, extra_body)."""
    print_section("Test 1b: Direct OpenAI - Thinking Disabled (Single Turn)")

    client = OpenAI(api_key=MOONSHOT_API_KEY, base_url=MOONSHOT_BASE_URL)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "user", "content": "What is 2+2?"}
            ],
            temperature=0.6,
            extra_body={"thinking": {"type": "disabled"}}
        )

        print(f"Response: {response.choices[0].message.content}")
        print(f"Full response: {json.dumps(response.model_dump(), indent=2)}")

        print_result("Direct OpenAI - Thinking Disabled (Single Turn)", True,
                     f"Response received: {response.choices[0].message.content[:50]}...")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        print_result("Direct OpenAI - Thinking Disabled (Single Turn)", False, str(e))
        return False


def test_direct_openai_tool_call_thinking_enabled():
    """Test multi-turn with tool calls - thinking enabled."""
    print_section("Test 1c: Direct OpenAI - Tool Call with Thinking Enabled")

    client = OpenAI(api_key=MOONSHOT_API_KEY, base_url=MOONSHOT_BASE_URL)

    # Define a simple tool
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city name"
                        }
                    },
                    "required": ["location"]
                }
            }
        }
    ]

    try:
        # First turn: user asks about weather
        print("Turn 1: User asks about weather")
        messages = [
            {"role": "user", "content": "What's the weather in San Francisco?"}
        ]

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            temperature=1.0
        )

        assistant_msg = response.choices[0].message
        print(f"Assistant response: {json.dumps(assistant_msg.model_dump(), indent=2)}")

        # Check if it has tool calls
        if not assistant_msg.tool_calls:
            print_result("Direct OpenAI - Tool Call with Thinking Enabled", False,
                         "No tool call made")
            return False

        # Turn 2: Return tool result
        print("\nTurn 2: Returning tool result")
        messages.append(assistant_msg.model_dump())
        messages.append({
            "role": "tool",
            "tool_call_id": assistant_msg.tool_calls[0].id,
            "content": "The weather in San Francisco is sunny, 72°F."
        })

        print(f"Messages being sent: {json.dumps(messages, indent=2)}")

        response2 = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            temperature=1.0
        )

        print(f"\nFinal response: {response2.choices[0].message.content}")
        print(f"Full response: {json.dumps(response2.model_dump(), indent=2)}")

        print_result("Direct OpenAI - Tool Call with Thinking Enabled", True,
                     "Multi-turn tool call successful")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        print_result("Direct OpenAI - Tool Call with Thinking Enabled", False, str(e))
        return False


def test_direct_openai_tool_call_thinking_disabled():
    """Test multi-turn with tool calls - thinking disabled."""
    print_section("Test 1d: Direct OpenAI - Tool Call with Thinking Disabled")

    client = OpenAI(api_key=MOONSHOT_API_KEY, base_url=MOONSHOT_BASE_URL)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city name"
                        }
                    },
                    "required": ["location"]
                }
            }
        }
    ]

    try:
        # First turn: user asks about weather
        print("Turn 1: User asks about weather")
        messages = [
            {"role": "user", "content": "What's the weather in San Francisco?"}
        ]

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            temperature=0.6,
            extra_body={"thinking": {"type": "disabled"}}
        )

        assistant_msg = response.choices[0].message
        print(f"Assistant response: {json.dumps(assistant_msg.model_dump(), indent=2)}")

        # Check if it has tool calls
        if not assistant_msg.tool_calls:
            print_result("Direct OpenAI - Tool Call with Thinking Disabled", False,
                         "No tool call made")
            return False

        # Turn 2: Return tool result
        print("\nTurn 2: Returning tool result")
        messages.append(assistant_msg.model_dump())
        messages.append({
            "role": "tool",
            "tool_call_id": assistant_msg.tool_calls[0].id,
            "content": "The weather in San Francisco is sunny, 72°F."
        })

        print(f"Messages being sent: {json.dumps(messages, indent=2)}")

        response2 = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            temperature=0.6,
            extra_body={"thinking": {"type": "disabled"}}
        )

        print(f"\nFinal response: {response2.choices[0].message.content}")
        print(f"Full response: {json.dumps(response2.model_dump(), indent=2)}")

        print_result("Direct OpenAI - Tool Call with Thinking Disabled", True,
                     "Multi-turn tool call successful")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        print_result("Direct OpenAI - Tool Call with Thinking Disabled", False, str(e))
        return False


# =============================================================================
# Test 2: LangChain ChatOpenAI Tests
# =============================================================================

def test_langchain_chat_thinking_enabled():
    """Test LangChain ChatOpenAI with thinking enabled."""
    print_section("Test 2a: LangChain ChatOpenAI - Thinking Enabled (Single Turn)")

    try:
        llm = ChatOpenAI(
            model=MODEL,
            api_key=MOONSHOT_API_KEY,
            base_url=MOONSHOT_BASE_URL,
            temperature=1.0
        )

        messages = [HumanMessage(content="What is 2+2?")]
        response = llm.invoke(messages)

        print(f"Response: {response.content}")
        print(f"Response type: {type(response)}")
        print(f"Additional kwargs: {response.additional_kwargs}")

        print_result("LangChain ChatOpenAI - Thinking Enabled", True,
                     f"Response: {response.content[:50]}...")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        print_result("LangChain ChatOpenAI - Thinking Enabled", False, str(e))
        return False


def test_langchain_chat_thinking_disabled():
    """Test LangChain ChatOpenAI with thinking disabled."""
    print_section("Test 2b: LangChain ChatOpenAI - Thinking Disabled (Single Turn)")

    try:
        llm = ChatOpenAI(
            model=MODEL,
            api_key=MOONSHOT_API_KEY,
            base_url=MOONSHOT_BASE_URL,
            temperature=0.6,
            model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}}
        )

        messages = [HumanMessage(content="What is 2+2?")]
        response = llm.invoke(messages)

        print(f"Response: {response.content}")
        print(f"Response type: {type(response)}")
        print(f"Additional kwargs: {response.additional_kwargs}")

        print_result("LangChain ChatOpenAI - Thinking Disabled", True,
                     f"Response: {response.content[:50]}...")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        print_result("LangChain ChatOpenAI - Thinking Disabled", False, str(e))
        return False


def test_langchain_chat_tool_call_thinking_enabled():
    """Test LangChain ChatOpenAI with tool calls - thinking enabled."""
    print_section("Test 2c: LangChain ChatOpenAI - Tool Call with Thinking Enabled")

    try:
        llm = ChatOpenAI(
            model=MODEL,
            api_key=MOONSHOT_API_KEY,
            base_url=MOONSHOT_BASE_URL,
            temperature=1.0
        )

        llm_with_tools = llm.bind_tools([get_weather])

        # First turn
        print("Turn 1: User asks about weather")
        messages = [HumanMessage(content="What's the weather in San Francisco?")]
        response1 = llm_with_tools.invoke(messages)

        print(f"Response 1 type: {type(response1)}")
        print(f"Response 1 content: {response1.content}")
        print(f"Tool calls: {response1.tool_calls}")
        print(f"Additional kwargs: {response1.additional_kwargs}")

        if not response1.tool_calls:
            print_result("LangChain ChatOpenAI - Tool Call with Thinking Enabled", False,
                         "No tool call made")
            return False

        # Simulate tool execution
        tool_call = response1.tool_calls[0]
        tool_result = get_weather.invoke(tool_call["args"])

        # Second turn
        print("\nTurn 2: Returning tool result")
        messages.append(response1)
        messages.append(ToolMessage(
            content=tool_result,
            tool_call_id=tool_call["id"]
        ))

        print(f"Messages being sent (count={len(messages)}):")
        for i, msg in enumerate(messages):
            print(f"  [{i}] {type(msg).__name__}: {msg}")

        response2 = llm_with_tools.invoke(messages)

        print(f"\nFinal response: {response2.content}")
        print(f"Additional kwargs: {response2.additional_kwargs}")

        print_result("LangChain ChatOpenAI - Tool Call with Thinking Enabled", True,
                     "Multi-turn tool call successful")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        print_result("LangChain ChatOpenAI - Tool Call with Thinking Enabled", False, str(e))
        return False


def test_langchain_chat_tool_call_thinking_disabled():
    """Test LangChain ChatOpenAI with tool calls - thinking disabled."""
    print_section("Test 2d: LangChain ChatOpenAI - Tool Call with Thinking Disabled")

    try:
        llm = ChatOpenAI(
            model=MODEL,
            api_key=MOONSHOT_API_KEY,
            base_url=MOONSHOT_BASE_URL,
            temperature=0.6,
            model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}}
        )

        llm_with_tools = llm.bind_tools([get_weather])

        # First turn
        print("Turn 1: User asks about weather")
        messages = [HumanMessage(content="What's the weather in San Francisco?")]
        response1 = llm_with_tools.invoke(messages)

        print(f"Response 1 type: {type(response1)}")
        print(f"Response 1 content: {response1.content}")
        print(f"Tool calls: {response1.tool_calls}")
        print(f"Additional kwargs: {response1.additional_kwargs}")

        if not response1.tool_calls:
            print_result("LangChain ChatOpenAI - Tool Call with Thinking Disabled", False,
                         "No tool call made")
            return False

        # Simulate tool execution
        tool_call = response1.tool_calls[0]
        tool_result = get_weather.invoke(tool_call["args"])

        # Second turn
        print("\nTurn 2: Returning tool result")
        messages.append(response1)
        messages.append(ToolMessage(
            content=tool_result,
            tool_call_id=tool_call["id"]
        ))

        print(f"Messages being sent (count={len(messages)}):")
        for i, msg in enumerate(messages):
            print(f"  [{i}] {type(msg).__name__}: {msg}")

        response2 = llm_with_tools.invoke(messages)

        print(f"\nFinal response: {response2.content}")
        print(f"Additional kwargs: {response2.additional_kwargs}")

        print_result("LangChain ChatOpenAI - Tool Call with Thinking Disabled", True,
                     "Multi-turn tool call successful")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        print_result("LangChain ChatOpenAI - Tool Call with Thinking Disabled", False, str(e))
        return False


# =============================================================================
# Test 3: LangGraph create_react_agent Tests
# =============================================================================

def test_langgraph_agent_thinking_enabled():
    """Test LangGraph create_react_agent with thinking enabled."""
    print_section("Test 3a: LangGraph Agent - Thinking Enabled")

    try:
        llm = ChatOpenAI(
            model=MODEL,
            api_key=MOONSHOT_API_KEY,
            base_url=MOONSHOT_BASE_URL,
            temperature=1.0
        )

        agent = create_react_agent(llm, [get_weather])

        print("Invoking agent with weather query...")
        result = agent.invoke({
            "messages": [HumanMessage(content="What's the weather in San Francisco?")]
        })

        print(f"\nAgent result messages ({len(result['messages'])} total):")
        for i, msg in enumerate(result["messages"]):
            print(f"  [{i}] {type(msg).__name__}: {msg.content[:100] if hasattr(msg, 'content') else msg}")

        final_message = result["messages"][-1]
        print(f"\nFinal message content: {final_message.content}")

        print_result("LangGraph Agent - Thinking Enabled", True,
                     f"Agent completed: {final_message.content[:50]}...")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        print_result("LangGraph Agent - Thinking Enabled", False, str(e))
        return False


def test_langgraph_agent_thinking_disabled():
    """Test LangGraph create_react_agent with thinking disabled."""
    print_section("Test 3b: LangGraph Agent - Thinking Disabled")

    try:
        llm = ChatOpenAI(
            model=MODEL,
            api_key=MOONSHOT_API_KEY,
            base_url=MOONSHOT_BASE_URL,
            temperature=0.6,
            model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}}
        )

        agent = create_react_agent(llm, [get_weather])

        print("Invoking agent with weather query...")
        result = agent.invoke({
            "messages": [HumanMessage(content="What's the weather in San Francisco?")]
        })

        print(f"\nAgent result messages ({len(result['messages'])} total):")
        for i, msg in enumerate(result["messages"]):
            print(f"  [{i}] {type(msg).__name__}: {msg.content[:100] if hasattr(msg, 'content') else msg}")

        final_message = result["messages"][-1]
        print(f"\nFinal message content: {final_message.content}")

        print_result("LangGraph Agent - Thinking Disabled", True,
                     f"Agent completed: {final_message.content[:50]}...")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        print_result("LangGraph Agent - Thinking Disabled", False, str(e))
        return False


# =============================================================================
# Main Test Runner
# =============================================================================

def main():
    """Run all tests systematically."""
    print("\n" + "=" * 80)
    print(" Kimi K2.5 Integration Test Suite")
    print(" Testing Moonshot API at multiple abstraction levels")
    print("=" * 80)

    results = {}

    # Test 1: Direct OpenAI Client
    results["1a_direct_thinking_enabled"] = test_direct_openai_thinking_enabled()
    results["1b_direct_thinking_disabled"] = test_direct_openai_thinking_disabled()
    results["1c_direct_tool_thinking_enabled"] = test_direct_openai_tool_call_thinking_enabled()
    results["1d_direct_tool_thinking_disabled"] = test_direct_openai_tool_call_thinking_disabled()

    # Test 2: LangChain ChatOpenAI
    results["2a_langchain_thinking_enabled"] = test_langchain_chat_thinking_enabled()
    results["2b_langchain_thinking_disabled"] = test_langchain_chat_thinking_disabled()
    results["2c_langchain_tool_thinking_enabled"] = test_langchain_chat_tool_call_thinking_enabled()
    results["2d_langchain_tool_thinking_disabled"] = test_langchain_chat_tool_call_thinking_disabled()

    # Test 3: LangGraph
    results["3a_langgraph_thinking_enabled"] = test_langgraph_agent_thinking_enabled()
    results["3b_langgraph_thinking_disabled"] = test_langgraph_agent_thinking_disabled()

    # Summary
    print_section("Test Summary")
    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print(f"Results: {passed}/{total} tests passed\n")

    for test_name, passed in results.items():
        status = "✓" if passed else "✗"
        print(f"{status} {test_name}")

    print("\n" + "=" * 80)
    print(f" Overall: {'SUCCESS' if passed == total else 'FAILURES DETECTED'}")
    print("=" * 80 + "\n")

    return results


if __name__ == "__main__":
    results = main()
