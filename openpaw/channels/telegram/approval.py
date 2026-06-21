"""Telegram approval request sender."""

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from openpaw.channels.helpers import format_approval_message


class TelegramApprovalSender:
    """Send approval requests with Telegram inline keyboard."""

    def __init__(self, app: Any) -> None:
        self._app = app

    async def send_request(
        self,
        session_key: str,
        approval_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        show_args: bool = True,
    ) -> None:
        """Send approval request with Telegram inline keyboard."""
        chat_id = int(session_key.split(":")[1])

        text = format_approval_message(tool_name, tool_args, show_args)

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Approve", callback_data=f"approve:{approval_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ Deny", callback_data=f"deny:{approval_id}"
                    ),
                ]
            ]
        )

        await self._app.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
