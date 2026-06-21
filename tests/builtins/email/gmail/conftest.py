"""Shared fixtures for Gmail provider tests."""

import base64
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out google.oauth2 / googleapiclient before importing the provider,
# since those packages may not be installed in the test environment.
# ---------------------------------------------------------------------------


def _build_google_stubs() -> None:
    """Register minimal google.* stubs in sys.modules if not already present."""
    if "google" in sys.modules:
        return

    google = types.ModuleType("google")
    oauth2 = types.ModuleType("google.oauth2")
    sa = types.ModuleType("google.oauth2.service_account")

    class _Credentials:
        @classmethod
        def from_service_account_file(cls, path: str, **kwargs: object) -> "_Credentials":
            return cls()

    sa.Credentials = _Credentials  # type: ignore[attr-defined]
    oauth2.service_account = sa  # type: ignore[attr-defined]
    google.oauth2 = oauth2  # type: ignore[attr-defined]

    googleapiclient = types.ModuleType("googleapiclient")
    discovery = types.ModuleType("googleapiclient.discovery")
    discovery.build = MagicMock()  # type: ignore[attr-defined]
    googleapiclient.discovery = discovery  # type: ignore[attr-defined]

    errors_mod = types.ModuleType("googleapiclient.errors")

    class HttpError(Exception):
        def __init__(self, resp: object, content: bytes) -> None:
            self.resp = resp
            self.content = content

    errors_mod.HttpError = HttpError  # type: ignore[attr-defined]
    googleapiclient.errors = errors_mod  # type: ignore[attr-defined]

    sys.modules["google"] = google
    sys.modules["google.oauth2"] = oauth2
    sys.modules["google.oauth2.service_account"] = sa
    sys.modules["googleapiclient"] = googleapiclient
    sys.modules["googleapiclient.discovery"] = discovery
    sys.modules["googleapiclient.errors"] = errors_mod


_build_google_stubs()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _b64(text: str) -> str:
    """Base64url-encode a string (no padding), as Gmail API does."""
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8").rstrip("=")


def _make_raw_message(
    *,
    msg_id: str = "msg001",
    thread_id: str = "thread001",
    snippet: str = "This is a snippet.",
    labels: list[str] | None = None,
    headers: list[dict] | None = None,
    payload: dict | None = None,
) -> dict:
    """Build a minimal raw Gmail API message dict."""
    default_headers = [
        {"name": "From", "value": "alice@example.com"},
        {"name": "To", "value": "bob@example.com"},
        {"name": "Subject", "value": "Test Subject"},
        {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
    ]
    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": snippet,
        "labelIds": labels or ["INBOX"],
        "payload": payload or {"headers": headers or default_headers, "mimeType": "text/plain"},
    }


@pytest.fixture
def provider():
    """Return a GmailProvider with mocked Google API service."""
    from openpaw.builtins.tools.email.gmail import GmailProvider

    with patch("google.oauth2.service_account.Credentials.from_service_account_file"):
        with patch("googleapiclient.discovery.build"):
            prov = GmailProvider(
                service_account_file="/fake/sa.json",
                delegated_user="agent@example.com",
            )
    # Inject a mock service so _get_service() returns without hitting disk/network.
    prov._service = MagicMock()
    return prov
