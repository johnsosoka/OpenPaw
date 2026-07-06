"""Discord outbound sender retries transient network errors — proves the
channel retry interface generalizes beyond Telegram."""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from openpaw.channels.discord import DiscordChannel
from openpaw.channels.discord.outbound import DiscordOutboundSender
from openpaw.channels.retry import RetryPolicy, retry_async


def _retry_runner():
    async def run(describe, operation):
        async def no_sleep(_d):
            return None

        return await retry_async(
            operation,
            retryable=DiscordChannel.RETRYABLE_SEND_ERRORS,
            non_retryable=DiscordChannel.NON_RETRYABLE_SEND_ERRORS,
            policy=RetryPolicy(max_attempts=3, base_delay=0.0, max_delay=0.0, jitter=0.0),
            describe=describe,
            sleep=no_sleep,
        )

    return run


def _sender(channel, *, retry=True):
    s = DiscordOutboundSender(
        client=MagicMock(), channel_name="discord", bot_id=1,
        retry=_retry_runner() if retry else None,
    )
    s._resolve_channel = AsyncMock(return_value=channel)  # type: ignore[method-assign]
    return s


class TestDiscordOutboundRetry:
    async def test_send_retries_connection_error_then_succeeds(self) -> None:
        channel = MagicMock()
        good = MagicMock(id=555)
        channel.send = AsyncMock(side_effect=[aiohttp.ClientConnectionError("drop"), good])

        msg = await _sender(channel).send_message("discord:123", "hi")

        assert msg.id == "555"
        assert channel.send.await_count == 2

    async def test_send_gives_up_after_max_attempts(self) -> None:
        channel = MagicMock()
        channel.send = AsyncMock(side_effect=aiohttp.ClientConnectionError("down"))

        with pytest.raises(aiohttp.ClientConnectionError):
            await _sender(channel).send_message("discord:123", "hi")
        assert channel.send.await_count == 3

    async def test_no_retry_runner_runs_once(self) -> None:
        channel = MagicMock()
        channel.send = AsyncMock(side_effect=aiohttp.ClientConnectionError("drop"))

        with pytest.raises(aiohttp.ClientConnectionError):
            await _sender(channel, retry=False).send_message("discord:123", "hi")
        assert channel.send.await_count == 1
