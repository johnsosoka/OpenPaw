"""Tests for channel-agnostic outbound retry (openpaw/channels/retry.py)
and the ChannelAdapter retry interface."""

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.retry import RetryPolicy, retry_async


class _BoomError(Exception):
    """Retryable stand-in."""


class _PermanentError(Exception):
    """Non-retryable stand-in."""


class _FloodControlError(Exception):
    """Carries a server retry_after hint (like Telegram RetryAfter)."""

    def __init__(self, retry_after: float) -> None:
        super().__init__("slow down")
        self.retry_after = retry_after


def _fast_policy(**kw: object) -> RetryPolicy:
    # jitter off for deterministic delay assertions
    return RetryPolicy(max_attempts=3, base_delay=1.0, max_delay=8.0, jitter=0.0, **kw)  # type: ignore[arg-type]


class TestRetryAsync:
    async def test_success_first_try_no_sleep(self) -> None:
        calls, sleeps = 0, []

        async def op() -> str:
            nonlocal calls
            calls += 1
            return "ok"

        out = await retry_async(
            op, retryable=(_BoomError,), policy=_fast_policy(),
            sleep=lambda d: sleeps.append(d),  # type: ignore[arg-type,func-returns-value]
        )
        assert out == "ok" and calls == 1 and sleeps == []

    async def test_retries_then_succeeds(self) -> None:
        calls, sleeps = 0, []

        async def op() -> str:
            nonlocal calls
            calls += 1
            if calls < 2:
                raise _BoomError()
            return "ok"

        async def fake_sleep(d: float) -> None:
            sleeps.append(d)

        out = await retry_async(op, retryable=(_BoomError,), policy=_fast_policy(), sleep=fake_sleep)
        assert out == "ok" and calls == 2 and sleeps == [1.0]  # one backoff at base_delay

    async def test_exhausts_and_raises_last(self) -> None:
        calls, sleeps = 0, []

        async def op() -> str:
            nonlocal calls
            calls += 1
            raise _BoomError()

        async def fake_sleep(d: float) -> None:
            sleeps.append(d)

        with pytest.raises(_BoomError):
            await retry_async(op, retryable=(_BoomError,), policy=_fast_policy(), sleep=fake_sleep)
        assert calls == 3 and sleeps == [1.0, 2.0]  # attempts-1 backoffs, exponential

    async def test_deny_list_overrides_allow_list_for_subclass(self) -> None:
        # A permanent error subclassing a retryable type must not loop.
        class _SubBoomError(_BoomError):
            pass

        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            raise _SubBoomError()

        with pytest.raises(_SubBoomError):
            await retry_async(
                op, retryable=(_BoomError,), non_retryable=(_SubBoomError,), policy=_fast_policy()
            )
        assert calls == 1  # denied immediately despite matching the allow-list

    async def test_non_retryable_raises_immediately(self) -> None:
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            raise _PermanentError()

        with pytest.raises(_PermanentError):
            await retry_async(op, retryable=(_BoomError,), policy=_fast_policy())
        assert calls == 1

    async def test_empty_retryable_runs_once(self) -> None:
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            raise _BoomError()

        with pytest.raises(_BoomError):
            await retry_async(op, retryable=(), policy=_fast_policy())
        assert calls == 1  # no retry path taken

    async def test_honors_server_retry_after_hint(self) -> None:
        calls, sleeps = 0, []

        async def op() -> str:
            nonlocal calls
            calls += 1
            if calls < 2:
                raise _FloodControlError(retry_after=5.0)
            return "ok"

        async def fake_sleep(d: float) -> None:
            sleeps.append(d)

        out = await retry_async(
            op, retryable=(_FloodControlError,), policy=_fast_policy(), sleep=fake_sleep
        )
        assert out == "ok" and sleeps == [5.0]  # server hint, not the 1.0 schedule

    async def test_retry_after_capped_at_max_delay(self) -> None:
        async def op() -> str:
            raise _FloodControlError(retry_after=999.0)

        sleeps: list[float] = []

        async def fake_sleep(d: float) -> None:
            sleeps.append(d)

        with pytest.raises(_FloodControlError):
            await retry_async(
                op, retryable=(_FloodControlError,),
                policy=RetryPolicy(max_attempts=2, base_delay=1.0, max_delay=8.0, jitter=0.0),
                sleep=fake_sleep,
            )
        assert sleeps == [8.0]  # clamped to max_delay


class TestRetryPolicy:
    def test_exponential_schedule(self) -> None:
        p = RetryPolicy(base_delay=0.5, max_delay=8.0)
        assert p.delay_for(1) == 0.5
        assert p.delay_for(2) == 1.0
        assert p.delay_for(3) == 2.0

    def test_delay_capped(self) -> None:
        p = RetryPolicy(base_delay=1.0, max_delay=3.0)
        assert p.delay_for(10) == 3.0


class _DummyChannel(ChannelAdapter):
    """Minimal adapter to exercise the retry interface without a transport."""

    name = "dummy"
    RETRYABLE_SEND_ERRORS = (_BoomError,)
    retry_policy = RetryPolicy(max_attempts=3, base_delay=0.0, max_delay=0.0, jitter=0.0)

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_message(self, session_key, content, **kwargs):  # type: ignore[no-untyped-def]
        ...
    def on_message(self, callback):  # type: ignore[no-untyped-def]
        ...


class TestAdapterInterface:
    async def test_send_with_retry_retries_declared_errors(self) -> None:
        ch = _DummyChannel()
        calls = 0

        async def op() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise _BoomError()
            return "delivered"

        out = await ch.send_with_retry("send_message", op)
        assert out == "delivered" and calls == 3

    async def test_default_adapter_has_no_retry(self) -> None:
        # Base default RETRYABLE_SEND_ERRORS is empty ⇒ inert (stdio, etc.).
        assert ChannelAdapter.RETRYABLE_SEND_ERRORS == ()
