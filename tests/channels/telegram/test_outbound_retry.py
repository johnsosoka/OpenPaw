"""Telegram outbound sender retries transient network errors (the fix for
the ConnectError-drops-a-delivery gap)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import BadRequest, NetworkError

from openpaw.channels.retry import RetryPolicy, retry_async
from openpaw.channels.telegram import TelegramChannel
from openpaw.channels.telegram.outbound import TelegramOutboundSender


def _retry_runner():
    """A runner mirroring the adapter's, with instant (no-op) sleep."""
    async def run(describe, operation):
        async def no_sleep(_d):
            return None

        return await retry_async(
            operation,
            retryable=TelegramChannel.RETRYABLE_SEND_ERRORS,
            non_retryable=TelegramChannel.NON_RETRYABLE_SEND_ERRORS,
            policy=RetryPolicy(max_attempts=3, base_delay=0.0, max_delay=0.0, jitter=0.0),
            describe=describe,
            sleep=no_sleep,
        )

    return run


def _sender_with(app):
    return TelegramOutboundSender(
        app=app, channel_name="telegram", bot_id=42, retry=_retry_runner()
    )


class TestOutboundRetry:
    async def test_send_message_retries_network_error_then_succeeds(self) -> None:
        app = MagicMock()
        good = MagicMock(message_id=777)
        # First call is a transient network blip, second succeeds.
        app.bot.send_message = AsyncMock(side_effect=[NetworkError("blip"), good])

        sender = _sender_with(app)
        msg = await sender.send_message("telegram:123", "hello", parse_mode="HTML")

        assert msg.id == "777"
        assert app.bot.send_message.await_count == 2  # retried once

    async def test_send_message_gives_up_after_max_attempts(self) -> None:
        app = MagicMock()
        app.bot.send_message = AsyncMock(side_effect=NetworkError("down"))

        sender = _sender_with(app)
        with pytest.raises(NetworkError):
            await sender.send_message("telegram:123", "hello", parse_mode="HTML")
        assert app.bot.send_message.await_count == 3  # max_attempts

    async def test_bad_request_is_not_retried(self) -> None:
        # BadRequest (permanent) must surface on the first try, not loop.
        app = MagicMock()
        app.bot.send_message = AsyncMock(side_effect=BadRequest("chat not found"))

        sender = _sender_with(app)
        with pytest.raises(BadRequest):
            await sender.send_message("telegram:123", "hello", parse_mode="HTML")
        assert app.bot.send_message.await_count == 1

    async def test_no_retry_runner_runs_once(self) -> None:
        # Default construction (no retry wired) preserves single-shot behavior.
        app = MagicMock()
        app.bot.send_message = AsyncMock(side_effect=NetworkError("blip"))
        sender = TelegramOutboundSender(app=app, channel_name="telegram", bot_id=42)
        with pytest.raises(NetworkError):
            await sender.send_message("telegram:123", "hello", parse_mode="HTML")
        assert app.bot.send_message.await_count == 1


class TestChannelDeclaration:
    def test_retryable_errors_declared(self) -> None:
        from telegram.error import RetryAfter, TimedOut

        assert NetworkError in TelegramChannel.RETRYABLE_SEND_ERRORS
        assert TimedOut in TelegramChannel.RETRYABLE_SEND_ERRORS
        assert RetryAfter in TelegramChannel.RETRYABLE_SEND_ERRORS
        assert BadRequest not in TelegramChannel.RETRYABLE_SEND_ERRORS
