"""Tests for GmailProvider integration — send, list, get, search."""

import importlib.util
import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from .conftest import _b64, _make_raw_message

# Marker applied to tests that require the email extra (google_auth_httplib2).
# We use find_spec() rather than importorskip() because find_spec() stat-checks the
# package without executing its __init__.py: the conftest registers a bare `google`
# stub that would make a real import of google_auth_httplib2 fail (it needs
# google.auth.*), so importorskip() would wrongly skip even when the package exists.
_skip_no_email_extra = pytest.mark.skipif(
    importlib.util.find_spec("google_auth_httplib2") is None,
    reason="google_auth_httplib2 not installed (email extra required)",
)


class TestGmailProviderSend:
    """Tests for GmailProvider.send() with a mocked Gmail service."""

    @pytest.mark.asyncio
    async def test_successful_send_returns_message_id(self, provider) -> None:
        provider._service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
            "id": "sent_msg_001"
        }
        result = await provider.send(
            to=["recipient@example.com"],
            subject="Test",
            body="Hello.",
        )
        assert result == "sent_msg_001"

    @pytest.mark.asyncio
    async def test_api_error_returns_error_string(self, provider) -> None:
        exc = Exception("API failure")
        exc.status_code = 500  # type: ignore[attr-defined]
        provider._service.users.return_value.messages.return_value.send.return_value.execute.side_effect = exc

        with pytest.raises(RuntimeError):
            await provider.send(
                to=["recipient@example.com"],
                subject="Test",
                body="Hello.",
            )

    @pytest.mark.asyncio
    async def test_send_with_thread_id_included_in_payload(
        self, provider
    ) -> None:
        execute_mock = MagicMock(return_value={"id": "sent_001"})
        send_mock = MagicMock()
        send_mock.execute = execute_mock

        messages_mock = MagicMock()
        messages_mock.send = MagicMock(return_value=send_mock)
        provider._service.users.return_value.messages.return_value = messages_mock

        await provider.send(
            to=["r@example.com"],
            subject="Re: Thread",
            body="Reply.",
            thread_id="thread_abc",
        )

        call_kwargs = messages_mock.send.call_args[1]
        assert call_kwargs["body"].get("threadId") == "thread_abc"


class TestGmailProviderGetMessage:
    """Tests for GmailProvider.get_message()."""

    def _make_full_raw(self) -> dict:
        body_text = "Full body content."
        return {
            "id": "msg_full",
            "threadId": "thr_full",
            "snippet": "Full body content.",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "To", "value": "recipient@example.com"},
                    {"name": "Subject", "value": "Full Message"},
                    {"name": "Date", "value": "Tue, 20 Feb 2024 14:00:00 +0000"},
                ],
                "mimeType": "text/plain",
                "body": {"data": _b64(body_text)},
            },
        }

    @pytest.mark.asyncio
    async def test_get_message_returns_email_message(self, provider) -> None:
        provider._service.users.return_value.messages.return_value.get.return_value.execute.return_value = (
            self._make_full_raw()
        )

        msg = await provider.get_message("msg_full")

        assert msg.id == "msg_full"
        assert msg.subject == "Full Message"
        assert "Full body content." in msg.body

    @pytest.mark.asyncio
    async def test_get_message_raises_on_api_failure(self, provider) -> None:
        provider._service.users.return_value.messages.return_value.get.return_value.execute.side_effect = Exception(
            "Not found"
        )
        with pytest.raises(RuntimeError):
            await provider.get_message("nonexistent")


