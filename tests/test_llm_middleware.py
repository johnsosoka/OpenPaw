"""Tests for openpaw/llm/middleware.py - LangGraph pre/post model hooks."""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from openpaw.agent.middleware.llm_hooks import (
    build_pre_model_hook,
    build_post_model_hook,
    _sanitize_reasoning_content,
    _strip_thinking_tokens,
)


class TestBuildPreModelHook:
    """Test build_pre_model_hook factory."""

    def test_disabled_returns_none(self):
        """Returns None when strip_reasoning=False."""
        hook = build_pre_model_hook(strip_reasoning=False)
        assert hook is None

    def test_enabled_returns_callable(self):
        """Returns callable when strip_reasoning=True."""
        hook = build_pre_model_hook(strip_reasoning=True)
        assert callable(hook)


class TestBuildPostModelHook:
    """Test build_post_model_hook factory."""

    def test_disabled_returns_none(self):
        """Returns None when strip_thinking=False."""
        hook = build_post_model_hook(strip_thinking=False)
        assert hook is None

    def test_enabled_returns_callable(self):
        """Returns callable when strip_thinking=True."""
        hook = build_post_model_hook(strip_thinking=True)
        assert callable(hook)


class TestSanitizeReasoningContent:
    """Test _sanitize_reasoning_content logic."""

    def test_strips_from_additional_kwargs(self):
        """Strips reasoning_content from AIMessage.additional_kwargs."""
        msg = AIMessage(
            content="Hello",
            additional_kwargs={"reasoning_content": "I should greet the user"}
        )
        state = {"messages": [msg]}

        result = _sanitize_reasoning_content(state)

        assert "reasoning_content" not in result["messages"][0].additional_kwargs

    def test_strips_from_response_metadata(self):
        """Strips reasoning_content from AIMessage.response_metadata."""
        msg = AIMessage(content="Hello")
        msg.response_metadata = {"reasoning_content": "Internal reasoning"}
        state = {"messages": [msg]}

        result = _sanitize_reasoning_content(state)

        assert "reasoning_content" not in result["messages"][0].response_metadata

    def test_strips_from_both_kwargs_and_metadata(self):
        """Strips reasoning_content from both locations."""
        msg = AIMessage(
            content="Hello",
            additional_kwargs={"reasoning_content": "kwargs reasoning"}
        )
        msg.response_metadata = {"reasoning_content": "metadata reasoning"}
        state = {"messages": [msg]}

        result = _sanitize_reasoning_content(state)

        assert "reasoning_content" not in result["messages"][0].additional_kwargs
        assert "reasoning_content" not in result["messages"][0].response_metadata

    def test_preserves_non_ai_messages(self):
        """Doesn't touch HumanMessage."""
        human_msg = HumanMessage(content="Hello")
        ai_msg = AIMessage(
            content="Hi",
            additional_kwargs={"reasoning_content": "Should respond"}
        )
        state = {"messages": [human_msg, ai_msg]}

        result = _sanitize_reasoning_content(state)

        # HumanMessage unchanged
        assert result["messages"][0] is human_msg
        # AIMessage stripped
        assert "reasoning_content" not in result["messages"][1].additional_kwargs

    def test_no_reasoning_content_present(self):
        """No-op when no reasoning_content present."""
        msg = AIMessage(content="Hello", additional_kwargs={"other": "data"})
        state = {"messages": [msg]}

        result = _sanitize_reasoning_content(state)

        assert result["messages"][0].additional_kwargs == {"other": "data"}

    def test_empty_messages(self):
        """Handles empty messages list."""
        state = {"messages": []}
        result = _sanitize_reasoning_content(state)
        assert result["messages"] == []

    def test_no_messages_key(self):
        """Handles state without messages key."""
        state = {}
        result = _sanitize_reasoning_content(state)
        assert result.get("messages", []) == []


