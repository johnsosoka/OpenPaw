"""Slack channel adapter using slack_bolt and Socket Mode."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

import aiohttp
from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from openpaw.domain.message import Attachment, Message, MessageDirection

logger = logging.getLogger(__name__)


class SlackChannel:
    """Slack channel adapter.

    Handles:
    - Socket Mode connection for events
    - Message format conversion
    - User/channel allowlisting
    - File upload/download
    - Approval gates with Block Kit buttons
    """

    name = "slack"

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        signing_secret: str | None = None,
        allowed_users: list[str] | None = None,
        allowed_channels: list[str] | None = None,
        allow_all: bool = False,
        workspace_name: str = "unknown",
    ):
        """Initialize the Slack channel.

        Args:
            bot_token: Bot user OAuth token (xoxb-...).
            app_token: Socket Mode app token (xapp-...).
            signing_secret: Optional signing secret for request verification.
            allowed_users: List of allowed Slack user IDs.
            allowed_channels: List of allowed channel IDs (if empty, all channels allowed).
            allow_all: If True, allow all users (insecure). If False, requires allowlists.
            workspace_name: Name of the workspace (for error messages).
        """
        self.bot_token = bot_token
        self.app_token = app_token
        self.signing_secret = signing_secret
        self.allowed_users = set(allowed_users or [])
        self.allowed_channels = set(allowed_channels or [])
        self.allow_all = allow_all
        self.workspace_name = workspace_name

        self._app: AsyncApp | None = None
        self._handler: AsyncSocketModeHandler | None = None
        self._bot_user_id: str | None = None
        self._message_callback: Callable[[Message], Coroutine[Any, Any, None]] | None = None
        self._approval_callback: Callable[[str, bool], Coroutine[Any, Any, None]] | None = None
        self._user_cache: dict[str, dict[str, Any]] = {}
        self._user_cache_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the Slack bot via Socket Mode."""
        # Create Slack app
        self._app = AsyncApp(
            token=self.bot_token,
            signing_secret=self.signing_secret,
        )

        # Get bot's own user ID via auth.test
        try:
            auth_response = await self._app.client.auth_test()
            self._bot_user_id = auth_response["user_id"]
            logger.info(f"Slack bot authenticated as {self._bot_user_id}")
        except Exception as e:
            logger.error(f"Failed to authenticate Slack bot: {e}")
            raise RuntimeError(f"Slack auth.test failed: {e}") from e

        # Register message event listener
        self._app.event("message")(self._handle_message_event)

        # Register action handler for approval buttons
        self._app.action(re.compile(r"^(approve|deny):.*"))(self._handle_approval_action)

        # Start Socket Mode handler
        self._handler = AsyncSocketModeHandler(self._app, self.app_token)
        await self._handler.start_async()  # type: ignore[no-untyped-call]

        logger.info("Slack channel started via Socket Mode")

    async def stop(self) -> None:
        """Stop the Slack bot gracefully."""
        if self._handler:
            await self._handler.close_async()  # type: ignore[no-untyped-call]
            logger.info("Slack channel stopped")

    def on_message(self, callback: Callable[[Message], Coroutine[Any, Any, None]]) -> None:
        """Register callback for incoming messages."""
        self._message_callback = callback

    def on_approval(
        self, callback: Callable[[str, bool], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a callback for approval resolutions."""
        self._approval_callback = callback

    def build_session_key(self, *parts: str | int) -> str:
        """Build a session key from parts.

        Args:
            *parts: Components to join into a session key.

        Returns:
            Session key string like 'slack:C0ABC123'.
        """
        return f"{self.name}:" + ":".join(str(p) for p in parts)

    async def register_commands(self, commands: list[Any]) -> None:
        """Register available commands with Slack.

        No-op for now (Slack slash commands require app manifest changes).
        """
        pass

    # Slack message limit (conservative, actual limit is 40K)
    MAX_MESSAGE_LENGTH = 4000

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        """Send a message to a Slack channel.

        Automatically splits messages that exceed ~4000 chars,
        breaking at paragraph boundaries when possible.

        Args:
            session_key: Session key in format 'slack:channel_id'.
            content: Message text.
            **kwargs: Additional slack_sdk kwargs.

        Returns:
            The sent Message object (last chunk if split).
        """
        if not self._app:
            raise RuntimeError("Slack channel not started")

        # Parse channel_id from session_key
        parts = session_key.split(":")
        channel_id = parts[1]

        chunks = self._split_message(content)
        sent_ts = None

        for chunk in chunks:
            response = await self._app.client.chat_postMessage(
                channel=channel_id,
                text=chunk,
                **kwargs,
            )
            sent_ts = response["ts"]

        if not sent_ts:
            raise RuntimeError("Failed to send message: no chunks were sent")

        return Message(
            id=sent_ts,
            channel=self.name,
            session_key=session_key,
            user_id=self._bot_user_id or "bot",
            content=content,
            direction=MessageDirection.OUTBOUND,
            timestamp=datetime.now(),
        )

    def _split_message(self, text: str) -> list[str]:
        """Split text into chunks that fit Slack's practical message limit.

        Tries to break at paragraph boundaries (double newline), falls back
        to single newlines, then hard-splits as a last resort.

        Args:
            text: The full message text.

        Returns:
            List of message chunks, each within MAX_MESSAGE_LENGTH.
        """
        if len(text) <= self.MAX_MESSAGE_LENGTH:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= self.MAX_MESSAGE_LENGTH:
                chunks.append(remaining)
                break

            # Try to split at paragraph boundary
            split_at = remaining.rfind("\n\n", 0, self.MAX_MESSAGE_LENGTH)

            # Fall back to single newline
            if split_at == -1:
                split_at = remaining.rfind("\n", 0, self.MAX_MESSAGE_LENGTH)

            # Hard split as last resort
            if split_at == -1:
                split_at = self.MAX_MESSAGE_LENGTH

            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")

        return chunks

    async def send_file(
        self,
        session_key: str,
        file_data: bytes,
        filename: str,
        mime_type: str | None = None,
        caption: str | None = None,
    ) -> None:
        """Send a file via Slack's files.uploadV2 API.

        Args:
            session_key: Session key in format 'slack:channel_id'.
            file_data: Raw file bytes.
            filename: Display filename for the file.
            mime_type: Optional MIME type hint.
            caption: Optional caption/message to accompany the file.

        Raises:
            RuntimeError: If the channel is not started or upload fails.
        """
        if not self._app:
            raise RuntimeError("Slack channel not started")

        # Parse channel_id from session_key
        parts = session_key.split(":")
        channel_id = parts[1]

        try:
            await self._app.client.files_upload_v2(
                channel=channel_id,
                content=file_data,
                filename=filename,
                initial_comment=caption,
            )
            logger.info(f"Sent file '{filename}' ({len(file_data)} bytes) to channel {channel_id}")
        except Exception as e:
            logger.error(f"Failed to send file '{filename}' to channel {channel_id}: {e}")
            raise RuntimeError(f"Failed to send file: {e}") from e

    async def send_approval_request(
        self,
        session_key: str,
        approval_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        show_args: bool = True,
    ) -> None:
        """Send approval request with Slack Block Kit buttons.

        Args:
            session_key: Target session identifier.
            approval_id: Unique ID for this approval request.
            tool_name: Name of the tool requiring approval.
            tool_args: Arguments passed to the tool.
            show_args: Whether to display tool arguments to user.
        """
        if not self._app:
            raise RuntimeError("Slack channel not started")

        # Parse channel_id from session_key
        parts = session_key.split(":")
        channel_id = parts[1]

        # Build text block
        text = f"🔒 *Approval Required*\nTool: `{tool_name}`\n"
        if show_args and tool_args:
            args_str = str(tool_args)
            if len(args_str) > 500:
                args_str = args_str[:500] + "..."
            text += f"Args: `{args_str}`\n"

        # Build Block Kit blocks
        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text,
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve"},
                        "style": "primary",
                        "action_id": f"approve:{approval_id}",
                        "value": approval_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Deny"},
                        "style": "danger",
                        "action_id": f"deny:{approval_id}",
                        "value": approval_id,
                    },
                ],
            },
        ]

        try:
            await self._app.client.chat_postMessage(
                channel=channel_id,
                text=text,  # Fallback text
                blocks=blocks,
            )
        except Exception as e:
            logger.error(f"Failed to send approval request: {e}")
            raise

    async def _handle_message_event(self, event: dict[str, Any], say: Any) -> None:
        """Handle incoming message events from Slack.

        Filters:
        - Ignore bot's own messages
        - DMs (channel starts with 'D'): always process
        - Channels/Groups: only process if message contains @mention
        - Access control via _is_allowed
        """
        try:
            # Ignore bot's own messages
            if event.get("bot_id") or event.get("user") == self._bot_user_id:
                return

            # Ignore message subtypes we don't handle (edits, deletes, etc.)
            subtype = event.get("subtype")
            if subtype and subtype not in ("file_share",):
                return

            channel_id = event.get("channel")
            user_id = event.get("user")
            text = event.get("text", "")
            has_files = bool(event.get("files"))

            if not channel_id or not user_id:
                return

            # DMs: always process (DM channel IDs start with 'D' per Slack API spec)
            is_dm = channel_id.startswith("D")

            # Channels/Groups: only process if @mentioned
            is_mentioned = False
            if not is_dm and self._bot_user_id:
                mention_pattern = f"<@{self._bot_user_id}>"
                is_mentioned = mention_pattern in text
                # Strip the mention from the message text
                if is_mentioned:
                    text = text.replace(mention_pattern, "").strip()

            # Skip if not DM and not mentioned
            if not is_dm and not is_mentioned:
                return

            # Skip empty messages after mention stripping (unless it has files or specific subtype)
            if not text.strip() and not has_files and not subtype:
                logger.debug(f"Ignoring empty message after mention stripping (channel={channel_id})")
                return

            # Access control
            if not self._is_allowed(user_id, channel_id):
                await self._send_unauthorized_response(channel_id, user_id)
                return

            # Build Message object
            message = await self._event_to_message(event, text)
            if message and self._message_callback:
                await self._message_callback(message)

        except Exception as e:
            logger.error(f"Error handling Slack message event: {e}", exc_info=True)

    async def _event_to_message(self, event: dict[str, Any], text: str) -> Message | None:
        """Convert Slack event to unified Message format.

        Args:
            event: Slack message event payload.
            text: Message text (with @mention stripped).

        Returns:
            Message object or None if conversion fails.
        """
        channel_id = event.get("channel")
        user_id = event.get("user")
        ts = event.get("ts")

        if not channel_id or not user_id or not ts:
            return None

        session_key = self.build_session_key(channel_id)

        # Get user display name
        display_name = await self._get_user_display_name(user_id)

        # Determine chat type (DMs start with 'D' per Slack API spec)
        if channel_id.startswith("D"):
            chat_type = "im"
        elif channel_id.startswith("G"):
            chat_type = "group"
        else:
            chat_type = "channel"

        # Handle file attachments
        attachments: list[Attachment] = []
        failed_files: list[str] = []
        if "files" in event:
            for file_data in event["files"]:
                attachment = await self._download_file(file_data)
                if attachment:
                    attachments.append(attachment)
                else:
                    # Track failed downloads
                    file_name = file_data.get("name", "unknown")
                    failed_files.append(file_name)

        # Append failed file notification to message text
        if failed_files:
            failure_notice = f"\n\n[Failed to download {len(failed_files)} file(s): {', '.join(failed_files)}]"
            text = text + failure_notice

        # Convert timestamp (Slack ts is like "1234567890.123456")
        try:
            timestamp = datetime.fromtimestamp(float(ts))
        except (ValueError, TypeError):
            timestamp = datetime.now()

        return Message(
            id=ts,
            channel=self.name,
            session_key=session_key,
            user_id=user_id,
            content=text,
            direction=MessageDirection.INBOUND,
            timestamp=timestamp,
            metadata={
                "chat_type": chat_type,
                "first_name": display_name,
                "username": user_id,  # Slack uses user_id as identifier
            },
            attachments=attachments,
        )

    async def _download_file(self, file_data: dict[str, Any]) -> Attachment | None:
        """Download a file from Slack.

        Args:
            file_data: File metadata from Slack event.

        Returns:
            Attachment object or None if download fails.
        """
        file_id = file_data.get("id")
        url_private = file_data.get("url_private_download") or file_data.get("url_private")
        filename = file_data.get("name")
        mime_type = file_data.get("mimetype")
        file_size = file_data.get("size", 0)

        if not url_private:
            logger.warning(f"No download URL for file {file_id}")
            return None

        # Skip files over 50MB
        max_file_size = 50 * 1024 * 1024  # 50MB in bytes
        if file_size > max_file_size:
            logger.warning(f"Skipping file {filename} ({file_size} bytes) - exceeds 50MB limit")
            return None

        try:
            # Download file with bot token authorization (30-second timeout)
            headers = {"Authorization": f"Bearer {self.bot_token}"}
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url_private, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to download file {file_id}: HTTP {response.status}")
                        return None

                    file_bytes = await response.read()

            # Determine attachment type from MIME type
            attachment_type = "document"
            if mime_type:
                if mime_type.startswith("image/"):
                    attachment_type = "image"
                elif mime_type.startswith("audio/"):
                    attachment_type = "audio"
                elif mime_type.startswith("video/"):
                    attachment_type = "video"

            logger.info(f"Downloaded file: {filename} ({len(file_bytes)} bytes, {mime_type})")

            return Attachment(
                type=attachment_type,
                data=file_bytes,
                filename=filename,
                mime_type=mime_type,
                metadata={"file_id": file_id, "file_size": len(file_bytes)},
            )

        except Exception as e:
            logger.error(f"Failed to download file {file_id}: {e}", exc_info=True)
            return None

    def _is_allowed(self, user_id: str, channel_id: str) -> bool:
        """Check if the message sender is allowed.

        Security model:
        - If allow_all is True, all users are allowed (insecure)
        - If allowed_users is set, user must be in the list
        - If in a channel and allowed_channels is set, channel must be in the list
        - If neither allow_all nor allowlists are set, deny by default (secure)
        """
        # Explicit allow-all mode (use with caution)
        if self.allow_all:
            return True

        # Check user allowlist
        if self.allowed_users:
            if user_id not in self.allowed_users:
                return False
        else:
            # No user allowlist and not allow_all = deny
            return False

        # Check channel allowlist (if configured)
        if self.allowed_channels:
            # For channels/groups, verify channel is in allowlist
            if not channel_id.startswith("D"):  # Not a DM
                if channel_id not in self.allowed_channels:
                    return False

        return True

    async def _send_unauthorized_response(self, channel_id: str, user_id: str) -> None:
        """Send a helpful response to unauthorized users with their ID."""
        if not self._app:
            return

        message = (
            f"⛔ Access denied.\n\n"
            f"Your user ID: `{user_id}`\n"
            f"Channel ID: `{channel_id}`\n\n"
            f"To gain access, add your ID to the allowlist:\n"
            f"`agent_workspaces/{self.workspace_name}/agent.yaml`\n\n"
            f"```\n"
            f"channel:\n"
            f"  allowed_users:\n"
            f"    - {user_id}\n"
            f"```"
        )

        try:
            # Send ephemeral message (only visible to the user)
            await self._app.client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=message,
            )
            logger.warning(f"Blocked user {user_id} from workspace '{self.workspace_name}'")
        except Exception as e:
            logger.error(f"Failed to send unauthorized response: {e}")

    async def _get_user_display_name(self, user_id: str) -> str:
        """Get user display name from Slack API with caching.

        Args:
            user_id: Slack user ID.

        Returns:
            User's display name or real name, fallback to user_id.
        """
        # Check cache first (thread-safe read)
        async with self._user_cache_lock:
            if user_id in self._user_cache:
                user_info = self._user_cache[user_id]
                profile = user_info.get("profile", {})
                return profile.get("display_name") or profile.get("real_name") or user_id

        # Fetch from API (outside lock to avoid blocking)
        try:
            if not self._app:
                return user_id

            response = await self._app.client.users_info(user=user_id)
            user_info = response.get("user", {})

            # Update cache (thread-safe write)
            async with self._user_cache_lock:
                self._user_cache[user_id] = user_info

            profile = user_info.get("profile", {})
            display_name = profile.get("display_name") or profile.get("real_name") or user_id
            return display_name

        except Exception as e:
            logger.warning(f"Failed to fetch user info for {user_id}: {e}")
            return user_id

    async def _handle_approval_action(self, ack: Any, body: dict[str, Any]) -> None:
        """Handle Block Kit button presses for approval gates.

        Args:
            ack: Acknowledgement function.
            body: Action payload from Slack.
        """
        await ack()  # Acknowledge the button press immediately

        try:
            action = body["actions"][0]
            action_id = action["action_id"]

            # Parse action_id: "approve:approval_id" or "deny:approval_id"
            parts = action_id.split(":", 1)
            if len(parts) != 2:
                logger.warning(f"Invalid action_id format: {action_id}")
                return

            action_type, approval_id = parts
            approved = action_type == "approve"

            # Invoke the callback FIRST, before updating UI
            callback_success = True
            if self._approval_callback:
                try:
                    await self._approval_callback(approval_id, approved)
                except Exception as e:
                    logger.error(f"Approval callback failed: {e}", exc_info=True)
                    callback_success = False

            # Update the message UI based on callback result
            result_text = "✅ Approved" if approved else "❌ Denied"
            if not callback_success:
                result_text = "⚠️ Error processing approval"

            message = body.get("message", {})
            blocks = message.get("blocks", [])

            # Replace action buttons with result text
            if blocks:
                blocks[-1] = {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Result: {result_text}*",
                    },
                }

                if self._app:
                    await self._app.client.chat_update(
                        channel=body["channel"]["id"],
                        ts=message["ts"],
                        blocks=blocks,
                        text=message.get("text", ""),
                    )

        except Exception as e:
            logger.error(f"Error handling approval action: {e}", exc_info=True)
