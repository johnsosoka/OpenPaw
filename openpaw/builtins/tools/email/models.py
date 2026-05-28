"""Pydantic input schemas for email tools."""

from pydantic import BaseModel, Field


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
