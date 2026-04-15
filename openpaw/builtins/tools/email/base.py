"""Email provider abstraction and data models.

Defines the EmailProvider ABC that concrete implementations (Gmail, SMTP, SES, etc.)
must implement, along with shared data models and the RecipientPolicy safety gate.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from fnmatch import fnmatch

logger = logging.getLogger(__name__)


@dataclass
class EmailAttachment:
    """Email attachment metadata and optional content.

    Content is populated only when explicitly downloaded via download_attachment().
    List/get operations return metadata only (content=None).
    """

    filename: str
    mime_type: str
    size_bytes: int
    attachment_id: str = ""
    content: bytes | None = None


@dataclass
class EmailMessage:
    """A single email message."""

    id: str
    thread_id: str
    subject: str
    sender: str
    recipients: list[str]
    body: str
    date: datetime
    snippet: str
    cc: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    attachments: list[EmailAttachment] = field(default_factory=list)

    def format_summary(self) -> str:
        """Format a concise summary for tool output."""
        att_info = f" [{len(self.attachments)} attachment(s)]" if self.attachments else ""
        cc_info = f", CC: {', '.join(self.cc)}" if self.cc else ""
        return (
            f"ID: {self.id}\n"
            f"Date: {self.date.strftime('%Y-%m-%d %H:%M')}\n"
            f"From: {self.sender}\n"
            f"To: {', '.join(self.recipients)}{cc_info}\n"
            f"Subject: {self.subject}{att_info}\n"
            f"Snippet: {self.snippet}"
        )

    def format_full(self) -> str:
        """Format full message content for tool output."""
        att_section = ""
        if self.attachments:
            att_lines = []
            for att in self.attachments:
                size_kb = att.size_bytes / 1024
                att_lines.append(
                    f"  - {att.filename} ({att.mime_type}, {size_kb:.1f} KB, id: {att.attachment_id})"
                )
            att_section = "\nAttachments:\n" + "\n".join(att_lines)

        cc_info = f"\nCC: {', '.join(self.cc)}" if self.cc else ""
        labels_info = f"\nLabels: {', '.join(self.labels)}" if self.labels else ""

        return (
            f"ID: {self.id}\n"
            f"Thread: {self.thread_id}\n"
            f"Date: {self.date.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"From: {self.sender}\n"
            f"To: {', '.join(self.recipients)}{cc_info}{labels_info}\n"
            f"Subject: {self.subject}\n"
            f"---\n"
            f"{self.body}"
            f"{att_section}"
        )


class RecipientPolicy:
    """Validates email recipients against an allowlist.

    Safety-first design: an empty allowlist blocks ALL outbound email.
    This is intentional — email is an externally-visible side effect and
    must be explicitly configured before agents can send.
    """

    def __init__(self, allowed_patterns: list[str], max_recipients: int = 10) -> None:
        self.allowed_patterns = [p.lower() for p in allowed_patterns]
        self.max_recipients = max_recipients

    def validate(self, recipients: list[str]) -> str | None:
        """Validate a list of recipients against the policy.

        Returns:
            None if all recipients pass, or an error message string.
        """
        if not recipients:
            return "No recipients specified"

        total = len(recipients)
        if total > self.max_recipients:
            return f"Too many recipients ({total}). Maximum allowed: {self.max_recipients}"

        if not self.allowed_patterns:
            return (
                "No allowed_recipients configured. "
                "Email sending is disabled by default for safety. "
                "Configure allowed_recipients in the email builtin config."
            )

        blocked: list[str] = []
        for addr in recipients:
            if not self._matches(addr):
                blocked.append(addr)

        if blocked:
            return (
                f"Recipient(s) not in allowlist: {', '.join(blocked)}. "
                f"Allowed patterns: {', '.join(self.allowed_patterns)}"
            )

        return None

    def _matches(self, email: str) -> bool:
        """Check if an email address matches any allowed pattern."""
        email_lower = email.lower().strip()
        for pattern in self.allowed_patterns:
            if fnmatch(email_lower, pattern):
                return True
        return False


class EmailProvider(ABC):
    """Abstract base class for email provider implementations.

    Concrete providers (Gmail, SMTP, SES) implement these methods to handle
    the transport-level details of sending and retrieving email.
    """

    @abstractmethod
    async def send(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to_message_id: str | None = None,
        thread_id: str | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
    ) -> str:
        """Send an email.

        Args:
            to: Recipient email addresses.
            subject: Email subject line.
            body: Plain text email body.
            cc: CC recipients.
            bcc: BCC recipients.
            reply_to_message_id: Message-ID header for threading replies.
            thread_id: Provider-specific thread identifier for reply grouping.
            attachments: List of (filename, content_bytes, mime_type) tuples.

        Returns:
            The sent message ID.

        Raises:
            Exception: On transport failure. The tool layer catches all
                exceptions and converts them to ``[Error: ...]`` strings.
        """

    @abstractmethod
    async def list_messages(
        self,
        max_results: int = 10,
        label: str = "INBOX",
    ) -> list[EmailMessage]:
        """List recent messages.

        Args:
            max_results: Maximum messages to return.
            label: Label/folder to list from.

        Returns:
            List of EmailMessage with metadata (body may be truncated).
        """

    @abstractmethod
    async def get_message(self, message_id: str) -> EmailMessage:
        """Get a single message with full content.

        Args:
            message_id: The provider-specific message ID.

        Returns:
            Full EmailMessage including body and attachment metadata.
        """

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[EmailMessage]:
        """Search messages using provider-native query syntax.

        Args:
            query: Provider-specific search query (e.g., Gmail search syntax).
            max_results: Maximum messages to return.

        Returns:
            List of matching EmailMessage objects.
        """

    @abstractmethod
    async def download_attachment(
        self,
        message_id: str,
        attachment_id: str,
        filename_hint: str = "",
    ) -> EmailAttachment:
        """Download an attachment's content.

        Args:
            message_id: The message containing the attachment.
            attachment_id: The provider-specific attachment ID.
            filename_hint: Original filename from message metadata. Providers
                that cannot recover the filename from the download API should
                use this as a fallback.

        Returns:
            EmailAttachment with content populated.
        """

    @abstractmethod
    async def mark_as_read(self, message_id: str) -> None:
        """Mark a message as read.

        Args:
            message_id: The message to mark as read.
        """

    @abstractmethod
    async def mark_as_unread(self, message_id: str) -> None:
        """Mark a message as unread.

        Args:
            message_id: The message to mark as unread.
        """
