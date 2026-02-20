"""Tests for timeout notification enhancements."""

from openpaw.prompts.system_events import (
    TIMEOUT_NOTIFICATION_GENERIC,
    TIMEOUT_NOTIFICATION_TEMPLATE,
)


class TestTimeoutTemplates:
    """Test timeout notification template rendering."""

    def test_timeout_with_tool_context(self) -> None:
        """Timeout message includes tool name when tool context is available."""
        result = TIMEOUT_NOTIFICATION_TEMPLATE.format(
            timeout=300,
            tool_name="shell",
        )
        assert "shell" in result
        assert "300" in result
        assert "ran out of time" in result
        assert "operation may still be completing" in result

    def test_timeout_without_tool_context(self) -> None:
        """Timeout message falls back to generic message without tool context."""
        result = TIMEOUT_NOTIFICATION_GENERIC.format(timeout=300)
        assert "300" in result
        assert "ran out of time" in result
        assert "simpler request" in result
        # Should NOT mention a specific tool
        assert "shell" not in result
        assert "operation may still be completing" not in result

    def test_timeout_message_formats_correctly(self) -> None:
        """Timeout messages format with proper grammar and punctuation."""
        tool_result = TIMEOUT_NOTIFICATION_TEMPLATE.format(
            timeout=600,
            tool_name="browser_navigate",
        )
        generic_result = TIMEOUT_NOTIFICATION_GENERIC.format(timeout=600)

        # Both should be complete sentences
        assert tool_result.endswith(".")
        assert generic_result.endswith(".")

        # Both should include the timeout value
        assert "600" in tool_result
        assert "600" in generic_result

        # Tool-specific message should mention the tool
        assert "browser_navigate" in tool_result
