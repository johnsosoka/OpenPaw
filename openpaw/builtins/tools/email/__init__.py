"""Email builtin — send and receive email via a configured provider.

Returns 8 LangChain tools covering the full email workflow:
send, check, get, search, reply, download attachment, mark read/unread.

Only Gmail (via Google service account + domain-wide delegation) is
supported in this release.  Additional providers can be added by
implementing the ``EmailProvider`` ABC in ``base.py`` and registering
them in ``__init__`` of this module.
"""

import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools.email.base import EmailProvider, RecipientPolicy
from openpaw.builtins.tools.email.executor import EmailToolExecutor
from openpaw.builtins.tools.email.models import (
    CheckEmailInput,
    DownloadAttachmentInput,
    GetEmailInput,
    MarkAsReadInput,
    MarkAsUnreadInput,
    ReplyEmailInput,
    SearchEmailInput,
    SendEmailInput,
)

logger = logging.getLogger(__name__)


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
            self._executor = EmailToolExecutor(lambda: self._provider, self._policy, self._workspace_root)
            return

        if provider_name != "gmail":
            logger.warning(
                f"EmailToolBuiltin: unsupported provider '{provider_name}'. "
                "Only 'gmail' is supported. Email tools will be unavailable."
            )
            self._executor = EmailToolExecutor(lambda: self._provider, self._policy, self._workspace_root)
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

        self._executor = EmailToolExecutor(lambda: self._provider, self._policy, self._workspace_root)

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
        return self._executor._resolve_attachments(paths)

    # ------------------------------------------------------------------
    # Tool factories
    # ------------------------------------------------------------------

    def _create_send_email_tool(self) -> Any:
        async def send_email_async(
            to: list[str],
            subject: str,
            body: str,
            cc: list[str] | None = None,
            bcc: list[str] | None = None,
            attachment_paths: list[str] | None = None,
        ) -> str:
            return await self._executor.send_email(
                to=to,
                subject=subject,
                body=body,
                cc=cc,
                bcc=bcc,
                attachment_paths=attachment_paths,
            )

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
        async def check_email_async(max_results: int = 10, label: str = "INBOX") -> str:
            return await self._executor.check_email(max_results=max_results, label=label)

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
        async def get_email_async(message_id: str) -> str:
            return await self._executor.get_email(message_id=message_id)

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
        async def search_email_async(query: str, max_results: int = 10) -> str:
            return await self._executor.search_email(query=query, max_results=max_results)

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
        async def reply_email_async(
            message_id: str,
            body: str,
            attachment_paths: list[str] | None = None,
        ) -> str:
            return await self._executor.reply_email(
                message_id=message_id,
                body=body,
                attachment_paths=attachment_paths,
            )

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
        async def download_attachment_async(
            message_id: str,
            attachment_id: str,
            filename: str,
            save_as: str | None = None,
        ) -> str:
            return await self._executor.download_attachment(
                message_id=message_id,
                attachment_id=attachment_id,
                filename=filename,
                save_as=save_as,
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
        async def mark_as_read_async(message_id: str) -> str:
            return await self._executor.mark_as_read(message_id=message_id)

        return StructuredTool.from_function(
            coroutine=mark_as_read_async,
            name="mark_as_read",
            description="Mark an email message as read (removes the UNREAD label).",
            args_schema=MarkAsReadInput,
        )

    def _create_mark_as_unread_tool(self) -> Any:
        async def mark_as_unread_async(message_id: str) -> str:
            return await self._executor.mark_as_unread(message_id=message_id)

        return StructuredTool.from_function(
            coroutine=mark_as_unread_async,
            name="mark_as_unread",
            description="Mark an email message as unread (adds the UNREAD label).",
            args_schema=MarkAsUnreadInput,
        )
