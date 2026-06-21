"""Email tool executor — async tool bodies decoupled from LangChain wiring.

The EmailToolExecutor contains the business logic for all 8 email tools.
It is instantiated by EmailToolBuiltin and invoked from thin StructuredTool
wrappers.
"""

import logging
from pathlib import Path
from typing import Any

from openpaw.agent.tools.sandbox import resolve_sandboxed_path
from openpaw.builtins.tools.email.base import EmailProvider, RecipientPolicy
from openpaw.core.utils import deduplicate_path, sanitize_filename

logger = logging.getLogger(__name__)

_PROVIDER_NOT_CONFIGURED = (
    "[Error: Email provider is not configured. "
    "Contact the workspace administrator to set up email credentials.]"
)


class EmailToolExecutor:
    """Execute email tool operations with provider, policy, and workspace context."""

    def __init__(
        self,
        provider_getter: Any,
        policy: RecipientPolicy,
        workspace_root: Path | None,
    ) -> None:
        self._provider_getter = provider_getter
        self._policy = policy
        self._workspace_root = workspace_root

    @property
    def _provider(self) -> EmailProvider | None:
        result = self._provider_getter()
        return result  # type: ignore[no-any-return]

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachment_paths: list[str] | None = None,
    ) -> str:
        if not self._provider:
            return _PROVIDER_NOT_CONFIGURED

        cc = cc or []
        bcc = bcc or []
        attachment_paths = attachment_paths or []

        all_recipients = to + cc + bcc
        policy_error = self._policy.validate(all_recipients)
        if policy_error:
            return f"[Error: Recipient policy violation — {policy_error}]"

        attachments, att_error = self._resolve_attachments(attachment_paths)
        if att_error:
            return att_error

        try:
            message_id = await self._provider.send(
                to=to,
                subject=subject,
                body=body,
                cc=cc or None,
                bcc=bcc or None,
                attachments=attachments or None,
            )
            att_note = f" with {len(attachments)} attachment(s)" if attachments else ""
            return f"Email sent{att_note}. Message ID: {message_id}"
        except Exception as exc:
            logger.error(f"send_email failed: {exc}")
            return f"[Error: Failed to send email: {exc}]"

    async def check_email(self, max_results: int = 10, label: str = "INBOX") -> str:
        if not self._provider:
            return _PROVIDER_NOT_CONFIGURED

        try:
            messages = await self._provider.list_messages(
                max_results=max_results, label=label
            )
        except Exception as exc:
            logger.error(f"check_email failed: {exc}")
            return f"[Error: Failed to check email: {exc}]"

        if not messages:
            return f"No messages found in {label}."

        summaries = "\n\n---\n\n".join(msg.format_summary() for msg in messages)
        return f"{len(messages)} message(s) in {label}:\n\n{summaries}"

    async def get_email(self, message_id: str) -> str:
        if not self._provider:
            return _PROVIDER_NOT_CONFIGURED

        try:
            message = await self._provider.get_message(message_id)
        except Exception as exc:
            logger.error(f"get_email failed for id={message_id}: {exc}")
            return f"[Error: Failed to retrieve email {message_id}: {exc}]"

        return message.format_full()

    async def search_email(self, query: str, max_results: int = 10) -> str:
        if not self._provider:
            return _PROVIDER_NOT_CONFIGURED

        try:
            messages = await self._provider.search(query=query, max_results=max_results)
        except Exception as exc:
            logger.error(f"search_email failed (query={query!r}): {exc}")
            return f"[Error: Email search failed: {exc}]"

        if not messages:
            return f"No messages matched query: {query}"

        summaries = "\n\n---\n\n".join(msg.format_summary() for msg in messages)
        return f"{len(messages)} result(s) for '{query}':\n\n{summaries}"

    async def reply_email(
        self,
        message_id: str,
        body: str,
        attachment_paths: list[str] | None = None,
    ) -> str:
        if not self._provider:
            return _PROVIDER_NOT_CONFIGURED

        attachment_paths = attachment_paths or []

        # Fetch the original message to extract threading info and sender.
        try:
            original = await self._provider.get_message(message_id)
        except Exception as exc:
            logger.error(f"reply_email: failed to fetch original message {message_id}: {exc}")
            return f"[Error: Could not retrieve original message {message_id}: {exc}]"

        # Validate original sender against recipient policy.
        policy_error = self._policy.validate([original.sender])
        if policy_error:
            return (
                f"[Error: Cannot reply — original sender '{original.sender}' "
                f"is not in the allowed_recipients list: {policy_error}]"
            )

        attachments, att_error = self._resolve_attachments(attachment_paths)
        if att_error:
            return att_error

        # Avoid stacking "Re: Re: Re: ..." on chain replies.
        subject = original.subject
        if not subject.startswith("Re: "):
            subject = f"Re: {subject}"

        try:
            sent_id = await self._provider.send(
                to=[original.sender],
                subject=subject,
                body=body,
                reply_to_message_id=original.id,
                thread_id=original.thread_id,
                attachments=attachments or None,
            )
            att_note = f" with {len(attachments)} attachment(s)" if attachments else ""
            return (
                f"Reply sent{att_note} to {original.sender}. "
                f"Message ID: {sent_id} (thread: {original.thread_id})"
            )
        except Exception as exc:
            logger.error(f"reply_email failed for message_id={message_id}: {exc}")
            return f"[Error: Failed to send reply: {exc}]"

    async def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        filename: str,
        save_as: str | None = None,
    ) -> str:
        if not self._provider:
            return _PROVIDER_NOT_CONFIGURED

        if not self._workspace_root:
            return "[Error: workspace_path not configured — cannot save attachments]"

        try:
            attachment = await self._provider.download_attachment(
                message_id=message_id,
                attachment_id=attachment_id,
                filename_hint=filename,
            )
        except Exception as exc:
            logger.error(
                f"download_attachment failed (msg={message_id}, att={attachment_id}): {exc}"
            )
            return f"[Error: Failed to download attachment: {exc}]"

        if attachment.content is None:
            return "[Error: Provider returned attachment with no content]"

        # Determine filename — caller override takes priority.
        raw_filename = save_as or attachment.filename or "attachment"
        safe_name = sanitize_filename(raw_filename)

        # Ensure target directory exists.
        save_dir = self._workspace_root / "downloads" / "email"
        save_dir.mkdir(parents=True, exist_ok=True)

        # Deduplicate if a file with that name already exists.
        target_path = deduplicate_path(save_dir / safe_name)

        try:
            target_path.write_bytes(attachment.content)
        except OSError as exc:
            logger.error(f"download_attachment: failed to write {target_path}: {exc}")
            return f"[Error: Failed to save attachment to disk: {exc}]"

        # Return workspace-relative path for easy reference in subsequent tools.
        relative = target_path.relative_to(self._workspace_root)
        size_kb = len(attachment.content) / 1024
        return (
            f"Attachment saved: {relative} ({size_kb:.1f} KB)\n"
            f"MIME type: {attachment.mime_type}"
        )

    async def mark_as_read(self, message_id: str) -> str:
        if not self._provider:
            return _PROVIDER_NOT_CONFIGURED

        try:
            await self._provider.mark_as_read(message_id)
            return f"Message {message_id} marked as read."
        except Exception as exc:
            logger.error(f"mark_as_read failed for id={message_id}: {exc}")
            return f"[Error: Failed to mark message as read: {exc}]"

    async def mark_as_unread(self, message_id: str) -> str:
        if not self._provider:
            return _PROVIDER_NOT_CONFIGURED

        try:
            await self._provider.mark_as_unread(message_id)
            return f"Message {message_id} marked as unread."
        except Exception as exc:
            logger.error(f"mark_as_unread failed for id={message_id}: {exc}")
            return f"[Error: Failed to mark message as unread: {exc}]"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_attachments(
        self, paths: list[str]
    ) -> tuple[list[tuple[str, bytes, str]], str | None]:
        """Resolve a list of workspace-relative attachment paths to (name, bytes, mime) tuples.

        Returns:
            A tuple of (attachments, error_string).  If any path fails to
            resolve or read, error_string is set and attachments is empty.
        """
        import mimetypes

        if not paths:
            return [], None

        if not self._workspace_root:
            return [], "[Error: workspace_path not configured — cannot resolve attachment paths]"

        attachments: list[tuple[str, bytes, str]] = []
        for raw_path in paths:
            try:
                resolved = resolve_sandboxed_path(self._workspace_root, raw_path)
            except ValueError as exc:
                return [], f"[Error: Invalid attachment path '{raw_path}': {exc}]"

            if not resolved.exists():
                return [], f"[Error: Attachment not found: {raw_path}]"

            if not resolved.is_file():
                return [], f"[Error: Attachment path is not a file: {raw_path}]"

            try:
                content = resolved.read_bytes()
            except OSError as exc:
                return [], f"[Error: Could not read attachment '{raw_path}': {exc}]"

            mime_type, _ = mimetypes.guess_type(resolved.name)
            attachments.append((resolved.name, content, mime_type or "application/octet-stream"))

        return attachments, None
