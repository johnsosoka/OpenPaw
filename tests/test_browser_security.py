"""Tests for browser domain security policy."""

import pytest

from openpaw.builtins.tools.browser.security import DomainPolicy


class TestDomainPolicyBasics:
    """Test basic allow/deny behavior."""

    def test_empty_allowlist_allows_all(self):
        """Empty allowlist should allow all domains."""
        policy = DomainPolicy(allowed_domains=[], blocked_domains=[])
        assert policy.is_allowed("https://example.com")
        assert policy.is_allowed("https://google.com")
        assert policy.is_allowed("https://random-site.io")

    def test_none_allowlist_allows_all(self):
        """None allowlist should allow all domains."""
        policy = DomainPolicy(allowed_domains=None, blocked_domains=[])
        assert policy.is_allowed("https://example.com")
        assert policy.is_allowed("https://google.com")

    def test_nonempty_allowlist_blocks_unlisted(self):
        """Non-empty allowlist should block domains not in list."""
        policy = DomainPolicy(
            allowed_domains=["example.com", "google.com"], blocked_domains=[]
        )
        assert policy.is_allowed("https://example.com")
        assert policy.is_allowed("https://google.com")
        assert not policy.is_allowed("https://blocked-site.com")
        assert not policy.is_allowed("https://random.io")

    def test_blocklist_takes_precedence(self):
        """Blocklist should override allowlist."""
        policy = DomainPolicy(
            allowed_domains=["example.com", "evil.com"],
            blocked_domains=["evil.com"],
        )
        assert policy.is_allowed("https://example.com")
        assert not policy.is_allowed("https://evil.com")

    def test_blocklist_works_with_empty_allowlist(self):
        """Blocklist should work when allowlist is empty (allow-all mode)."""
        policy = DomainPolicy(allowed_domains=[], blocked_domains=["evil.com"])
        assert policy.is_allowed("https://example.com")
        assert policy.is_allowed("https://google.com")
        assert not policy.is_allowed("https://evil.com")


class TestWildcardMatching:
    """Test wildcard pattern matching."""

    def test_wildcard_matches_subdomains(self):
        """*.google.com should match all google.com subdomains."""
        policy = DomainPolicy(allowed_domains=["*.google.com"], blocked_domains=[])
        assert policy.is_allowed("https://mail.google.com")
        assert policy.is_allowed("https://calendar.google.com")
        assert policy.is_allowed("https://docs.google.com")
        assert policy.is_allowed("https://drive.google.com")

    def test_wildcard_matches_base_domain(self):
        """*.google.com should also match google.com itself."""
        policy = DomainPolicy(allowed_domains=["*.google.com"], blocked_domains=[])
        assert policy.is_allowed("https://google.com")

    def test_wildcard_does_not_match_unrelated(self):
        """*.google.com should not match unrelated domains."""
        policy = DomainPolicy(allowed_domains=["*.google.com"], blocked_domains=[])
        assert not policy.is_allowed("https://example.com")
        assert not policy.is_allowed("https://fakegoogle.com")
        assert not policy.is_allowed("https://google.com.evil.com")

    def test_wildcard_multilevel_subdomains(self):
        """Wildcard should match multi-level subdomains."""
        policy = DomainPolicy(allowed_domains=["*.google.com"], blocked_domains=[])
        assert policy.is_allowed("https://foo.bar.google.com")
        assert policy.is_allowed("https://a.b.c.google.com")

    def test_wildcard_in_blocklist(self):
        """Wildcards should work in blocklist."""
        policy = DomainPolicy(
            allowed_domains=[],  # Allow all
            blocked_domains=["*.ads.com"],
        )
        assert not policy.is_allowed("https://tracker.ads.com")
        assert not policy.is_allowed("https://pixel.ads.com")
        assert not policy.is_allowed("https://ads.com")
        assert policy.is_allowed("https://example.com")


class TestExactMatching:
    """Test exact domain matching."""

    def test_exact_match_required(self):
        """Exact domain should match only that domain."""
        policy = DomainPolicy(allowed_domains=["example.com"], blocked_domains=[])
        assert policy.is_allowed("https://example.com")
        assert not policy.is_allowed("https://www.example.com")
        assert not policy.is_allowed("https://subdomain.example.com")

    def test_exact_match_with_subdomain_in_list(self):
        """Should match exact subdomain if listed."""
        policy = DomainPolicy(
            allowed_domains=["www.example.com"], blocked_domains=[]
        )
        assert policy.is_allowed("https://www.example.com")
        assert not policy.is_allowed("https://example.com")
        assert not policy.is_allowed("https://api.example.com")


