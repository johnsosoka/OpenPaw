"""Domain security policy for browser navigation."""

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class DomainPolicy:
    """Per-workspace domain allowlist/blocklist for browser navigation.

    Provides security controls over which domains an agent can navigate to.
    Supports wildcard patterns (*.google.com) and subdomain matching.

    If allowed_domains is empty, all domains are permitted (unless blocked).
    If allowed_domains is non-empty, ONLY those domains are permitted.
    blocked_domains always takes precedence over allowed_domains.
    """

    def __init__(
        self,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
    ):
        """Initialize domain policy.

        Args:
            allowed_domains: If non-empty, only these domains are permitted.
                Supports wildcards (*.google.com). Empty list allows all domains.
            blocked_domains: Always blocked, takes precedence over allowed.
                Supports wildcards.
        """
        self.allowed_domains = [d.lower() for d in (allowed_domains or [])]
        self.blocked_domains = [d.lower() for d in (blocked_domains or [])]

        logger.debug(
            f"DomainPolicy initialized: "
            f"allowed={self.allowed_domains}, blocked={self.blocked_domains}"
        )

    def is_allowed(self, url: str) -> bool:
        """Check if a URL is permitted by the policy.

        Args:
            url: The URL to check.

        Returns:
            True if the URL is allowed, False otherwise.
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # Handle URLs with ports (e.g., example.com:8080)
            if ":" in domain:
                domain = domain.split(":")[0]

            if not domain:
                logger.warning(f"Could not extract domain from URL: {url}")
                return False

            # Check blocklist first (takes precedence)
            for pattern in self.blocked_domains:
                if self._matches_pattern(domain, pattern):
                    logger.debug(f"Domain {domain} blocked by pattern {pattern}")
                    return False

            # If allowlist is empty, allow all (unless blocked)
            if not self.allowed_domains:
                logger.debug(f"Domain {domain} allowed (no allowlist)")
                return True

            # Check allowlist
            for pattern in self.allowed_domains:
                if self._matches_pattern(domain, pattern):
                    logger.debug(f"Domain {domain} allowed by pattern {pattern}")
                    return True

            # Not in allowlist
            logger.debug(f"Domain {domain} not in allowlist")
            return False

        except Exception as e:
            logger.error(f"Error checking domain policy for {url}: {e}")
            return False

    def _matches_pattern(self, domain: str, pattern: str) -> bool:
        """Check if domain matches a pattern.

        Supports wildcard prefix (*.google.com) for subdomain matching.
        Exact match also supported (google.com).

        Args:
            domain: The domain to check (already lowercased).
            pattern: The pattern to match against (already lowercased).

        Returns:
            True if domain matches pattern.
        """
        # Exact match
        if domain == pattern:
            return True

        # Wildcard subdomain match (*.google.com)
        if pattern.startswith("*."):
            base_domain = pattern[2:]  # Remove "*."

            # Check if domain ends with the base domain
            # and has a subdomain prefix
            if domain.endswith("." + base_domain):
                return True

            # Also match the base domain itself (*.google.com matches google.com)
            if domain == base_domain:
                return True

        return False
