"""Email builtin — send and receive email via a configured provider.

Returns 8 LangChain tools covering the full email workflow:
send, check, get, search, reply, download attachment, mark read/unread.

Only Gmail (via Google service account + domain-wide delegation) is
supported in this release.  Additional providers can be added by
implementing the ``EmailProvider`` ABC in ``base.py`` and registering
them in ``__init__`` of this module.
"""

import logging
import mimetypes
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from openpaw.agent.tools.sandbox import resolve_sandboxed_path
from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools.email.base import EmailProvider, RecipientPolicy
from openpaw.core.utils import deduplicate_path, sanitize_filename

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class SendEmailInput(BaseModel):
    """Input schema for send_email."""

    to: list[str] = Field(description="Primary recipient email addresses.")
    subject: str = Field(description="Email subject line.")
    body: str = Field(description="Plain-text email body.")
    cc: list[str] | None = Field(default=None, description="CC recipient email addresses.")
    bcc: list[str] | None = Field(default=None, description="BCC recipient email addresses.")
    attachment_paths: list[str] | None = Field(
        default=None,
        description=(
            "Workspace-relative paths to files to attach. "
            "Each path is resolved against the workspace sandbox."
        ),
    )


class CheckEmailInput(BaseModel):
    """Input schema for check_email."""

    max_results: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of messages to return (1–50).",
    )
    label: str = Field(
        default="INBOX",
        description="Gmail label/folder to list from (e.g. 'INBOX', 'SENT', 'SPAM').",
    )


class GetEmailInput(BaseModel):
    """Input schema for get_email."""

    message_id: str = Field(description="The Gmail message ID to retrieve.")


class SearchEmailInput(BaseModel):
    """Input schema for search_email."""

    query: str = Field(
        description=(
            "Gmail search query using Gmail search syntax. "
            "Examples: 'from:alice@example.com', 'subject:invoice', 'is:unread'."
        )
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of results to return (1–50).",
    )


class ReplyEmailInput(BaseModel):
    """Input schema for reply_email."""

    message_id: str = Field(description="The Gmail message ID to reply to.")
    body: str = Field(description="Plain-text body of the reply.")
    attachment_paths: list[str] | None = Field(
        default=None,
        description="Workspace-relative paths to files to attach to the reply.",
    )


class DownloadAttachmentInput(BaseModel):
    """Input schema for download_attachment."""

    message_id: str = Field(description="The Gmail message ID containing the attachment.")
    attachment_id: str = Field(description="The attachment ID from get_email output.")
    filename: str = Field(
        description="The attachment filename from get_email output (e.g., 'report.pdf').",
    )
    save_as: str | None = Field(
        default=None,
        description=(
            "Optional filename override. "
            "If omitted, uses the filename parameter. "
            "Saved to downloads/email/ in the workspace."
        ),
    )


class MarkAsReadInput(BaseModel):
    """Input schema for mark_as_read."""

    message_id: str = Field(description="The Gmail message ID to mark as read.")


class MarkAsUnreadInput(BaseModel):
    """Input schema for mark_as_unread."""

    message_id: str = Field(description="The Gmail message ID to mark as unread.")


# ---------------------------------------------------------------------------
# Builtin
# ---------------------------------------------------------------------------

_PROVIDER_NOT_CONFIGURED = (
    "[Error: Email provider is not configured. "
    "Contact the workspace administrator to set up email credentials.]"
)


