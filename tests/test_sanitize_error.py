"""Tests for sanitize_error_for_user utility."""

from openpaw.core.utils import sanitize_error_for_user


class TestSanitizeErrorForUser:
    """Tests for user-facing error message sanitization."""

    def test_timeout_error(self):
        """TimeoutError maps to timeout message."""
        msg = sanitize_error_for_user(TimeoutError("operation timed out after 30s"))
        assert msg == "The request timed out. Please try again."

    def test_connection_error(self):
        """ConnectionError maps to connection message."""
        msg = sanitize_error_for_user(ConnectionError("refused"))
        assert msg == "A connection error occurred. Please try again shortly."

    def test_generic_exception(self):
        """Unknown exceptions get generic message."""
        msg = sanitize_error_for_user(RuntimeError("NullPointerException at /internal/path"))
        assert msg == "Something went wrong processing your message. Please try again."

    def test_value_error_is_generic(self):
        """ValueError should not leak internal details."""
        msg = sanitize_error_for_user(ValueError("invalid config at /etc/secrets"))
        assert msg == "Something went wrong processing your message. Please try again."
        assert "/etc/secrets" not in msg

    def test_no_internal_details_leak(self):
        """Error message should not contain the original exception text."""
        original = "SQLSTATE[42000]: Syntax error at line 42 in /app/db.py"
        msg = sanitize_error_for_user(Exception(original))
        assert original not in msg
        assert "SQLSTATE" not in msg

    def test_async_timeout_error(self):
        """asyncio.TimeoutError (subclass of TimeoutError) maps correctly."""
        import asyncio
        msg = sanitize_error_for_user(asyncio.TimeoutError())
        assert msg == "The request timed out. Please try again."

    def test_os_error_subclass_connection(self):
        """ConnectionRefusedError (subclass of ConnectionError) maps correctly."""
        msg = sanitize_error_for_user(ConnectionRefusedError("refused"))
        assert msg == "A connection error occurred. Please try again shortly."
