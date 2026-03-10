"""Channel history browsing builtin tool.

Allows agents to browse and search message history from history-capable
channel adapters (e.g., Discord). Supports pagination, keyword filtering,
user filtering, and bot message exclusion.
"""

import logging
from datetime import UTC
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools._channel_context import get_current_session_key
from openpaw.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)

# Per-message content truncation (consistent with format_channel_context)
_MESSAGE_TRUNCATION = 500

# Total output cap (consistent with read_file safety valve)
_OUTPUT_CAP = 50_000

# Over-fetch multiplier when filters are active
_OVER_FETCH_RATIO = 3

# Hard cap on adapter fetch when filters are active
_OVER_FETCH_CAP = 300


class BrowseChannelHistoryInput(BaseModel):
    """Input schema for browse_channel_history."""

    channel: str | None = Field(
        default=None,
        description=(
            "Channel name to query (e.g., 'discord', 'discord-work'). "
            "Required when multiple history-capable channels exist. "
            "Auto-selected when only one exists."
        ),
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of messages to return (1-100).",
    )
    before: str | None = Field(
        default=None,
        description=(
            "Pagination cursor — message ID. Fetches messages sent before this "
            "message. Use the oldest_message_id from a previous call's footer."
        ),
    )
    keyword: str | None = Field(
        default=None,
        description="Case-insensitive substring filter on message content.",
    )
    user: str | None = Field(
        default=None,
        description="Filter by display name (case-insensitive substring match).",
    )
    include_bots: bool = Field(
        default=False,
        description="Include bot messages in results (default: excluded).",
    )


