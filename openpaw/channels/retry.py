"""Channel-agnostic retry for transient outbound-delivery failures.

Every channel talks to a remote API to deliver messages, and every such API
has occasional transient failures (a dropped connection, a timeout, a
flood-control pause). A lost *delivery* is worse than a lost model call — the
agent already did the work — so outbound sends get a bounded retry with
exponential backoff, mirroring the model layer's ``max_retries`` but at the
channel boundary.

The classification of *which* errors are transient is channel-specific and
lives on each :class:`~openpaw.channels.base.ChannelAdapter` (its
``RETRYABLE_SEND_ERRORS`` tuple); this module owns only the mechanism. A
channel that declares no retryable errors (e.g. stdio) runs the operation
exactly once — the retry path is inert by default.
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryRunner(Protocol):
    """A bound retry runner: ``await runner(describe, operation)``.

    Channels hand their outbound senders one of these (typically the
    adapter's :meth:`ChannelAdapter.send_with_retry`) so senders stay
    ignorant of policy and error classification — both live on the adapter.
    A Protocol (not a plain alias) so the same runner is callable at many
    result types across a sender's calls.
    """

    async def __call__(
        self, describe: str, operation: Callable[[], Awaitable[T]]
    ) -> T: ...


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential-backoff schedule for outbound retries.

    Attributes:
        max_attempts: Total tries including the first (1 = no retry).
        base_delay: Seconds before the first retry; doubles each attempt.
        max_delay: Ceiling on any single backoff wait.
        jitter: Fractional randomization (+/-) applied to each delay to avoid
            synchronized retries; 0 disables it.
    """

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.1

    def delay_for(self, attempt: int) -> float:
        """Backoff (seconds) to wait *after* a failed 1-based ``attempt``."""
        raw: float = self.base_delay * (2 ** (attempt - 1))
        return min(raw, self.max_delay)


DEFAULT_RETRY_POLICY = RetryPolicy()


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    retryable: tuple[type[BaseException], ...],
    non_retryable: tuple[type[BaseException], ...] = (),
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    describe: str = "operation",
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Run ``operation``, retrying transient failures with backoff.

    Args:
        operation: Zero-arg coroutine factory — re-invoked per attempt.
        retryable: Exception types treated as transient. Empty ⇒ no retry
            (the operation runs exactly once); anything not listed propagates
            immediately.
        non_retryable: Deny-list that overrides ``retryable`` — matched first,
            so a permanent error that *subclasses* a retryable type (e.g.
            Telegram ``BadRequest`` under ``NetworkError``) surfaces at once
            instead of looping.
        policy: Backoff schedule.
        describe: Short label for log lines (e.g. "telegram.send_message").
        sleep: Injectable sleep (tests pass a no-op).

    Returns:
        Whatever ``operation`` returns on the first success.

    Raises:
        The last transient exception if every attempt fails, or any
        non-retryable exception on the spot.
    """
    if not retryable:
        return await operation()

    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await operation()
        except non_retryable:
            raise  # permanent — deny-list wins over the allow-list
        except retryable as exc:  # type: ignore[misc]  # runtime tuple of types
            last_exc = exc
            if attempt >= policy.max_attempts:
                break
            delay = _delay_with_server_hint(exc, policy, attempt)
            logger.warning(
                "Transient failure on %s (attempt %d/%d); retrying in %.2fs: %s",
                describe, attempt, policy.max_attempts, delay, exc,
            )
            await sleep(delay)

    assert last_exc is not None  # loop ran at least once with a retryable catch
    logger.error(
        "Giving up on %s after %d attempts: %s", describe, policy.max_attempts, last_exc
    )
    raise last_exc


def _delay_with_server_hint(
    exc: BaseException, policy: RetryPolicy, attempt: int
) -> float:
    """Backoff for this attempt, honoring a server ``retry_after`` hint.

    Flood-control errors (e.g. Telegram ``RetryAfter``) carry the exact wait
    the server wants; respect it (capped at ``max_delay``) instead of the
    exponential schedule. Jitter is applied either way.
    """
    hint = getattr(exc, "retry_after", None)
    if isinstance(hint, int | float) and hint > 0:
        base = min(float(hint), policy.max_delay)
    else:
        base = policy.delay_for(attempt)
    if policy.jitter:
        spread = base * policy.jitter
        base = max(0.0, base + random.uniform(-spread, spread))
    return base
