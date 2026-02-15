"""Tests for thinking token stripping in AgentRunner."""

from openpaw.agent.runner import AgentRunner


class TestThinkingTokenStripping:
    """Test suite for thinking token removal from model responses."""

    def test_strip_simple_thinking_tokens(self):
        """Test removing basic thinking tokens."""
        input_text = "<think>This is internal reasoning</think>Hello, world!"
        expected = "Hello, world!"
        assert AgentRunner._strip_thinking_tokens(input_text) == expected

    def test_strip_multiline_thinking_tokens(self):
        """Test removing thinking tokens with multiline content."""
        input_text = """<think>
The user is asking about something.
Let me think through this carefully.
I should respond helpfully.
</think>

Here is my actual response."""
        expected = "Here is my actual response."
        assert AgentRunner._strip_thinking_tokens(input_text) == expected

    def test_strip_thinking_tokens_with_markdown(self):
        """Test stripping thinking tokens from response with markdown."""
        input_text = """<think>
The user asked about Kimi.
I should respond in character.
</think>

*eyes light up*

KIMI! Oh, you mean the *other* one!"""
        expected = "*eyes light up*\n\nKIMI! Oh, you mean the *other* one!"
        assert AgentRunner._strip_thinking_tokens(input_text) == expected

    def test_strip_multiple_thinking_blocks(self):
        """Test removing multiple thinking token blocks."""
        input_text = "<think>First thought</think>Part 1<think>Second thought</think>Part 2"
        expected = "Part 1Part 2"
        assert AgentRunner._strip_thinking_tokens(input_text) == expected

    def test_no_thinking_tokens(self):
        """Test that text without thinking tokens is unchanged."""
        input_text = "This is a normal response without any thinking tokens."
        assert AgentRunner._strip_thinking_tokens(input_text) == input_text

    def test_empty_thinking_tokens(self):
        """Test handling of empty thinking token blocks."""
        input_text = "<think></think>Response text"
        expected = "Response text"
        assert AgentRunner._strip_thinking_tokens(input_text) == expected

    def test_case_insensitive_thinking_tags(self):
        """Test that thinking tags are matched case-insensitively."""
        input_text = "<THINK>Uppercase tags</THINK>Response"
        expected = "Response"
        assert AgentRunner._strip_thinking_tokens(input_text) == expected

        input_text = "<Think>Mixed case</Think>Response"
        expected = "Response"
        assert AgentRunner._strip_thinking_tokens(input_text) == expected

    def test_strip_whitespace_after_thinking_tokens(self):
        """Test that trailing whitespace after thinking tokens is removed."""
        input_text = "<think>Reasoning</think>   \n\nResponse"
        expected = "Response"
        assert AgentRunner._strip_thinking_tokens(input_text) == expected

    def test_thinking_tokens_in_middle(self):
        """Test thinking tokens appearing in the middle of response."""
        input_text = "Start text<think>internal reasoning</think>End text"
        expected = "Start textEnd text"
        assert AgentRunner._strip_thinking_tokens(input_text) == expected

    def test_realistic_kimi_k2_response(self):
        """Test with realistic Kimi K2 thinking model output."""
        input_text = (
            '<think> The user is asking "Does Kimi ring a bell?" '
            "This is a straightforward question...\n"
            "No tools needed. Just a direct answer in character. </think> *eyes light up*\n\n"
            "KIMI! Oh, you mean the *other* one!\n\n"
            "Yeah, Moonshot's Kimi models are fascinating—especially the K1 series with native "
            "reasoning. But K2? That's the real heavyweight: 1 trillion parameter MoE architecture, "
            "256k context window.\n\n"
            "The fact that they're exposing the thinking traces in the response... bold move. "
            "Makes it easier to debug the model's reasoning chains, though you'd probably want to "
            "strip those tags before showing output to end users.\n\n"
            "You thinking of integrating it into OpenPaw?"
        )

        expected = (
            "*eyes light up*\n\n"
            "KIMI! Oh, you mean the *other* one!\n\n"
            "Yeah, Moonshot's Kimi models are fascinating—especially the K1 series with native "
            "reasoning. But K2? That's the real heavyweight: 1 trillion parameter MoE architecture, "
            "256k context window.\n\n"
            "The fact that they're exposing the thinking traces in the response... bold move. "
            "Makes it easier to debug the model's reasoning chains, though you'd probably want to "
            "strip those tags before showing output to end users.\n\n"
            "You thinking of integrating it into OpenPaw?"
        )

        assert AgentRunner._strip_thinking_tokens(input_text) == expected