class TestStripThinkingTokens:
    """Test _strip_thinking_tokens logic."""

    def test_strips_string_content_basic(self):
        """Strips <think>...</think> from string content."""
        msg = AIMessage(content="<think>Let me think about this</think>The answer is 42")
        state = {"messages": [msg]}

        result = _strip_thinking_tokens(state)

        assert result["messages"][0].content == "The answer is 42"

    def test_strips_string_content_multiline(self):
        """Strips multiline thinking tags."""
        msg = AIMessage(content="""<think>
Let me think...
This is complex
</think>Final answer""")
        state = {"messages": [msg]}

        result = _strip_thinking_tokens(state)

        assert result["messages"][0].content == "Final answer"

    def test_strips_string_content_case_insensitive(self):
        """Strips thinking tags case-insensitively."""
        msg = AIMessage(content="<THINK>reasoning</THINK>Answer")
        state = {"messages": [msg]}

        result = _strip_thinking_tokens(state)

        assert result["messages"][0].content == "Answer"

    def test_strips_string_content_multiple_tags(self):
        """Strips multiple thinking tags from string."""
        msg = AIMessage(content="<think>First</think>Text<think>Second</think>More")
        state = {"messages": [msg]}

        result = _strip_thinking_tokens(state)

        assert result["messages"][0].content == "TextMore"

    def test_filters_structured_content_dict_blocks(self):
        """Filters thinking blocks from dict-based structured content."""
        msg = AIMessage(content=[
            {"type": "thinking", "content": "reasoning here"},
            {"type": "text", "content": "The answer is 42"},
        ])
        state = {"messages": [msg]}

        result = _strip_thinking_tokens(state)

        assert len(result["messages"][0].content) == 1
        assert result["messages"][0].content[0]["type"] == "text"

    def test_preserves_non_thinking_blocks(self):
        """Preserves all non-thinking blocks."""
        msg = AIMessage(content=[
            {"type": "thinking", "content": "reasoning"},
            {"type": "text", "content": "Text"},
            {"type": "image", "url": "https://example.com/img.png"},
            {"type": "tool_use", "name": "search"},
        ])
        state = {"messages": [msg]}

        result = _strip_thinking_tokens(state)

        assert len(result["messages"][0].content) == 3
        assert result["messages"][0].content[0]["type"] == "text"
        assert result["messages"][0].content[1]["type"] == "image"
        assert result["messages"][0].content[2]["type"] == "tool_use"

    def test_empty_messages_list(self):
        """Handles empty messages list."""
        state = {"messages": []}
        result = _strip_thinking_tokens(state)
        assert result["messages"] == []

    def test_non_ai_last_message(self):
        """No-op when last message isn't AIMessage."""
        human_msg = HumanMessage(content="Hello")
        state = {"messages": [human_msg]}

        result = _strip_thinking_tokens(state)

        assert result["messages"][0] is human_msg

    def test_only_affects_last_message(self):
        """Only strips thinking from the last AI message."""
        msg1 = AIMessage(content="<think>Old thinking</think>Old answer")
        msg2 = HumanMessage(content="Follow-up")
        msg3 = AIMessage(content="<think>New thinking</think>New answer")
        state = {"messages": [msg1, msg2, msg3]}

        result = _strip_thinking_tokens(state)

        # First AI message unchanged (not last)
        assert "<think>" in result["messages"][0].content
        # Last AI message stripped
        assert result["messages"][2].content == "New answer"

    def test_no_messages_key(self):
        """Handles state without messages key."""
        state = {}
        result = _strip_thinking_tokens(state)
        assert result.get("messages", []) == []


class TestIntegration:
    """Test hook factories with actual state."""

    def test_pre_hook_integration(self):
        """Pre-model hook strips reasoning from conversation history."""
        msg1 = AIMessage(
            content="Hello",
            additional_kwargs={"reasoning_content": "Should greet"}
        )
        msg2 = HumanMessage(content="How are you?")
        msg3 = AIMessage(
            content="Good",
            additional_kwargs={"reasoning_content": "Polite response"}
        )
        state = {"messages": [msg1, msg2, msg3]}

        hook = build_pre_model_hook(strip_reasoning=True)
        result = hook(state)

        # All AI messages stripped
        assert "reasoning_content" not in result["messages"][0].additional_kwargs
        assert "reasoning_content" not in result["messages"][2].additional_kwargs
        # Human message unchanged
        assert result["messages"][1] is msg2

    def test_post_hook_integration(self):
        """Post-model hook strips thinking from last message."""
        msg1 = AIMessage(content="<think>Old</think>First")
        msg2 = HumanMessage(content="Question")
        msg3 = AIMessage(content="<think>New reasoning</think>Final answer")
        state = {"messages": [msg1, msg2, msg3]}

        hook = build_post_model_hook(strip_thinking=True)
        result = hook(state)

        # Only last AI message stripped
        assert "<think>" in result["messages"][0].content
        assert result["messages"][2].content == "Final answer"
