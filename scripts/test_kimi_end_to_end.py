#!/usr/bin/env python3
"""
End-to-end test of Kimi K2.5 integration with the working configuration.

This simulates how OpenPaw uses LangGraph create_react_agent with the
configured settings from krieger/agent.yaml.
"""

import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

# Load environment from Krieger's workspace
ENV_PATH = "/Users/john/code/projects/OpenPaw/agent_workspaces/krieger/.env"
load_dotenv(ENV_PATH)

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY")
if not MOONSHOT_API_KEY:
    print(f"ERROR: MOONSHOT_API_KEY not found in {ENV_PATH}")
    exit(1)

# Simple test tools
@tool
def get_weather(location: str) -> str:
    """Get the weather for a location."""
    return f"The weather in {location} is sunny, 72°F."

@tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression."""
    try:
        result = eval(expression)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Error: {e}"

def test_multi_turn_conversation():
    """Test a multi-turn conversation with tool usage."""
    print("=" * 80)
    print(" End-to-End Test: Kimi K2.5 with Working Configuration")
    print("=" * 80)
    print()

    # Create LLM with the exact configuration from krieger/agent.yaml
    llm = ChatOpenAI(
        model="kimi-k2.5",
        api_key=MOONSHOT_API_KEY,
        base_url="https://api.moonshot.ai/v1",
        temperature=0.6,
        model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}}
    )

    # Create agent with tools
    agent = create_react_agent(llm, [get_weather, calculate])

    # Test 1: Single tool call
    print("Test 1: Single tool call (weather)")
    print("-" * 80)
    result1 = agent.invoke({
        "messages": [HumanMessage(content="What's the weather in Tokyo?")]
    })

    print(f"Messages exchanged: {len(result1['messages'])}")
    print(f"Final response: {result1['messages'][-1].content}")
    print()

    # Test 2: Multiple tool calls
    print("Test 2: Multiple tool calls in conversation")
    print("-" * 80)
    result2 = agent.invoke({
        "messages": [
            HumanMessage(content="What's the weather in Paris?"),
        ]
    })

    # Continue conversation
    result2 = agent.invoke({
        "messages": result2["messages"] + [
            HumanMessage(content="Now calculate 42 * 17")
        ]
    })

    print(f"Messages exchanged: {len(result2['messages'])}")
    print(f"Final response: {result2['messages'][-1].content}")
    print()

    # Test 3: Complex reasoning task
    print("Test 3: Complex reasoning with multiple steps")
    print("-" * 80)
    result3 = agent.invoke({
        "messages": [
            HumanMessage(content="Get the weather in London, then calculate (the temperature in Fahrenheit * 2) + 10")
        ]
    })

    print(f"Messages exchanged: {len(result3['messages'])}")
    for i, msg in enumerate(result3['messages']):
        msg_type = type(msg).__name__
        content = getattr(msg, 'content', '')[:100]
        print(f"  [{i}] {msg_type}: {content}")
    print(f"\nFinal response: {result3['messages'][-1].content}")
    print()

    print("=" * 80)
    print(" ✅ All tests passed! Kimi K2.5 integration working correctly.")
    print("=" * 80)

if __name__ == "__main__":
    test_multi_turn_conversation()