class TestGmailProviderListMessages:
    """Tests for GmailProvider.list_messages()."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_messages(self, provider) -> None:
        provider._service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": []
        }

        result = await provider.list_messages()
        assert result == []

    @pytest.mark.asyncio
    async def test_caps_max_results_at_100(self, provider) -> None:
        list_mock = MagicMock()
        list_mock.execute.return_value = {"messages": []}
        provider._service.users.return_value.messages.return_value.list.return_value = list_mock

        await provider.list_messages(max_results=200)

        call_kwargs = provider._service.users.return_value.messages.return_value.list.call_args[1]
        assert call_kwargs["maxResults"] <= 100

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_api_error(self, provider) -> None:
        provider._service.users.return_value.messages.return_value.list.return_value.execute.side_effect = Exception(
            "Service unavailable"
        )

        result = await provider.list_messages()
        assert result == []


@_skip_no_email_extra
class TestGmailProviderBuildWiring:
    """Regression guard: _get_service() must isolate httplib2.Http per request.

    These tests verify the fix for the SIGTRAP crash caused by sharing one
    httplib2.Http object across concurrent asyncio.to_thread workers. Without the
    fix, GmailFetcher.list_messages/search fan out up to 100 concurrent calls that
    all drive the same TLS connection, corrupting the OpenSSL write buffer.

    See llm_memory/BUG-gmail-builtin-sigtrap-macos-py314.md for full context.

    Skipped in environments where google_auth_httplib2 is not installed (no email extra).
    """

    def _fresh_provider(self) -> Any:
        """GmailProvider with _service=None so _get_service() reaches the build path.

        The shared ``provider`` fixture pre-injects ``_service``, bypassing the
        build block entirely. These tests need a clean instance.
        """
        from openpaw.builtins.tools.email.gmail import GmailProvider

        return GmailProvider(
            service_account_file="/fake/sa.json",
            delegated_user="agent@example.com",
        )

    def _conftest_gap_stubs(self) -> dict[str, Any]:
        """Stub modules the new _get_service() imports that the conftest does not cover.

        The conftest stubs ``googleapiclient.discovery`` but not
        ``googleapiclient.http``. It also stubs ``google`` as a bare module, which
        blocks ``google_auth_httplib2`` from importing (it needs ``google.auth``).
        We add minimal stubs here so every import inside ``_get_service()``
        resolves without touching disk or network.
        """
        http_mod = types.ModuleType("googleapiclient.http")
        http_mod.HttpRequest = MagicMock(name="HttpRequest")  # type: ignore[attr-defined]

        # google_auth_httplib2 needs google.auth at import time. Rather than
        # unwinding the conftest's google stub, we register google_auth_httplib2
        # itself so patch() finds it in sys.modules without triggering a real import.
        gah_mod = types.ModuleType("google_auth_httplib2")
        gah_mod.AuthorizedHttp = MagicMock(name="AuthorizedHttp")  # type: ignore[attr-defined]
        gah_mod.Request = MagicMock(name="Request")  # type: ignore[attr-defined]

        return {
            "googleapiclient.http": http_mod,
            "google_auth_httplib2": gah_mod,
        }

    def test_request_builder_isolates_http_per_call(self) -> None:
        """requestBuilder must instantiate a fresh httplib2.Http on every invocation.

        Two successive builder calls (simulating two concurrent worker threads) must
        each produce a distinct Http instance. Sharing one object across threads
        corrupts the OpenSSL write buffer, causing SIGTRAP on macOS + Python 3.14.
        """
        captured_build_kwargs: dict[str, Any] = {}
        http_instances: list[MagicMock] = []

        def fake_build(*args: Any, **kwargs: Any) -> MagicMock:
            captured_build_kwargs.update(kwargs)
            return MagicMock()

        def new_http() -> MagicMock:
            inst = MagicMock(name=f"Http#{len(http_instances)}")
            http_instances.append(inst)
            return inst

        with patch.dict(sys.modules, self._conftest_gap_stubs()):
            with (
                patch("httplib2.Http", side_effect=new_http),
                patch("google_auth_httplib2.AuthorizedHttp"),
                patch("googleapiclient.discovery.build", side_effect=fake_build),
                patch("google.oauth2.service_account.Credentials.from_service_account_file"),
            ):
                prov = self._fresh_provider()
                prov._get_service()

                builder = captured_build_kwargs.get("requestBuilder")
                assert callable(builder), "build() must receive a requestBuilder callable"

                # Simulate two concurrent worker threads each triggering a request.
                builder(None)
                builder(None)

        # _get_service() creates one Http for discovery_http, then each builder
        # call creates another — three total Http() instantiations.
        assert len(http_instances) >= 3, (
            f"Expected at least 3 Http() calls (1 discovery + 2 per-request), "
            f"got {len(http_instances)}"
        )
        request_http_1 = http_instances[-2]
        request_http_2 = http_instances[-1]
        assert request_http_1 is not request_http_2, (
            "requestBuilder must create a distinct httplib2.Http per call — "
            "sharing one instance across threads corrupts TLS (SIGTRAP)."
        )

    def test_build_called_with_correct_kwargs(self) -> None:
        """build() must receive requestBuilder, cache_discovery=False, and http= not credentials=.

        Passing both ``http=`` and ``credentials=`` to build() raises; this test
        guards against accidentally reverting to the old ``credentials=`` form.
        """
        captured_args: tuple[Any, ...] = ()
        captured_kwargs: dict[str, Any] = {}

        def fake_build(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal captured_args, captured_kwargs
            captured_args = args
            captured_kwargs = kwargs
            return MagicMock()

        with patch.dict(sys.modules, self._conftest_gap_stubs()):
            with (
                patch("httplib2.Http"),
                patch("google_auth_httplib2.AuthorizedHttp"),
                patch("googleapiclient.discovery.build", side_effect=fake_build),
                patch("google.oauth2.service_account.Credentials.from_service_account_file"),
            ):
                prov = self._fresh_provider()
                prov._get_service()

        assert captured_args == ("gmail", "v1"), (
            f"build() positional args must be ('gmail', 'v1'), got {captured_args!r}"
        )
        assert callable(captured_kwargs.get("requestBuilder")), (
            "build() must receive a requestBuilder callable"
        )
        assert captured_kwargs.get("cache_discovery") is False, (
            "cache_discovery must be False to silence oauth2client file_cache warning"
        )
        assert "http" in captured_kwargs, (
            "build() must receive http= kwarg (AuthorizedHttp for the discovery doc)"
        )
        assert "credentials" not in captured_kwargs, (
            "build() must NOT receive credentials= — passing both http= and credentials= raises"
        )

    def test_credentials_refreshed_eagerly_under_lock(self) -> None:
        """_get_service() must prime the access token once before returning.

        Eager refresh avoids a thundering herd: without it, the first burst of
        concurrent worker threads would each find the shared credentials
        unpopulated and call refresh() simultaneously.
        """
        with patch.dict(sys.modules, self._conftest_gap_stubs()):
            with (
                patch("httplib2.Http"),
                patch("google_auth_httplib2.AuthorizedHttp"),
                patch("googleapiclient.discovery.build", return_value=MagicMock()),
                patch(
                    "google.oauth2.service_account.Credentials.from_service_account_file"
                ) as mock_from_file,
            ):
                prov = self._fresh_provider()
                prov._get_service()

        credentials = mock_from_file.return_value
        credentials.refresh.assert_called_once()
