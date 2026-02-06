"""Business logic for builtin management."""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openpaw.api.services.encryption import EncryptionService
from openpaw.builtins.registry import BuiltinRegistry
from openpaw.db.models import ApiKey, BuiltinAllowlist, BuiltinConfig


class BuiltinService:
    """Business logic for builtin management.

    Manages builtin tools/processors, API keys, and allow/deny lists.
    Integrates with BuiltinRegistry for metadata and database for configuration.
    """

    def __init__(
        self,
        session: AsyncSession,
        encryption: EncryptionService | None = None,
    ):
        self.session = session
        self.encryption = encryption or EncryptionService()
        self.registry = BuiltinRegistry.get_instance()

    # =========================================================================
    # Builtin Listing
    # =========================================================================

    async def list_registered(self) -> list[dict[str, Any]]:
        """List all registered builtins with availability status.

        Returns:
            List of builtin dictionaries with metadata and availability info.
            Each builtin includes: name, type, group, description, prerequisites,
            available, and enabled status.
        """
        all_builtins = self.registry.list_all()
        result = []

        for category in ["tools", "processors"]:
            for metadata in all_builtins.get(category, []):
                config = await self._get_config(metadata.name)
                result.append({
                    "name": metadata.name,
                    "type": category.rstrip("s"),  # "tools" -> "tool"
                    "group": metadata.group or "",
                    "description": metadata.description,
                    "prerequisites": {
                        "env_vars": metadata.prerequisites.env_vars,
                        "packages": metadata.prerequisites.packages,
                    },
                    "available": metadata.prerequisites.is_satisfied(),
                    "enabled": config.enabled if config else True,
                })

        return result

    async def list_available(self) -> list[dict[str, Any]]:
        """List only builtins with satisfied prerequisites.

        Returns:
            List of builtin dictionaries filtered to only available builtins.
        """
        all_builtins = await self.list_registered()
        return [b for b in all_builtins if b["available"]]

    async def get_config(self, name: str) -> dict[str, Any] | None:
        """Get builtin configuration.

        Args:
            name: Builtin name (e.g., "brave_search")

        Returns:
            Configuration dictionary or None if builtin not found.
            Contains: name, type, group, enabled, config.
        """
        # Find metadata from registry
        metadata = None
        builtin_type = "tool"

        tool_class = self.registry.get_tool_class(name)
        if tool_class:
            metadata = tool_class.metadata
        else:
            processor_class = self.registry.get_processor_class(name)
            if processor_class:
                metadata = processor_class.metadata
                builtin_type = "processor"

        if not metadata:
            return None

        config = await self._get_config(name)
        return {
            "name": name,
            "type": builtin_type,
            "group": metadata.group or "",
            "enabled": config.enabled if config else True,
            "config": config.config if config else {},
        }

    async def update_config(
        self, name: str, enabled: bool | None, config: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Update builtin configuration.

        Args:
            name: Builtin name
            enabled: Enable/disable the builtin (optional)
            config: Configuration dictionary (optional)

        Returns:
            Updated configuration dictionary

        Raises:
            ValueError: If builtin not found
        """
        # Verify builtin exists
        if not self.registry.get_tool_class(name) and not self.registry.get_processor_class(name):
            raise ValueError(f"Builtin '{name}' not found")

        builtin_config = await self._get_or_create_config(name)

        if enabled is not None:
            builtin_config.enabled = enabled
        if config is not None:
            builtin_config.config = config

        await self.session.flush()
        return await self.get_config(name) or {}

    # =========================================================================
    # API Key Management
    # =========================================================================

    async def list_api_keys(self) -> list[dict[str, Any]]:
        """List API key names (never expose values).

        Returns:
            List of API key metadata dictionaries.
            Each contains: name, service, created_at.
        """
        stmt = select(ApiKey).order_by(ApiKey.name)
        result = await self.session.execute(stmt)

        return [
            {
                "name": key.name,
                "service": key.service,
                "created_at": key.created_at,
            }
            for key in result.scalars().all()
        ]

    async def store_api_key(
        self, name: str, service: str, value: str
    ) -> dict[str, Any]:
        """Store an API key (encrypted).

        Args:
            name: Key identifier (e.g., "BRAVE_API_KEY")
            service: Service name (e.g., "brave_search")
            value: The actual API key to encrypt

        Returns:
            Created API key metadata (without value)

        Raises:
            ValueError: If API key with this name already exists
        """
        # Check if exists
        stmt = select(ApiKey).where(ApiKey.name == name)
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            raise ValueError(f"API key '{name}' already exists")

        api_key = ApiKey(
            name=name,
            service=service,
            key_encrypted=self.encryption.encrypt(value),
        )
        self.session.add(api_key)
        await self.session.flush()
        await self.session.refresh(api_key)

        return {
            "name": api_key.name,
            "service": api_key.service,
            "created_at": api_key.created_at,
        }

    async def delete_api_key(self, name: str) -> bool:
        """Delete an API key.

        Args:
            name: Key identifier

        Returns:
            True if deleted, False if not found
        """
        stmt = select(ApiKey).where(ApiKey.name == name)
        result = await self.session.execute(stmt)
        api_key = result.scalar_one_or_none()

        if not api_key:
            return False

        await self.session.delete(api_key)
        await self.session.flush()
        return True

    async def get_api_key_value(self, name: str) -> str | None:
        """Get decrypted API key value (internal use only).

        This method is for internal use by BuiltinLoader and should not
        be exposed via API endpoints.

        Args:
            name: Key identifier

        Returns:
            Decrypted API key value or None if not found
        """
        stmt = select(ApiKey).where(ApiKey.name == name)
        result = await self.session.execute(stmt)
        api_key = result.scalar_one_or_none()

        if not api_key:
            return None

        return self.encryption.decrypt(api_key.key_encrypted)

    # =========================================================================
    # Allow/Deny List Management
    # =========================================================================

    async def get_allowlist(self) -> dict[str, list[str]]:
        """Get global allow/deny lists.

        Returns:
            Dictionary with "allow" and "deny" keys containing lists of
            builtin names or group patterns (e.g., "group:voice").
        """
        stmt = select(BuiltinAllowlist).where(
            BuiltinAllowlist.workspace_id.is_(None)
        )
        result = await self.session.execute(stmt)

        allow = []
        deny = []
        for entry in result.scalars().all():
            if entry.list_type == "allow":
                allow.append(entry.entry)
            else:
                deny.append(entry.entry)

        return {"allow": allow, "deny": deny}

    async def update_allowlist(
        self, allow: list[str], deny: list[str]
    ) -> dict[str, list[str]]:
        """Update global allow/deny lists.

        Replaces existing lists with new values.

        Args:
            allow: List of allowed builtin names or group patterns
            deny: List of denied builtin names or group patterns

        Returns:
            Updated allow/deny lists
        """
        # Delete existing global entries
        stmt = delete(BuiltinAllowlist).where(
            BuiltinAllowlist.workspace_id.is_(None)
        )
        await self.session.execute(stmt)

        # Add new entries
        for name in allow:
            self.session.add(BuiltinAllowlist(
                workspace_id=None,
                entry=name,
                list_type="allow",
            ))
        for name in deny:
            self.session.add(BuiltinAllowlist(
                workspace_id=None,
                entry=name,
                list_type="deny",
            ))

        await self.session.flush()
        return await self.get_allowlist()

    # =========================================================================
    # Private Helpers
    # =========================================================================

    async def _get_config(self, name: str) -> BuiltinConfig | None:
        """Get global builtin config.

        Args:
            name: Builtin name

        Returns:
            BuiltinConfig or None if not found
        """
        stmt = select(BuiltinConfig).where(
            BuiltinConfig.workspace_id.is_(None),
            BuiltinConfig.builtin_name == name,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_create_config(self, name: str) -> BuiltinConfig:
        """Get or create global builtin config.

        Args:
            name: Builtin name

        Returns:
            Existing or newly created BuiltinConfig
        """
        config = await self._get_config(name)
        if not config:
            config = BuiltinConfig(
                workspace_id=None,
                builtin_name=name,
                enabled=True,
                config={},
            )
            self.session.add(config)
            await self.session.flush()
            await self.session.refresh(config)
        return config
