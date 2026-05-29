"""Browser tool creation and async browsing logic for channel history."""

import asyncio
import contextvars
import logging
from typing import Any

from langchain_core.tools import StructuredTool

from .formatter import (
    _OUTPUT_CAP,
    _OVER_FETCH_CAP,
    _OVER_FETCH_RATIO,
    _build_filter_qualifier,
    _format_history_output,
)
from .models import BrowseChannelHistoryInput
from .resolver import _resolve_adapter, _resolve_channel_id

logger = logging.getLogger(__name__)


def _create_browse_tool(builtin: Any) -> StructuredTool:
    """Create the browse_channel_history StructuredTool."""

    def browse_sync(
        channel: str | None = None,
        limit: int = 50,
        before: str | None = None,
        keyword: str | None = None,
        user: str | None = None,
        include_bots: bool = False,
    ) -> str:
        """Sync wrapper — delegates to the async implementation via run_coroutine.

        Used by LangChain when the tool is called in a non-async context.
        """
        try:
            asyncio.get_running_loop()
            import concurrent.futures

            ctx = contextvars.copy_context()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    ctx.run,
                    asyncio.run,
                    _browse_async(channel, limit, before, keyword, user, include_bots),
                )
                return future.result()
        except RuntimeError:
            return asyncio.run(
                _browse_async(channel, limit, before, keyword, user, include_bots)
            )

    async def _browse_async(
        channel: str | None,
        limit: int,
        before: str | None,
        keyword: str | None,
        user: str | None,
        include_bots: bool,
    ) -> str:
        """Fetch and format channel history with optional filtering."""
        if builtin._channels is None:
            return "[Error: Channel history tool not connected to any channels]"

        if not builtin._channels:
            return "[Error: No history-capable channels available in this workspace]"

        # Resolve which channel adapter to use
        adapter, error = _resolve_adapter(builtin._channels, channel)
        if error:
            return error
        if adapter is None:
            return "[Error: Failed to resolve channel adapter]"

        # Determine the platform channel ID from session context
        channel_id, id_error = _resolve_channel_id(adapter)
        if id_error:
            return id_error

        # Clamp limit to configured max
        effective_limit = min(limit, builtin.max_messages_per_request)

        # Over-fetch when text filters are active so we have enough after filtering.
        # Bot exclusion is intentionally excluded from this check: bots are
        # typically a small fraction of messages, so the 3x multiplier is not
        # warranted on every default call where include_bots=False.
        has_filters = bool(keyword or user)
        fetch_limit = (
            min(effective_limit * _OVER_FETCH_RATIO, _OVER_FETCH_CAP)
            if has_filters
            else effective_limit
        )

        try:
            entries = await adapter.fetch_channel_history(
                channel_id=channel_id,
                limit=fetch_limit,
                before_message_id=before,
            )
        except Exception as exc:
            logger.warning("fetch_channel_history failed: %s", exc, exc_info=True)
            return (
                "[No messages retrieved. The bot may lack permission to read "
                "history in this channel.]"
            )

        if not entries:
            return "[No messages found in channel history]"

        # Apply client-side filters
        filtered = entries
        if not include_bots:
            filtered = [e for e in filtered if not e.is_bot]
        if keyword:
            kw = keyword.lower()
            filtered = [e for e in filtered if kw in e.content.lower()]
        if user:
            usr = user.lower()
            filtered = [e for e in filtered if usr in e.display_name.lower()]

        if not filtered:
            qualifier = _build_filter_qualifier(keyword, user, include_bots)
            return f"[No messages found matching filters in #{adapter.name}{qualifier}]"

        # Truncate to the requested limit after filtering
        matched_count = len(filtered)
        results = filtered[:effective_limit]

        # Use the adapter's name as the canonical channel identifier now that
        # it is fully resolved — avoids re-indexing self._channels.
        resolved_channel_name = adapter.name
        output = _format_history_output(
            entries=results,
            channel_name=resolved_channel_name,
            adapter_type=adapter.name,
            requested_limit=effective_limit,
            matched_count=matched_count,
            before_cursor=before,
            content_truncation=builtin.content_truncation,
        )

        # Total output cap
        if len(output) > _OUTPUT_CAP:
            output = output[:_OUTPUT_CAP]
            output += (
                "\n[Output truncated at 50K characters. "
                "Use pagination or narrower filters.]"
            )

        return output

    async def browse_async(
        channel: str | None = None,
        limit: int = 50,
        before: str | None = None,
        keyword: str | None = None,
        user: str | None = None,
        include_bots: bool = False,
    ) -> str:
        """Browse channel message history with optional filtering.

        Args:
            channel: Channel name to query. Auto-selected when only one
                history-capable channel exists.
            limit: Maximum messages to return (1-100).
            before: Pagination cursor — message ID from previous call's footer.
            keyword: Case-insensitive substring filter on content.
            user: Filter by display name substring (case-insensitive).
            include_bots: Include bot messages (default: excluded).

        Returns:
            Formatted history output with timestamps, user IDs, and
            a pagination footer. Error string on failure.
        """
        return await _browse_async(channel, limit, before, keyword, user, include_bots)

    return StructuredTool.from_function(
        func=browse_sync,
        coroutine=browse_async,
        name="browse_channel_history",
        description=(
            "Browse message history from a channel (e.g., Discord). "
            "Supports pagination via the 'before' cursor, keyword and user filtering, "
            "and bot message exclusion. Use this to access messages beyond the "
            "initial context window or to search what was discussed in the past."
        ),
        args_schema=BrowseChannelHistoryInput,
    )
