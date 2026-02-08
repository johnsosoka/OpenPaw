#!/usr/bin/env python3
"""
Diagnostic script to inspect how LangChain handles reasoning_content.

This shows exactly what happens when LangChain converts messages between
API format and LangChain message objects.
"""

import json
import os
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import _convert_dict_to_message, _convert_message_to_dict

# Load environment
ENV_PATH = "/Users/john/code/projects/OpenPaw/agent_workspaces/krieger/.env"
load_dotenv(ENV_PATH)

MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY")
MOONSHOT_BASE_URL = "https://api.moonshot.ai/v1"


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80 + "\n")


def inspect_message_conversion():
    """Show how LangChain converts messages with reasoning_content."""
    print_section("Message Conversion Inspection")

    # Simulate an API response with reasoning_content
    api_response = {
        "role": "assistant",
        "content": "Let me help you with that.",
        "tool_calls": [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "Tokyo"}'
                }
            }
        ],
        "reasoning_content": "The user asked about weather. I should use the get_weather tool."
    }

    print("Original API Response:")
    print(json.dumps(api_response, indent=2))

    # Convert to LangChain message
    lc_message = _convert_dict_to_message(api_response)

    print("\nLangChain Message Object:")
    print(f"Type: {type(lc_message)}")
    print(f"Content: {lc_message.content}")
    print(f"Additional kwargs: {lc_message.additional_kwargs}")
    print(f"Response metadata: {lc_message.response_metadata}")
    print(f"Tool calls: {lc_message.tool_calls}")

    # Check if reasoning_content is preserved anywhere
    print("\nSearching for reasoning_content...")
    found = False

    if hasattr(lc_message, 'reasoning_content'):
        print(f"  ✓ Found in message.reasoning_content: {lc_message.reasoning_content}")
        found = True

    if 'reasoning_content' in lc_message.additional_kwargs:
        print(f"  ✓ Found in additional_kwargs: {lc_message.additional_kwargs['reasoning_content']}")
        found = True

    if hasattr(lc_message, 'response_metadata') and 'reasoning_content' in lc_message.response_metadata:
        print(f"  ✓ Found in response_metadata: {lc_message.response_metadata['reasoning_content']}")
        found = True

    if not found:
        print("  ✗ reasoning_content NOT FOUND in LangChain message")

    # Convert back to dict (for API replay)
    print("\nConverting back to dict for API replay...")
    try:
        # This is what LangChain does when sending messages back to API
        api_dict = _convert_message_to_dict(lc_message)

        print("Converted dict:")
        print(json.dumps(api_dict, indent=2))

        if 'reasoning_content' in api_dict:
            print("\n✓ reasoning_content PRESERVED in conversion")
        else:
            print("\n✗ reasoning_content LOST in conversion (THIS IS THE BUG)")

    except Exception as e:
        print(f"\nError during conversion: {e}")


def test_actual_api_behavior():
    """Test with actual API to see what fields are returned."""
    print_section("Actual API Behavior Test")

    # Test with thinking enabled
    print("Test 1: Thinking Enabled (temperature=1.0)")
    print("-" * 80)

    llm_enabled = ChatOpenAI(
        model="kimi-k2.5",
        api_key=MOONSHOT_API_KEY,
        base_url=MOONSHOT_BASE_URL,
        temperature=1.0
    )

    response1 = llm_enabled.invoke([HumanMessage(content="What is 2+2?")])

    print(f"Response content: {response1.content}")
    print(f"Response type: {type(response1)}")
    print(f"\nFull response object attributes:")
    for attr in dir(response1):
        if not attr.startswith('_'):
            value = getattr(response1, attr)
            if not callable(value):
                print(f"  {attr}: {value!r}"[:150])

    # Test with thinking disabled
    print("\n\nTest 2: Thinking Disabled (temperature=0.6)")
    print("-" * 80)

    llm_disabled = ChatOpenAI(
        model="kimi-k2.5",
        api_key=MOONSHOT_API_KEY,
        base_url=MOONSHOT_BASE_URL,
        temperature=0.6,
        model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}}
    )

    response2 = llm_disabled.invoke([HumanMessage(content="What is 2+2?")])

    print(f"Response content: {response2.content}")
    print(f"Response type: {type(response2)}")
    print(f"\nFull response object attributes:")
    for attr in dir(response2):
        if not attr.startswith('_'):
            value = getattr(response2, attr)
            if not callable(value):
                print(f"  {attr}: {value!r}"[:150])


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print(" LangChain Message Conversion Diagnostic")
    print(" Investigating reasoning_content handling")
    print("=" * 80)

    inspect_message_conversion()
    test_actual_api_behavior()

    print("\n" + "=" * 80)
    print(" Diagnostic Complete")
    print("=" * 80 + "\n")