class EmailToolBuiltin(BaseBuiltinTool):
    """Multi-tool email builtin providing send/receive capabilities.

    Backed by a Gmail service-account provider.  The provider is constructed
    lazily from the workspace config injected by ``BuiltinLoader``.

    Config options (all injected by the loader or agent.yaml):
        provider: Provider name — only "gmail" is supported (default: "gmail").
        service_account_file: Absolute path to the Google service account JSON.
        delegated_user: Email address to impersonate via domain-wide delegation.
        allowed_recipients: List of glob patterns for outbound recipient validation.
        max_recipients: Maximum number of recipients per outbound message (default: 10).
        workspace_path: Absolute path to the workspace root (injected by loader).
    """

    metadata = BuiltinMetadata(
        name="email",
        display_name="Email",
        description="Send and receive email via configured provider",
        builtin_type=BuiltinType.TOOL,
        group="communication",
        prerequisites=BuiltinPrerequisite(packages=["google.oauth2", "googleapiclient"]),
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)

        provider_name: str = self.config.get("provider", "gmail")
        service_account_file: str | None = self.config.get("service_account_file")
        delegated_user: str | None = self.config.get("delegated_user")

        workspace_path_raw = self.config.get("workspace_path")
        self._workspace_root: Path | None = (
            Path(workspace_path_raw).resolve() if workspace_path_raw else None
        )

        allowed_recipients: list[str] = self.config.get("allowed_recipients", [])
        max_recipients: int = self.config.get("max_recipients", 10)
        self._policy = RecipientPolicy(allowed_recipients, max_recipients)

        # Build provider — store None if config is incomplete so that all tools
        # can return a clean error string rather than crashing at call time.
        self._provider: EmailProvider | None = None
        if not service_account_file or not delegated_user:
            logger.warning(
                "EmailToolBuiltin: 'service_account_file' or 'delegated_user' not set — "
                "email tools will return an error until the config is corrected."
            )
            return

        if provider_name != "gmail":
            logger.warning(
                f"EmailToolBuiltin: unsupported provider '{provider_name}'. "
                "Only 'gmail' is supported. Email tools will be unavailable."
            )
            return

        if not Path(service_account_file).exists():
            logger.warning(
                f"EmailToolBuiltin: service_account_file not found at "
                f"'{service_account_file}' — email tools will fail on first use."
            )

        try:
            from openpaw.builtins.tools.email.gmail import GmailProvider

            self._provider = GmailProvider(
                service_account_file=service_account_file,
                delegated_user=delegated_user,
            )
            logger.info(
                f"EmailToolBuiltin initialized (provider=gmail, delegated_user={delegated_user})"
            )
        except Exception as exc:
            logger.error(f"EmailToolBuiltin: failed to initialize GmailProvider: {exc}")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_langchain_tool(self) -> list[Any]:
        """Return the full list of email tools."""
        return [
            self._create_send_email_tool(),
            self._create_check_email_tool(),
            self._create_get_email_tool(),
            self._create_search_email_tool(),
            self._create_reply_email_tool(),
            self._create_download_attachment_tool(),
            self._create_mark_as_read_tool(),
            self._create_mark_as_unread_tool(),
        ]

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

    # ------------------------------------------------------------------
    # Tool factories
    # ------------------------------------------------------------------

    def _create_send_email_tool(self) -> Any:
        from langchain_core.tools import StructuredTool

        async def send_email_async(
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

        return StructuredTool.from_function(
            coroutine=send_email_async,
            name="send_email",
            description=(
                "Send an email to one or more recipients. "
                "All recipients (to, cc, bcc) must match the configured allowed_recipients "
                "patterns — email sending is disabled by default for safety. "
                "Optionally attach workspace files by providing their relative paths."
            ),
            args_schema=SendEmailInput,
        )

    def _create_check_email_tool(self) -> Any:
        from langchain_core.tools import StructuredTool

        async def check_email_async(max_results: int = 10, label: str = "INBOX") -> str:
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

        return StructuredTool.from_function(
            coroutine=check_email_async,
            name="check_email",
            description=(
                "List recent email messages from a Gmail label (default: INBOX). "
                "Returns message summaries including ID, date, sender, subject, and snippet. "
                "Use get_email with the message ID to retrieve the full body."
            ),
            args_schema=CheckEmailInput,
        )

    def _create_get_email_tool(self) -> Any:
        from langchain_core.tools import StructuredTool

        async def get_email_async(message_id: str) -> str:
            if not self._provider:
                return _PROVIDER_NOT_CONFIGURED

            try:
                message = await self._provider.get_message(message_id)
            except Exception as exc:
                logger.error(f"get_email failed for id={message_id}: {exc}")
                return f"[Error: Failed to retrieve email {message_id}: {exc}]"

            return message.format_full()

        return StructuredTool.from_function(
            coroutine=get_email_async,
            name="get_email",
            description=(
                "Retrieve the full content of a specific email by its message ID. "
                "Returns the complete body, headers, and attachment metadata. "
                "Attachment IDs in the output can be used with download_attachment."
            ),
            args_schema=GetEmailInput,
        )

    def _create_search_email_tool(self) -> Any:
        from langchain_core.tools import StructuredTool

        async def search_email_async(query: str, max_results: int = 10) -> str:
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

        return StructuredTool.from_function(
            coroutine=search_email_async,
            name="search_email",
            description=(
                "Search email using Gmail query syntax. "
                "Supports operators like 'from:', 'to:', 'subject:', 'is:unread', "
                "'has:attachment', 'after:2024/01/01', and free-text search. "
                "Returns message summaries; use get_email for full content."
            ),
            args_schema=SearchEmailInput,
        )

    def _create_reply_email_tool(self) -> Any:
        from langchain_core.tools import StructuredTool

        async def reply_email_async(
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
            # NOTE: reply_email currently only sends to original.sender. If cc/bcc
            # fields are added in a future iteration, validate ALL recipients here.
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

        return StructuredTool.from_function(
            coroutine=reply_email_async,
            name="reply_email",
            description=(
                "Reply to an existing email thread. "
                "Automatically sets threading headers (In-Reply-To, References) "
                "so the reply appears in the same thread. "
                "The original sender must match the allowed_recipients policy."
            ),
            args_schema=ReplyEmailInput,
        )

    def _create_download_attachment_tool(self) -> Any:
        from langchain_core.tools import StructuredTool

        async def download_attachment_async(
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

        return StructuredTool.from_function(
            coroutine=download_attachment_async,
            name="download_attachment",
            description=(
                "Download an email attachment and save it to downloads/email/ "
                "in the workspace. "
                "Requires the message ID and attachment ID from get_email output. "
                "Returns the workspace-relative path of the saved file."
            ),
            args_schema=DownloadAttachmentInput,
        )

    def _create_mark_as_read_tool(self) -> Any:
        from langchain_core.tools import StructuredTool

        async def mark_as_read_async(message_id: str) -> str:
            if not self._provider:
                return _PROVIDER_NOT_CONFIGURED

            try:
                await self._provider.mark_as_read(message_id)
                return f"Message {message_id} marked as read."
            except Exception as exc:
                logger.error(f"mark_as_read failed for id={message_id}: {exc}")
                return f"[Error: Failed to mark message as read: {exc}]"

        return StructuredTool.from_function(
            coroutine=mark_as_read_async,
            name="mark_as_read",
            description="Mark an email message as read (removes the UNREAD label).",
            args_schema=MarkAsReadInput,
        )

    def _create_mark_as_unread_tool(self) -> Any:
        from langchain_core.tools import StructuredTool

        async def mark_as_unread_async(message_id: str) -> str:
            if not self._provider:
                return _PROVIDER_NOT_CONFIGURED

            try:
                await self._provider.mark_as_unread(message_id)
                return f"Message {message_id} marked as unread."
            except Exception as exc:
                logger.error(f"mark_as_unread failed for id={message_id}: {exc}")
                return f"[Error: Failed to mark message as unread: {exc}]"

        return StructuredTool.from_function(
            coroutine=mark_as_unread_async,
            name="mark_as_unread",
            description="Mark an email message as unread (adds the UNREAD label).",
            args_schema=MarkAsUnreadInput,
        )
