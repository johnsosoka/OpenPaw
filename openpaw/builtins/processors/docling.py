"""Docling document processor for inbound PDFs and documents."""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from openpaw.builtins.base import (
    BaseBuiltinProcessor,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
    ProcessorResult,
)
from openpaw.channels.base import Attachment, Message

logger = logging.getLogger(__name__)

# Supported MIME types for Docling processing
SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "text/html",
    "image/png",
    "image/jpeg",
    "image/tiff",
}

# File extensions for fallback detection when MIME type is missing
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
}

# Maximum file size for processing (default 50 MB, Telegram's limit)
DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024


class DoclingProcessor(BaseBuiltinProcessor):
    """Converts inbound documents to markdown using Docling.

    Processes document attachments before the message reaches the agent,
    converting PDFs, DOCX, PPTX, XLSX, HTML, and images to markdown format
    and saving them to the workspace inbox directory.

    No API key required - runs locally using Docling.

    Config options:
        workspace_path: Path to workspace directory (required, injected by loader)
        max_file_size: Maximum file size in bytes (default: 50 MB)
    """

    metadata = BuiltinMetadata(
        name="docling",
        display_name="Docling Document Processor",
        description="Converts inbound documents (PDF, DOCX, etc.) to markdown for agent consumption",
        builtin_type=BuiltinType.PROCESSOR,
        group="document",
        prerequisites=BuiltinPrerequisite(),  # No API key needed (local processing)
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.workspace_path = config.get("workspace_path") if config else None
        self.max_file_size = config.get("max_file_size", DEFAULT_MAX_FILE_SIZE) if config else DEFAULT_MAX_FILE_SIZE

        if not self.workspace_path:
            logger.warning("DoclingProcessor initialized without workspace_path - will pass through all messages")

    async def process_inbound(self, message: Message) -> ProcessorResult:
        """Convert document attachments to markdown and save to workspace inbox.

        Args:
            message: The incoming message, possibly with document attachments.

        Returns:
            ProcessorResult with enriched message content pointing to processed files.
        """
        if not self.workspace_path:
            logger.warning("No workspace_path configured, skipping document processing")
            return ProcessorResult(message=message)

        # Find document attachments
        document_attachments = [
            a for a in message.attachments
            if self._is_supported_document(a)
        ]

        if not document_attachments:
            return ProcessorResult(message=message)

        # Check if docling is available
        if not self._check_docling_available():
            logger.warning("docling package not installed, skipping document processing")
            error_note = (
                "\n\n[Note: Document processing unavailable - docling not installed. "
                "Install with: pip install docling]"
            )
            new_content = message.content + error_note if message.content else error_note
            updated_message = Message(
                id=message.id,
                channel=message.channel,
                session_key=message.session_key,
                user_id=message.user_id,
                content=new_content,
                direction=message.direction,
                timestamp=message.timestamp,
                reply_to_id=message.reply_to_id,
                metadata={**message.metadata, "docling_unavailable": True},
                attachments=message.attachments,
            )
            return ProcessorResult(message=updated_message)

        processed_files: list[str] = []
        errors: list[str] = []

        for attachment in document_attachments:
            if not attachment.data:
                logger.warning("Document attachment has no data, skipping")
                errors.append("Document attachment has no data")
                continue

            # Check file size
            file_size = len(attachment.data)
            if file_size > self.max_file_size:
                size_mb = file_size / (1024 * 1024)
                max_mb = self.max_file_size / (1024 * 1024)
                logger.warning(f"Document too large: {size_mb:.1f} MB (max {max_mb:.1f} MB)")
                errors.append(f"Document too large ({size_mb:.1f} MB, max {max_mb:.1f} MB)")
                continue

            try:
                result_info = await self._process_document(attachment, file_size)
                if result_info:
                    processed_files.append(result_info)
                else:
                    errors.append("Conversion failed")
            except Exception as e:
                logger.error(f"Failed to process document: {e}", exc_info=True)
                errors.append(str(e))

        # Build enriched message content
        enrichment_parts = []

        # Add processed files info
        for result_info in processed_files:
            enrichment_parts.append(result_info)

        # Add error notes
        if errors:
            error_detail = "; ".join(errors)
            plural = "files" if len(errors) > 1 else "file"
            enrichment_parts.append(
                f"[Note: {len(errors)} document {plural} could not be processed - {error_detail}]"
            )

        # If nothing was processed and all failed, just add error note
        if not processed_files and errors:
            enrichment = "\n\n" + "\n".join(enrichment_parts)
        elif processed_files:
            # Add to start of message (before user caption)
            enrichment = "\n".join(enrichment_parts)
            if message.content:
                enrichment += f"\n\nUser caption: {message.content}"
        else:
            # No documents processed, no errors (shouldn't happen)
            enrichment = ""

        new_content = enrichment or message.content

        # Create updated message
        updated_message = Message(
            id=message.id,
            channel=message.channel,
            session_key=message.session_key,
            user_id=message.user_id,
            content=new_content,
            direction=message.direction,
            timestamp=message.timestamp,
            reply_to_id=message.reply_to_id,
            metadata={**message.metadata, "docling_processed": True, "processed_count": len(processed_files)},
            attachments=message.attachments,
        )

        return ProcessorResult(message=updated_message)

    def _is_supported_document(self, attachment: Attachment) -> bool:
        """Check if attachment is a supported document type.

        Args:
            attachment: The attachment to check.

        Returns:
            True if the attachment should be processed by Docling.
        """
        # Check MIME type first
        if attachment.mime_type and attachment.mime_type in SUPPORTED_MIME_TYPES:
            return True

        # Fallback: check file extension
        if attachment.filename:
            ext = Path(attachment.filename).suffix.lower()
            if ext in SUPPORTED_EXTENSIONS:
                return True

        return False

    def _check_docling_available(self) -> bool:
        """Check if docling package is available.

        Returns:
            True if docling can be imported.
        """
        try:
            import docling  # noqa: F401
            return True
        except ImportError:
            return False

    async def _process_document(self, attachment: Attachment, file_size: int) -> str | None:
        """Process a single document attachment.

        Args:
            attachment: The document attachment to process.
            file_size: Size of the file in bytes.

        Returns:
            Info string about the processed document, or None if processing failed.
        """
        # Import docling (already checked for availability)
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as e:
            logger.error(f"Failed to import docling: {e}")
            return None

        # Generate output directory
        today = datetime.now().strftime("%Y-%m-%d")
        filename = attachment.filename or "document"
        sanitized_name = self._sanitize_filename(filename)

        # Type assertion - workspace_path is guaranteed non-None by caller check
        assert self.workspace_path is not None
        inbox_dir = Path(self.workspace_path) / "inbox" / today / sanitized_name
        inbox_dir.mkdir(parents=True, exist_ok=True)

        # Save raw file to temp location
        import tempfile
        # Type assertion - attachment.data is guaranteed non-None by caller check
        assert attachment.data is not None
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp_file:
            tmp_file.write(attachment.data)
            tmp_path = Path(tmp_file.name)

        try:
            # Run docling conversion in thread pool (CPU-bound)
            converter = DocumentConverter()
            result = await asyncio.to_thread(converter.convert, tmp_path)

            # Export to markdown
            markdown = result.document.export_to_markdown()

            # Save markdown file
            md_file = inbox_dir / "document.md"
            md_file.write_text(markdown, encoding="utf-8")
            logger.info(f"Saved markdown to {md_file}")

            # Count tables and images (approximate from markdown)
            table_count = markdown.count("| --- |")
            image_count = markdown.count("![")

            # Build result info
            size_mb = file_size / (1024 * 1024)
            relative_path = f"inbox/{today}/{sanitized_name}/"

            result_parts = [f"[Document received: {filename} ({size_mb:.1f} MB)]"]
            result_parts.append(f"Processed to: {relative_path}")

            content_parts = ["document.md (full text)"]
            if table_count > 0:
                content_parts.append(f"{table_count} tables")
            if image_count > 0:
                content_parts.append(f"{image_count} images")

            result_parts.append(f"Contents: {', '.join(content_parts)}")

            return "\n".join(result_parts)

        except Exception as e:
            logger.error(f"Docling conversion failed: {e}", exc_info=True)
            return None
        finally:
            # Clean up temp file
            try:
                tmp_path.unlink()
            except Exception:
                pass

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for use as directory name.

        Args:
            filename: Original filename.

        Returns:
            Sanitized filename safe for directory creation.
        """
        # Remove extension
        name = Path(filename).stem

        # Replace spaces with underscores
        name = name.replace(" ", "_")

        # Replace dots with underscores (except extension dot, already removed)
        name = name.replace(".", "_")

        # Remove special characters (keep only alphanumeric, underscore, hyphen)
        name = re.sub(r"[^a-zA-Z0-9_-]", "", name)

        # Lowercase
        name = name.lower()

        # Limit length
        if len(name) > 100:
            name = name[:100]

        # Fallback if empty or only underscores/hyphens
        if not name or not re.search(r"[a-z0-9]", name):
            name = "document"

        return name