class ChannelHistoryToolBuiltin(BaseBuiltinTool):
    """On-demand channel history browser for history-capable adapters.

    Enables agents to browse message history beyond the initial context
    window, paginate through older messages, and filter by keyword or user.

    Capabilities:
    - Paginate through channel history (newest to oldest)
    - Filter by keyword (case-insensitive substring)
    - Filter by user (case-insensitive display name substring)
    - Exclude bot messages (default on)
    - Auto-select the channel when only one supports history

    Config options:
        max_messages_per_request: Hard cap on messages returned (default: 100)
        content_truncation: Per-message content char limit (default: 500)

    Wired at startup via set_channels(). If no channel supports history
    browsing, the tool is removed from the agent by WorkspaceRunner.
    """

    metadata = BuiltinMetadata(
        name="channel_history",
        display_name="Channel History Browser",
        description="Browse and search message history from history-capable channel adapters",
        builtin_type=BuiltinType.TOOL,
        group="communication",
        prerequisites=BuiltinPrerequisite(),  # Runtime gating, not API-key gating
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the channel history tool.

        Args:
            config: Optional configuration dict containing:
                - max_messages_per_request: Hard cap on messages (default: 100)
                - content_truncation: Per-message char limit (default: 500)
        """
        super().__init__(config)

        self.max_messages_per_request: int = self.config.get("max_messages_per_request", 100)
        self.content_truncation: int = self.config.get("content_truncation", _MESSAGE_TRUNCATION)

        # Channel adapters — set via set_channels() at workspace startup
        self._channels: dict[str, ChannelAdapter] | None = None

        logger.debug("ChannelHistoryToolBuiltin initialized")

    def set_channels(self, channels: dict[str, "ChannelAdapter"]) -> None:
        """Set the history-capable channel adapter references.

        Called by WorkspaceRunner after channels are set up. Only channels
        with supports_history_browsing == True should be passed.

        Args:
            channels: Dict mapping channel name -> ChannelAdapter for
                history-capable channels only.
        """
        self._channels = channels
        logger.info(
            "ChannelHistoryTool connected to %d channel(s): %s",
            len(channels),
            list(channels.keys()),
        )

    def get_langchain_tool(self) -> Any:
        """Return the browse_channel_history tool as a list."""
        return [self._create_browse_tool()]

    def _create_browse_tool(self) -> StructuredTool:
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
            import asyncio
            import contextvars

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
            if self._channels is None:
                return "[Error: Channel history tool not connected to any channels]"

            if not self._channels:
                return "[Error: No history-capable channels available in this workspace]"

            # Resolve which channel adapter to use
            adapter, error = _resolve_adapter(self._channels, channel)
            if error:
                return error
            if adapter is None:
                return "[Error: Failed to resolve channel adapter]"

            # Determine the platform channel ID from session context
            channel_id, id_error = _resolve_channel_id(adapter)
            if id_error:
                return id_error

            # Clamp limit to configured max
            effective_limit = min(limit, self.max_messages_per_request)

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
                content_truncation=self.content_truncation,
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


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_adapter(
    channels: dict[str, "ChannelAdapter"],
    channel_name: str | None,
) -> tuple["ChannelAdapter | None", str | None]:
    """Resolve which adapter to use.

    Args:
        channels: Available history-capable channels.
        channel_name: Requested channel name, or None for auto-selection.

    Returns:
        Tuple of (adapter, error_string). One of the two will be None.
    """
    if channel_name is not None:
        adapter = channels.get(channel_name)
        if adapter is None:
            available = ", ".join(sorted(channels.keys()))
            return None, (
                f"[Error: Channel '{channel_name}' not found or does not support "
                f"history browsing. Available: {available}]"
            )
        return adapter, None

    # Auto-selection: only works when exactly one history-capable channel exists
    if len(channels) == 1:
        return next(iter(channels.values())), None

    available = ", ".join(sorted(channels.keys()))
    return None, (
        f"[Error: Multiple history-capable channels available. "
        f"Specify channel= with one of: {available}]"
    )


def _resolve_channel_id(adapter: "ChannelAdapter") -> tuple[str, str | None]:
    """Resolve the platform channel ID from context or return an error.

    Uses the current session key from _channel_context contextvars to extract
    the channel ID. Fails gracefully when running outside a user session (e.g.,
    from a cron job without a channel context).

    Args:
        adapter: The selected channel adapter.

    Returns:
        Tuple of (channel_id, error_string). One will be None.
    """
    session_key = get_current_session_key()
    if not session_key:
        return "", (
            "[Error: No active session context. "
            "Cannot determine which channel to browse. "
            "This tool must be called from within a channel session.]"
        )

    # Session key format: "{channel_name}:{channel_id}"
    # channel_name can contain colons (e.g., "discord-work"), but channel_id
    # is always the last segment.
    parts = session_key.rsplit(":", 1)
    if len(parts) != 2 or not parts[1]:
        return "", (
            f"[Error: Unable to extract channel ID from session key '{session_key}'. "
            f"Provide the channel_id explicitly or ensure you are in a guild channel.]"
        )

    channel_id = parts[1]

    # Detect DMs: Discord DM session keys use the user ID as channel_id,
    # but we can't tell without platform context. We surface an informative
    # message if the fetch returns empty (handled in the caller).
    return channel_id, None


def _build_filter_qualifier(
    keyword: str | None,
    user: str | None,
    include_bots: bool,
) -> str:
    """Build a human-readable description of active filters for no-result messages.

    Args:
        keyword: Active keyword filter, or None.
        user: Active user filter, or None.
        include_bots: Whether bot messages are included.

    Returns:
        Qualifier string like " (keyword='deploy', user='Alice')" or "".
    """
    parts = []
    if keyword:
        parts.append(f"keyword='{keyword}'")
    if user:
        parts.append(f"user='{user}'")
    if not include_bots:
        parts.append("bots excluded")
    return f" ({', '.join(parts)})" if parts else ""


def _format_history_output(
    entries: list[Any],
    channel_name: str,
    adapter_type: str,
    requested_limit: int,
    matched_count: int,
    before_cursor: str | None,
    content_truncation: int,
) -> str:
    """Format channel history entries as readable text.

    Args:
        entries: ChannelHistoryEntry list (already filtered and truncated to limit).
        channel_name: Human-readable channel name for the header.
        adapter_type: Platform type string (e.g., "discord") for the header.
        requested_limit: The limit the agent requested.
        matched_count: Total matched entries before truncation to limit.
        before_cursor: The 'before' cursor used in this request, for header display.
        content_truncation: Per-message character truncation limit.

    Returns:
        Formatted multi-line string suitable for agent consumption.
    """
    lines: list[str] = []

    # Header
    count = len(entries)
    lines.append(
        f"[Channel History: #{channel_name} ({adapter_type}) — {count} message(s), oldest first]"
    )
    if before_cursor:
        lines.append(f"[Showing messages before ID: {before_cursor}]")
    lines.append("")

    # Message lines
    for entry in entries:
        timestamp_str = _format_timestamp(entry.timestamp)
        content = entry.content
        if len(content) > content_truncation:
            content = content[:content_truncation] + "..."

        suffix = ""
        if entry.attachments_summary:
            suffix = f" {entry.attachments_summary}"

        lines.append(
            f"[{timestamp_str}] {entry.display_name} (id:{entry.user_id}): {content}{suffix}"
        )

    # Pagination footer
    lines.append("")
    if entries:
        oldest_id = entries[0].message_id
        if oldest_id:
            lines.append(
                f"[Pagination: oldest_message_id={oldest_id} — "
                f"use before=\"{oldest_id}\" to load older messages]"
            )

    if matched_count > requested_limit:
        lines.append(
            f"[Showing {requested_limit} of {matched_count} matched — "
            f"use before= to continue paging]"
        )
    elif count == requested_limit:
        lines.append(
            f"[Showing {count} of {requested_limit} requested — more history may be available]"
        )

    return "\n".join(lines)


def _format_timestamp(ts: Any) -> str:
    """Format a datetime to a consistent UTC string for agent output.

    Args:
        ts: datetime object (naive or timezone-aware).

    Returns:
        Formatted string like "2026-03-08 14:30 UTC".
    """
    try:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        utc_ts = ts.astimezone(UTC)
        return utc_ts.strftime("%Y-%m-%d %H:%M UTC")  # type: ignore[no-any-return]
    except Exception:
        return str(ts)
