"""Business logic for global settings management."""

from pathlib import Path
from typing import Any, TypedDict

import yaml  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import AsyncSession

from openpaw.db.repositories.settings_repo import SettingsRepository


class ImportStats(TypedDict):
    """Statistics for settings import operation."""

    settings: int
    builtins: int


class ImportResult(TypedDict):
    """Result of a settings import operation."""

    imported: ImportStats
    skipped: int
    errors: list[str]


class SettingsService:
    """Business logic for global settings management."""

    VALID_CATEGORIES = {"agent", "queue", "lanes"}

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SettingsRepository(session)

    async def get_all(self) -> dict[str, dict[str, Any]]:
        """Get all settings grouped by category.

        Returns:
            Dictionary with category names as keys and setting dicts as values.
            Example: {"agent": {"model": "...", "temperature": 0.7}, ...}
        """
        all_settings = await self.repo.list_all()
        grouped: dict[str, dict[str, Any]] = {}

        for setting in all_settings:
            if setting.category not in grouped:
                grouped[setting.category] = {}
            # Extract key name after category prefix
            key_name = setting.key.split(".", 1)[-1] if "." in setting.key else setting.key
            grouped[setting.category][key_name] = setting.value.get("value")

        return grouped

    async def get_category(self, category: str) -> dict[str, Any] | None:
        """Get settings for a specific category.

        Args:
            category: Category name (must be in VALID_CATEGORIES)

        Returns:
            Dictionary of settings for the category, or None if invalid category.
        """
        if category not in self.VALID_CATEGORIES:
            return None

        settings = await self.repo.get_by_category(category)
        return {
            s.key.split(".", 1)[-1]: s.value.get("value")
            for s in settings
        }

    async def update_category(
        self, category: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Update settings for a category. Upserts each key.

        Args:
            category: Category name (must be in VALID_CATEGORIES)
            data: Dictionary of key-value pairs to update

        Returns:
            Updated category settings

        Raises:
            ValueError: If category is not valid
        """
        if category not in self.VALID_CATEGORIES:
            raise ValueError(f"Invalid category: {category}")

        for key, value in data.items():
            full_key = f"{category}.{key}"
            await self.repo.upsert(
                key=full_key,
                value=value,
                category=category,
                encrypted=False,
            )

        await self.session.flush()
        return await self.get_category(category) or {}

    async def import_from_yaml(self, config_path: Path) -> ImportResult:
        """Import settings from a YAML config file.

        Extracts agent, queue, and lanes sections from the YAML file and
        imports them into the database via upsert operations.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            Summary dictionary with import results:
            {
                "imported": {"settings": count, "builtins": count},
                "skipped": count,
                "errors": [...]
            }
        """
        result: ImportResult = {
            "imported": {"settings": 0, "builtins": 0},
            "skipped": 0,
            "errors": [],
        }

        try:
            with config_path.open("r") as f:
                config_data = yaml.safe_load(f)

            if not config_data:
                result["errors"].append("Empty or invalid YAML file")
                return result

            # Import each valid category
            for category in self.VALID_CATEGORIES:
                if category not in config_data:
                    result["skipped"] += 1
                    continue

                category_data = config_data[category]
                if not isinstance(category_data, dict):
                    result["errors"].append(
                        f"Category '{category}' is not a dictionary"
                    )
                    continue

                # Flatten nested dictionaries into dot-notation keys
                flattened = self._flatten_dict(category_data)

                # Import each setting
                for key, value in flattened.items():
                    try:
                        full_key = f"{category}.{key}"
                        await self.repo.upsert(
                            key=full_key,
                            value=value,
                            category=category,
                            encrypted=False,
                        )
                        result["imported"]["settings"] += 1
                    except Exception as e:
                        result["errors"].append(
                            f"Failed to import {category}.{key}: {str(e)}"
                        )

            # Import builtins separately (stored under 'agent' category)
            if "builtins" in config_data:
                builtins_data = config_data["builtins"]
                if isinstance(builtins_data, dict):
                    flattened = self._flatten_dict(builtins_data, prefix="builtins")
                    for key, value in flattened.items():
                        try:
                            await self.repo.upsert(
                                key=key,
                                value=value,
                                category="agent",
                                encrypted=False,
                            )
                            result["imported"]["builtins"] += 1
                        except Exception as e:
                            result["errors"].append(
                                f"Failed to import builtin {key}: {str(e)}"
                            )

            await self.session.flush()

        except FileNotFoundError:
            result["errors"].append(f"Config file not found: {config_path}")
        except yaml.YAMLError as e:
            result["errors"].append(f"YAML parsing error: {str(e)}")
        except Exception as e:
            result["errors"].append(f"Unexpected error: {str(e)}")

        return result

    def _flatten_dict(
        self, data: dict[str, Any], prefix: str = "", sep: str = "."
    ) -> dict[str, Any]:
        """Flatten a nested dictionary into dot-notation keys.

        Args:
            data: Dictionary to flatten
            prefix: Prefix for keys (used in recursion)
            sep: Separator character (default: ".")

        Returns:
            Flattened dictionary with dot-notation keys

        Example:
            {"model": {"provider": "anthropic"}}
            -> {"model.provider": "anthropic"}
        """
        flattened: dict[str, Any] = {}

        for key, value in data.items():
            full_key = f"{prefix}{sep}{key}" if prefix else key

            if isinstance(value, dict):
                # Recursively flatten nested dictionaries
                nested = self._flatten_dict(value, prefix=full_key, sep=sep)
                flattened.update(nested)
            else:
                # Store the value directly
                flattened[full_key] = value

        return flattened
