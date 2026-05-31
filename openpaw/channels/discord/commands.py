"""Discord slash command registration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import discord
from discord import app_commands

from openpaw.model.message import Message, MessageDirection

logger = logging.getLogger(__name__)


class DiscordCommandRegistrar:
    """Register OpenPaw framework commands as Discord slash commands."""

    def __init__(
        self,
        client: discord.Client,
        tree: app_commands.CommandTree,
        channel_name: str,
        workspace_name: str,
        message_callback: Any,
        build_session_key: Any,
    ) -> None:
        self._client = client
        self._tree = tree
        self._channel_name = channel_name
        self._workspace_name = workspace_name
        self._message_callback = message_callback
        self._build_session_key = build_session_key

    async def register(self, commands: list[Any]) -> None:
        """Register OpenPaw commands as Discord slash commands.

        Each CommandDefinition from the framework command system becomes a
        Discord slash command. When invoked, the interaction is deferred
        immediately (agents may take time to respond) and the handler creates
        a synthetic Message routed through the message callback.

        Args:
            commands: List of CommandDefinition objects from CommandRouter.
        """
        for command_def in commands:
            # Skip commands that are hidden or internal-only
            if getattr(command_def, "hidden", False):
                continue

            # Capture in closure for the async handler below
            cmd_name: str = command_def.name
            cmd_description: str = getattr(command_def, "description", f"/{cmd_name}")

            # discord.py slash commands require a description <= 100 chars
            if len(cmd_description) > 100:
                cmd_description = cmd_description[:97] + "..."

            async def _slash_handler(
                interaction: discord.Interaction,
                args: str = "",
                *,
                _cmd_name: str = cmd_name,
            ) -> None:
                await interaction.response.defer()

                content = f"/{_cmd_name}"
                if args:
                    content = f"{content} {args}"

                message = Message(
                    id=str(interaction.id),
                    channel=self._channel_name,
                    session_key=self._build_session_key(interaction.channel_id),
                    user_id=str(interaction.user.id),
                    content=content,
                    direction=MessageDirection.INBOUND,
                    timestamp=datetime.now(UTC),
                    metadata={
                        "guild_id": interaction.guild_id,
                        "username": interaction.user.name,
                        "display_name": interaction.user.display_name,
                    },
                )

                if self._message_callback:
                    await self._message_callback(message)

                # Delete the deferred "thinking..." message
                try:
                    await interaction.delete_original_response()
                except discord.HTTPException:
                    logger.debug("Failed to delete deferred interaction response", exc_info=True)

            slash_cmd: app_commands.Command[Any, Any, Any] = app_commands.Command(
                name=cmd_name,
                description=cmd_description,
                callback=_slash_handler,
            )
            self._tree.add_command(slash_cmd)

        try:
            await self._tree.sync()
            logger.info(
                "Synced %d Discord slash commands for workspace '%s'",
                len(commands),
                self._workspace_name,
            )
        except discord.HTTPException as e:
            logger.error("Failed to sync Discord slash commands: %s", e)
