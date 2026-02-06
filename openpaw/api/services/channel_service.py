"""Business logic for channel management."""

import json
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from openpaw.api.services.encryption import EncryptionService
from openpaw.db.repositories.channel_repo import ChannelRepository
from openpaw.db.repositories.workspace_repo import WorkspaceRepository


class ChannelService:
    """Business logic for channel management.

    Manages channel bindings, configuration, and connection testing.
    Integrates with database repositories and encryption service.
    """

    def __init__(
        self,
        session: AsyncSession,
        encryption: EncryptionService | None = None,
        orchestrator: Any | None = None,
    ):
        """Initialize channel service.

        Args:
            session: SQLAlchemy async session
            encryption: Encryption service for tokens (creates default if None)
            orchestrator: Optional orchestrator for runtime status
        """
        self.session = session
        self.encryption = encryption or EncryptionService()
        self.orchestrator = orchestrator
        self.channel_repo = ChannelRepository(session)
        self.workspace_repo = WorkspaceRepository(session)

    # =========================================================================
    # Channel Types
    # =========================================================================

    async def list_types(self) -> list[dict[str, Any]]:
        """List supported channel types.

        Returns:
            List of channel type dictionaries with metadata.
            Each includes: name, description, config_schema, status.
        """
        return [
            {
                "name": "telegram",
                "description": "Telegram bot integration with message routing and voice support",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "string",
                            "description": "Telegram bot token from @BotFather",
                        },
                        "allowed_users": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "List of allowed Telegram user IDs",
                        },
                        "allowed_groups": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "List of allowed Telegram group IDs",
                        },
                        "allow_all": {
                            "type": "boolean",
                            "description": "Allow all users/groups (use with caution)",
                        },
                    },
                    "required": ["token"],
                },
                "status": "active",
            },
            {
                "name": "discord",
                "description": "Discord bot integration (planned)",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "string",
                            "description": "Discord bot token",
                        },
                    },
                    "required": ["token"],
                },
                "status": "planned",
            },
            {
                "name": "slack",
                "description": "Slack bot integration (planned)",
                "config_schema": {
                    "type": "object",
                    "properties": {
                        "token": {
                            "type": "string",
                            "description": "Slack bot token",
                        },
                    },
                    "required": ["token"],
                },
                "status": "planned",
            },
        ]

    # =========================================================================
    # Channel Configuration
    # =========================================================================

    async def get_config(self, workspace: str) -> dict[str, Any] | None:
        """Get channel configuration for a workspace.

        Args:
            workspace: Workspace name

        Returns:
            Configuration dictionary or None if no channel configured.
            Contains: workspace, type, enabled, allowed_users, allowed_groups,
            allow_all, status (if orchestrator available).
            Never includes token value.
        """
        binding = await self.channel_repo.get_by_workspace(workspace)
        if not binding:
            return None

        result = {
            "workspace": workspace,
            "type": binding.channel_type,
            "enabled": binding.enabled,
            "allowed_users": binding.allowed_users or [],
            "allowed_groups": binding.allowed_groups or [],
            "allow_all": binding.allow_all,
        }

        # Add runtime status if orchestrator available
        if self.orchestrator:
            try:
                runner = self.orchestrator.runners.get(workspace)
                if runner and hasattr(runner, "channel"):
                    result["status"] = {
                        "running": True,
                        "connected": getattr(runner.channel, "is_connected", False),
                    }
                else:
                    result["status"] = {"running": False}
            except Exception:
                result["status"] = None

        return result

    async def update_config(
        self,
        workspace: str,
        channel_type: str | None = None,
        token: str | None = None,
        allowed_users: list[int] | None = None,
        allowed_groups: list[int] | None = None,
        allow_all: bool | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Update channel configuration for a workspace.

        Args:
            workspace: Workspace name
            channel_type: Channel type (e.g., "telegram")
            token: Channel authentication token (will be encrypted)
            allowed_users: List of allowed user IDs
            allowed_groups: List of allowed group IDs
            allow_all: Whether to allow all users/groups
            enabled: Whether the channel is enabled

        Returns:
            Updated configuration dictionary

        Raises:
            ValueError: If workspace not found or invalid channel type
        """
        # Get workspace
        workspace_obj = await self.workspace_repo.get_by_name(workspace)
        if not workspace_obj:
            raise ValueError(f"Workspace '{workspace}' not found")

        # Get existing binding or prepare for new one
        binding = await self.channel_repo.get_by_workspace(workspace)

        # Determine final channel type
        final_channel_type = channel_type or (binding.channel_type if binding else None)
        if not final_channel_type:
            raise ValueError("Channel type must be provided for new channel binding")

        # Validate channel type
        supported_types = [t["name"] for t in await self.list_types()]
        if final_channel_type not in supported_types:
            raise ValueError(
                f"Invalid channel type '{final_channel_type}'. "
                f"Supported types: {', '.join(supported_types)}"
            )

        # Prepare encrypted config
        if token:
            config_encrypted = self.encryption.encrypt(json.dumps({"token": token}))
        elif binding:
            config_encrypted = binding.config_encrypted
        else:
            raise ValueError("Token must be provided for new channel binding")

        # Determine final values (use existing if not provided)
        final_allowed_users = allowed_users
        final_allowed_groups = allowed_groups
        final_allow_all = allow_all if allow_all is not None else (binding.allow_all if binding else False)
        final_enabled = enabled if enabled is not None else (binding.enabled if binding else True)

        # Update or create binding
        await self.channel_repo.create_or_update(
            workspace_id=workspace_obj.id,
            channel_type=final_channel_type,
            config_encrypted=config_encrypted,
            allowed_users=final_allowed_users,
            allowed_groups=final_allowed_groups,
            allow_all=final_allow_all,
            enabled=final_enabled,
        )

        await self.session.commit()

        # TODO: Trigger workspace restart if orchestrator available and workspace running
        # This would allow live config updates without manual restart

        # Return updated config
        return await self.get_config(workspace) or {}

    # =========================================================================
    # Channel Testing
    # =========================================================================

    async def test_connection(self, workspace: str) -> dict[str, Any]:
        """Test channel connection for a workspace.

        Currently supports testing Telegram bot tokens via Telegram API.

        Args:
            workspace: Workspace name

        Returns:
            Test result dictionary with status and bot_info.
            Status is "success" or "failed".
            bot_info contains username, id, and other bot details.

        Raises:
            ValueError: If workspace or channel not found
            RuntimeError: If channel type not supported for testing or connection failed
        """
        binding = await self.channel_repo.get_by_workspace(workspace)
        if not binding:
            raise ValueError(f"No channel configured for workspace '{workspace}'")

        # Decrypt token
        config = json.loads(self.encryption.decrypt(binding.config_encrypted))
        token = config.get("token")
        if not token:
            raise RuntimeError("Channel configuration missing token")

        # Test based on channel type
        if binding.channel_type == "telegram":
            return await self._test_telegram(token)
        else:
            raise RuntimeError(
                f"Connection testing not yet supported for '{binding.channel_type}' channels"
            )

    async def _test_telegram(self, token: str) -> dict[str, Any]:
        """Test Telegram bot token by calling getMe API.

        Args:
            token: Telegram bot token

        Returns:
            Test result with status and bot_info

        Raises:
            RuntimeError: If API call fails
        """
        url = f"https://api.telegram.org/bot{token}/getMe"

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()

                if not data.get("ok"):
                    raise RuntimeError(
                        f"Telegram API error: {data.get('description', 'Unknown error')}"
                    )

                bot_info = data.get("result", {})
                return {
                    "status": "success",
                    "bot_info": {
                        "id": bot_info.get("id"),
                        "username": bot_info.get("username"),
                        "first_name": bot_info.get("first_name"),
                        "can_join_groups": bot_info.get("can_join_groups"),
                        "can_read_all_group_messages": bot_info.get(
                            "can_read_all_group_messages"
                        ),
                        "supports_inline_queries": bot_info.get("supports_inline_queries"),
                    },
                }
            except httpx.HTTPStatusError as e:
                raise RuntimeError(f"Telegram API HTTP error: {e.response.status_code}")
            except httpx.RequestError as e:
                raise RuntimeError(f"Telegram API request failed: {str(e)}")
            except Exception as e:
                raise RuntimeError(f"Telegram test failed: {str(e)}")
