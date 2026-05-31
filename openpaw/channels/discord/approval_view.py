"""Discord UI view for approval gate requests."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

import discord

logger = logging.getLogger(__name__)


class DiscordApprovalView(discord.ui.View):
    """Discord UI view for approval gate requests.

    Renders Approve / Deny buttons. On interaction the stored callback is
    invoked and the view is disabled so buttons cannot be pressed twice.
    """

    def __init__(
        self,
        approval_id: str,
        callback: Callable[[str, bool], Coroutine[Any, Any, None]],
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._approval_id = approval_id
        self._callback = callback

    async def _resolve(self, interaction: discord.Interaction, approved: bool) -> None:
        """Disable buttons and invoke the approval callback."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        result_label = "Approved" if approved else "Denied"
        try:
            await interaction.response.edit_message(
                content=f"{interaction.message.content}\n\nResult: {result_label}",  # type: ignore[union-attr]
                view=self,
            )
        except Exception:
            logger.debug("Failed to update approval message after resolution", exc_info=True)

        await self._callback(self._approval_id, approved)
        self.stop()

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        """Handle approve button press."""
        await self._resolve(interaction, approved=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        """Handle deny button press."""
        await self._resolve(interaction, approved=False)

    async def on_timeout(self) -> None:
        """Disable buttons when the view times out."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        self.stop()