class TestUrlParsing:
    """Test URL parsing edge cases."""

    def test_url_with_port(self):
        """Should handle URLs with ports."""
        policy = DomainPolicy(allowed_domains=["example.com"], blocked_domains=[])
        assert policy.is_allowed("https://example.com:443")
        assert policy.is_allowed("http://example.com:8080")
        assert not policy.is_allowed("https://other.com:443")

    def test_url_with_path(self):
        """Should ignore path when checking domain."""
        policy = DomainPolicy(allowed_domains=["example.com"], blocked_domains=[])
        assert policy.is_allowed("https://example.com/path/to/page")
        assert policy.is_allowed("https://example.com/path?query=value")

    def test_url_with_query_params(self):
        """Should ignore query params when checking domain."""
        policy = DomainPolicy(allowed_domains=["example.com"], blocked_domains=[])
        assert policy.is_allowed("https://example.com?foo=bar&baz=qux")

    def test_url_with_fragment(self):
        """Should ignore fragment when checking domain."""
        policy = DomainPolicy(allowed_domains=["example.com"], blocked_domains=[])
        assert policy.is_allowed("https://example.com#section")

    def test_url_without_scheme(self):
        """Should handle URLs without scheme."""
        policy = DomainPolicy(allowed_domains=["example.com"], blocked_domains=[])
        # urlparse will put domain in path if no scheme, should fail
        assert not policy.is_allowed("example.com/path")

    def test_invalid_url(self):
        """Should reject invalid URLs gracefully."""
        policy = DomainPolicy(allowed_domains=["example.com"], blocked_domains=[])
        assert not policy.is_allowed("")
        assert not policy.is_allowed("not-a-url")
        assert not policy.is_allowed("://missing-scheme")


class TestCaseInsensitivity:
    """Test case-insensitive matching."""

    def test_mixed_case_domains(self):
        """Domain matching should be case-insensitive."""
        policy = DomainPolicy(allowed_domains=["Example.COM"], blocked_domains=[])
        assert policy.is_allowed("https://example.com")
        assert policy.is_allowed("https://EXAMPLE.COM")
        assert policy.is_allowed("https://ExAmPlE.CoM")

    def test_mixed_case_wildcards(self):
        """Wildcard matching should be case-insensitive."""
        policy = DomainPolicy(allowed_domains=["*.GOOGLE.com"], blocked_domains=[])
        assert policy.is_allowed("https://mail.google.com")
        assert policy.is_allowed("https://MAIL.GOOGLE.COM")

    def test_mixed_case_blocklist(self):
        """Blocklist should be case-insensitive."""
        policy = DomainPolicy(
            allowed_domains=[], blocked_domains=["EVIL.com", "bad.IO"]
        )
        assert not policy.is_allowed("https://evil.com")
        assert not policy.is_allowed("https://EVIL.COM")
        assert not policy.is_allowed("https://Bad.io")


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    def test_mixed_exact_and_wildcard_allowlist(self):
        """Should handle mix of exact and wildcard patterns."""
        policy = DomainPolicy(
            allowed_domains=["example.com", "*.google.com", "github.com"],
            blocked_domains=[],
        )
        assert policy.is_allowed("https://example.com")
        assert policy.is_allowed("https://mail.google.com")
        assert policy.is_allowed("https://google.com")
        assert policy.is_allowed("https://github.com")
        assert not policy.is_allowed("https://gitlab.com")

    def test_blocklist_overrides_wildcard_allowlist(self):
        """Blocklist should override even when allowlist has wildcard."""
        policy = DomainPolicy(
            allowed_domains=["*.google.com"],
            blocked_domains=["ads.google.com"],
        )
        assert policy.is_allowed("https://mail.google.com")
        assert policy.is_allowed("https://google.com")
        assert not policy.is_allowed("https://ads.google.com")

    def test_multiple_wildcard_patterns(self):
        """Should handle multiple wildcard patterns."""
        policy = DomainPolicy(
            allowed_domains=["*.google.com", "*.github.com"],
            blocked_domains=[],
        )
        assert policy.is_allowed("https://mail.google.com")
        assert policy.is_allowed("https://gist.github.com")
        assert policy.is_allowed("https://google.com")
        assert policy.is_allowed("https://github.com")
        assert not policy.is_allowed("https://example.com")

    def test_research_agent_config(self):
        """Test config for research agent (allow all except known bad)."""
        policy = DomainPolicy(
            allowed_domains=[],  # Allow all
            blocked_domains=["ads.example.com", "tracker.example.com"],
        )
        assert policy.is_allowed("https://arxiv.org")
        assert policy.is_allowed("https://github.com")
        assert policy.is_allowed("https://stackoverflow.com")
        assert not policy.is_allowed("https://ads.example.com")

    def test_assistant_config(self):
        """Test config for assistant (strict allowlist)."""
        policy = DomainPolicy(
            allowed_domains=["calendly.com", "*.google.com"],
            blocked_domains=[],
        )
        assert policy.is_allowed("https://calendly.com")
        assert policy.is_allowed("https://calendar.google.com")
        assert not policy.is_allowed("https://random-site.com")
