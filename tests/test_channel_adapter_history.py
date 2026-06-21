"""Tests for ChannelAdapter base class — history fetch and event callback methods.

Covers:
- fetch_channel_history() default no-op implementation
- on_channel_event() callback registration
- _channel_event_callback default value
- Subclass override of fetch_channel_history()
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.model.channel import ChannelEvent, ChannelHistoryEntry
from openpaw.model.message import Message

# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing the abstract base
# ---------------------------------------------------------------------------


class _MinimalAdapter(ChannelAdapter):
    """Bare-minimum subclass that satisfies the ABC contract.

    Does not override fetch_channel_history() or on_channel_event() — tests
    the default base-class behaviour.
    """

    name: str = "minimal"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        return Message(content=content, user_id="system", session_key=session_key)

    def on_message(self, callback: Any) -> None:
        self._message_callback = callback


class _OverridingAdapter(_MinimalAdapter):
    """Subclass that overrides fetch_channel_history() with a real implementation."""

    name: str = "overriding"

    async def fetch_channel_history(
        self,
        channel_id: str,
        limit: int = 25,
        before_message_id: str | None = None,
    ) -> list[ChannelHistoryEntry]:
        """Return a fixed list of entries for testing override behaviour."""
        return [
            ChannelHistoryEntry(
                timestamp=datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC),
                user_id="99",
                display_name="TestUser",
                content=f"message from {channel_id}",
            )
        ]


# ---------------------------------------------------------------------------
# fetch_channel_history — default (no-op) behaviour
# ---------------------------------------------------------------------------


class TestFetchChannelHistoryDefault:
    """The default implementation returns an empty list."""

    @pytest.mark.asyncio
    async def test_returns_empty_list(self) -> None:
        adapter = _MinimalAdapter()

        result = await adapter.fetch_channel_history("123456")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_list_type(self) -> None:
        adapter = _MinimalAdapter()

        result = await adapter.fetch_channel_history("channel-id", limit=10)

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_ignores_limit_parameter(self) -> None:
        """Default implementation accepts limit but always returns empty."""
        adapter = _MinimalAdapter()

        result = await adapter.fetch_channel_history("chan", limit=100)

        assert result == []

    @pytest.mark.asyncio
    async def test_ignores_before_message_id_parameter(self) -> None:
        """Default implementation accepts before_message_id but always returns empty."""
        adapter = _MinimalAdapter()

        result = await adapter.fetch_channel_history(
            "chan", limit=25, before_message_id="some-msg-id"
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_calls_each_return_empty(self) -> None:
        """Repeated calls all return empty — no state leakage."""
        adapter = _MinimalAdapter()

        first = await adapter.fetch_channel_history("chan")
        second = await adapter.fetch_channel_history("chan")

        assert first == []
        assert second == []


# ---------------------------------------------------------------------------
# on_channel_event — callback registration
# ---------------------------------------------------------------------------


class TestOnChannelEvent:
    """on_channel_event() stores the callback on the instance."""

    def test_callback_is_none_by_default(self) -> None:
        adapter = _MinimalAdapter()

        assert getattr(adapter, "_channel_event_callback", None) is None

    def test_stores_callback_after_registration(self) -> None:
        adapter = _MinimalAdapter()

        async def my_callback(event: ChannelEvent) -> None:
            pass

        adapter.on_channel_event(my_callback)

        assert adapter._channel_event_callback is my_callback

    def test_stored_callback_is_callable(self) -> None:
        adapter = _MinimalAdapter()

        async def logger(event: ChannelEvent) -> None:
            pass

        adapter.on_channel_event(logger)

        assert callable(adapter._channel_event_callback)

    def test_callback_can_be_replaced(self) -> None:
        """Registering a second callback overwrites the first."""
        adapter = _MinimalAdapter()

        async def first(event: ChannelEvent) -> None:
            pass

        async def second(event: ChannelEvent) -> None:
            pass

        adapter.on_channel_event(first)
        adapter.on_channel_event(second)

        assert adapter._channel_event_callback is second

    def test_callback_not_shared_between_instances(self) -> None:
        """Each adapter instance has its own callback slot."""
        adapter_a = _MinimalAdapter()
        adapter_b = _MinimalAdapter()

        async def handler(event: ChannelEvent) -> None:
            pass

        adapter_a.on_channel_event(handler)

        assert adapter_a._channel_event_callback is handler
        assert getattr(adapter_b, "_channel_event_callback", None) is None

    @pytest.mark.asyncio
    async def test_stored_callback_is_invocable(self) -> None:
        """The stored callback can actually be called with a ChannelEvent."""
        adapter = _MinimalAdapter()
        received_events: list[ChannelEvent] = []

        async def capture(event: ChannelEvent) -> None:
            received_events.append(event)

        adapter.on_channel_event(capture)

        event = ChannelEvent(
            timestamp=datetime(2026, 3, 7, 14, 0, 0, tzinfo=UTC),
            channel_name="minimal",
            channel_id="42",
            channel_label="general",
            server_name="Test Server",
            server_id="1",
            user_id="100",
            display_name="Alice",
            content="hello",
        )

        assert adapter._channel_event_callback is not None
        await adapter._channel_event_callback(event)

        assert len(received_events) == 1
        assert received_events[0].content == "hello"


# ---------------------------------------------------------------------------
# fetch_channel_history — subclass override
# ---------------------------------------------------------------------------


class TestFetchChannelHistoryOverride:
    """A concrete subclass can override fetch_channel_history() with real logic."""

    @pytest.mark.asyncio
    async def test_override_returns_entries(self) -> None:
        adapter = _OverridingAdapter()

        result = await adapter.fetch_channel_history("ch-99")

        assert len(result) == 1
        assert result[0].display_name == "TestUser"
        assert result[0].content == "message from ch-99"

    @pytest.mark.asyncio
    async def test_override_result_contains_channel_history_entries(self) -> None:
        adapter = _OverridingAdapter()

        result = await adapter.fetch_channel_history("ch-1")

        assert all(isinstance(entry, ChannelHistoryEntry) for entry in result)

    @pytest.mark.asyncio
    async def test_base_class_adapter_still_returns_empty(self) -> None:
        """Override on subclass does not affect base-class instances."""
        base_adapter = _MinimalAdapter()
        overriding_adapter = _OverridingAdapter()

        base_result = await base_adapter.fetch_channel_history("ch-1")
        overriding_result = await overriding_adapter.fetch_channel_history("ch-1")

        assert base_result == []
        assert len(overriding_result) == 1
