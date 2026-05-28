"""Security mixin for channel adapters.

Provides allowlist enforcement and activation filtering (mention/trigger)
that is shared across all channel adapters. Concrete adapters extract
platform-specific primitives and delegate to these generic helpers.

Usage::

    class MyChannel(ChannelAdapter, SecurityMixin):
        def _is_allowed(self, message: PlatformMessage) -> bool:
            user_id = message.author.id
            group_id = message.guild.id if message.guild else None
            return self._check_user_allowed(user_id, group_id)

Expected instance attributes (set by the adapter's __init__):
    allowed_users: set[int]
    allowed_groups: set[int]
    allow_all: bool
    mention_required: bool
    triggers: list[str]
    workspace_name: str
"""

from openpaw.channels.helpers.formatting import format_unauthorized_response


class SecurityMixin:
    """Allowlist and activation filtering mixin for channel adapters.

    Both Discord and Telegram (and future adapters) need the same security
    model: allowlist checking, group allowlist, mention/trigger activation
    filtering, and unauthorized-response formatting. This mixin extracts the
    shared logic so it can be unit-tested once and reused everywhere.
    """

    # Type annotations for expected instance attributes (set by adapters)
    allowed_users: set[int]
    allowed_groups: set[int]
    allow_all: bool
    mention_required: bool
    triggers: list[str]
    workspace_name: str

    # --- Allowlist enforcement ---

    def _check_user_allowed(self, user_id: int, group_id: int | None = None) -> bool:
        """Check whether a user is permitted to use this workspace.

        Security model:
        - allow_all=True → everyone is allowed (insecure, use with caution)
        - group_id provided and in allowed_groups → allowed (any member)
        - allowed_users non-empty → user_id must be in the set
        - No allowlists match → deny (secure default)

        Args:
            user_id: The platform-specific user ID.
            group_id: Optional group/guild/chat ID. If provided and in
                allowed_groups, the user is permitted regardless of
                allowed_users.

        Returns:
            True if the user is allowed, False otherwise.
        """
        if self.allow_all:
            return True

        # Group allowlist: if the user is in an allowed group, permit them
        # without requiring individual allowlisting.
        if group_id is not None and self.allowed_groups:
            if group_id in self.allowed_groups:
                return True

        # User allowlist check (applies to DMs and non-allowed groups)
        if self.allowed_users:
            return user_id in self.allowed_users

        # No allowlists matched — deny
        return False

    # --- Activation filtering ---

    def _check_activation(
        self,
        content: str,
        is_dm: bool,
        is_command: bool,
        is_mentioned: bool,
    ) -> bool:
        """Check whether a message passes activation filters (mention OR trigger).

        In group channels, messages must pass at least one activation condition:
        - Bot is @mentioned (when mention_required is True)
        - Message contains a trigger keyword (when triggers are configured)

        If neither mention_required nor triggers are configured, all messages pass.
        DMs and commands always pass through regardless.

        Args:
            content: The message text content.
            is_dm: True if the message is from a DM/private chat.
            is_command: True if the message is a framework command (e.g., starts with "/").
            is_mentioned: True if the bot is @mentioned in the message.

        Returns:
            True if the message should be processed.
        """
        # No activation filters configured — pass everything
        if not self.mention_required and not self.triggers:
            return True

        # DMs and commands always pass through
        if is_dm or is_command:
            return True

        # OR logic: either mention or trigger is sufficient
        if self.mention_required and is_mentioned:
            return True

        if self.triggers and self._passes_trigger_filter(content, self.triggers):
            return True

        return False

    # --- Unauthorized response formatting ---

    def _build_unauthorized_text(
        self, user_id: int, group_id: int | None = None
    ) -> str:
        """Build the standard access-denied message text.

        Args:
            user_id: The blocked user's platform ID.
            group_id: Optional group/server ID to include.

        Returns:
            Formatted access-denied message text.
        """
        return format_unauthorized_response(
            user_id, self.workspace_name, group_id
        )
