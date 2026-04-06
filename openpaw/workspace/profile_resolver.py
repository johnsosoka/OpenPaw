"""Spawn profile resolver with workspace-over-system precedence."""
import logging

from openpaw.model.spawn_profile import SpawnProfile

logger = logging.getLogger(__name__)


class SpawnProfileResolver:
    """Resolves spawn profile names to SpawnProfile instances.

    Holds a merged profile map where workspace profiles shadow system
    profiles with the same name. Provides lookup and listing.
    """

    def __init__(
        self,
        workspace_profiles: list[SpawnProfile],
        system_profiles: list[SpawnProfile] | None = None,
    ) -> None:
        """Initialize resolver with workspace and system profiles.

        Args:
            workspace_profiles: Profiles from the workspace's agent/team/ directory.
            system_profiles: Profiles from the system-level team_profiles/ directory.
                Workspace profiles take precedence over system profiles with the
                same name.
        """
        self._profiles: dict[str, SpawnProfile] = {}

        for profile in (system_profiles or []):
            self._profiles[profile.name] = profile

        for profile in workspace_profiles:
            if profile.name in self._profiles:
                logger.info(
                    "Workspace profile '%s' shadows system profile", profile.name
                )
            self._profiles[profile.name] = profile

    def resolve(self, name: str) -> SpawnProfile | None:
        """Look up a profile by name.

        Args:
            name: Profile name to resolve.

        Returns:
            SpawnProfile if found, None otherwise.
        """
        return self._profiles.get(name)

    def list_profiles(self) -> list[SpawnProfile]:
        """Return all profiles sorted by name."""
        return sorted(self._profiles.values(), key=lambda p: p.name)

    def list_profile_names(self) -> list[str]:
        """Return all profile names sorted alphabetically."""
        return sorted(self._profiles.keys())

    def register(self, profile: SpawnProfile) -> None:
        """Register or update a profile in the resolver.

        Args:
            profile: Profile to register. Overwrites any existing profile with
                the same name.
        """
        self._profiles[profile.name] = profile

    def unregister(self, name: str) -> bool:
        """Remove a profile from the resolver.

        Args:
            name: Profile name to remove.

        Returns:
            True if the profile was found and removed, False if not found.
        """
        return self._profiles.pop(name, None) is not None

    def __len__(self) -> int:
        """Return the number of registered profiles."""
        return len(self._profiles)
