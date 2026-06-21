"""Tests for GmailAttachmentHandler — download attachment."""

import base64

import pytest


class TestGmailProviderDownloadAttachment:
    """Tests for GmailProvider.download_attachment()."""

    @pytest.mark.asyncio
    async def test_successful_download_returns_attachment_with_content(
        self, provider
    ) -> None:
        raw_bytes = b"PDF content here"
        encoded = base64.urlsafe_b64encode(raw_bytes).decode()
        att_chain = provider._service.users.return_value.messages.return_value
        att_chain.attachments.return_value.get.return_value.execute.return_value = {
            "data": encoded,
            "size": len(raw_bytes),
        }

        att = await provider.download_attachment("msg_001", "att_001")

        assert att.content == raw_bytes
        assert att.size_bytes == len(raw_bytes)
        assert att.attachment_id == "att_001"

    @pytest.mark.asyncio
    async def test_download_failure_raises_runtime_error(
        self, provider
    ) -> None:
        att_chain = provider._service.users.return_value.messages.return_value
        att_chain.attachments.return_value.get.return_value.execute.side_effect = Exception(
            "Download failed"
        )
        with pytest.raises(RuntimeError):
            await provider.download_attachment("msg_001", "att_bad")
