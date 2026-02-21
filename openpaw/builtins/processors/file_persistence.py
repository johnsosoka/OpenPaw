"""File persistence processor for saving uploaded files to workspace."""

import logging
import mimetypes
from pathlib import Path
from typing import Any

from openpaw.builtins.base import (
    BaseBuiltinProcessor,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
    ProcessorResult,
)
from openpaw.core.timezone import workspace_now
from openpaw.core.utils import deduplicate_path, sanitize_filename
from openpaw.model.message import Attachment, Message
from openpaw.core.prompts.processors import FILE_RECEIVED_TEMPLATE

logger = logging.getLogger(__name__)

# MIME type to extension mapping for common file types
_MIME_TO_EXT = {
    # Audio
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
    # Images
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    # Video
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    # Documents
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes.

    Returns:
        Formatted size string (e.g., "2.3 MB").
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


class FilePersistenceProcessor(BaseBuiltinProcessor):
    """Persists all inbound file attachments to the workspace uploads directory.

    Saves original files to uploads/{YYYY-MM-DD}/{filename} and enriches
    the message content with file receipt notifications. Runs before all
    other processors so downstream processors (Docling, Whisper) can
    read from disk via attachment.saved_path.

    No API key required - always available if enabled.

    Config options:
        workspace_path: Path to workspace directory (required, injected by loader)
        max_file_size: Maximum file size in bytes (default: 50 MB)
        clear_data_after_save: Free attachment data bytes after saving (default: False)
    """

    metadata = BuiltinMetadata(
        name="file_persistence",
        display_name="File Persistence",
        description="Saves uploaded files to workspace and notifies agent",
        builtin_type=BuiltinType.PROCESSOR,
        group="file",
        prerequisites=BuiltinPrerequisite(),  # Always available, no API key
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.workspace_path = config.get("workspace_path") if config else None
        self.max_file_size = (
            config.get("max_file_size", 52428800) if config else 52428800
        )  # 50 MB default
        self.clear_data_after_save = (
            config.get("clear_data_after_save", False) if config else False
        )
        self._timezone = config.get("timezone", "UTC") if config else "UTC"

        if not self.workspace_path:
            logger.warning(
                "FilePersistenceProcessor initialized without workspace_path - will pass through all messages"
            )

    async def process_inbound(self, message: Message) -> ProcessorResult:
        """Save all attachments to workspace uploads/ directory.

        Args:
            message: The incoming message from a channel.

        Returns:
            ProcessorResult with updated message containing file receipt info.
        """
        if not self.workspace_path:
            logger.warning("No workspace_path configured, skipping file persistence")
            return ProcessorResult(message=message)

        # Filter attachments that have data
        attachments_with_data = [a for a in message.attachments if a.data is not None]

        if not attachments_with_data:
            return ProcessorResult(message=message)

        # Process each attachment
        enrichment_parts: list[str] = []
        uploaded_files_metadata: list[dict[str, Any]] = []

        for attachment in attachments_with_data:
            try:
                result = await self._save_attachment(attachment, message)
                if result:
                    enrichment_parts.append(result["enrichment"])
                    uploaded_files_metadata.append(result["metadata"])
            except Exception as e:
                logger.error(f"Failed to save attachment: {e}", exc_info=True)
                # Add error note to enrichment
                filename = attachment.filename or "unknown"
                enrichment_parts.append(f"[Error saving file: {filename} - {str(e)}]")

        # If no files were saved, pass through unchanged
        if not enrichment_parts:
            return ProcessorResult(message=message)

        # Build enriched content
        enrichment = "\n".join(enrichment_parts)
        if message.content:
            new_content = f"{enrichment}\n\n{message.content}"
        else:
            new_content = enrichment

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
            metadata={**message.metadata, "uploaded_files": uploaded_files_metadata},
            attachments=message.attachments,  # Attachments updated in-place
        )

        return ProcessorResult(message=updated_message)

    async def _save_attachment(
        self, attachment: Attachment, message: Message
    ) -> dict[str, Any] | None:
        """Save a single attachment to the uploads directory.

        Args:
            attachment: The attachment to save.
            message: The parent message (for fallback filename generation).

        Returns:
            Dict with enrichment text and metadata, or None if save failed.
        """
        # Type assertion - attachment.data is guaranteed non-None by caller
        assert attachment.data is not None
        assert self.workspace_path is not None

        file_size = len(attachment.data)

        # Check file size limit
        if file_size > self.max_file_size:
            max_mb = self.max_file_size / (1024 * 1024)
            size_mb = file_size / (1024 * 1024)
            error_msg = (
                f"[File too large: {attachment.filename or 'unknown'} "
                f"({size_mb:.1f} MB, limit {max_mb:.1f} MB)]"
            )
            logger.warning(f"File exceeds size limit: {size_mb:.1f} MB > {max_mb:.1f} MB")
            return {"enrichment": error_msg, "metadata": {}}

        # Determine filename
        filename = self._generate_filename(attachment, message)

        # Sanitize filename
        sanitized_filename = sanitize_filename(filename)

        # Build target directory (use workspace timezone for date partition)
        today = workspace_now(self._timezone).strftime("%Y-%m-%d")
        target_dir = Path(self.workspace_path) / "uploads" / today
        target_dir.mkdir(parents=True, exist_ok=True)

        # Build target path and deduplicate
        target_path = target_dir / sanitized_filename
        target_path = deduplicate_path(target_path)

        # Write file
        try:
            target_path.write_bytes(attachment.data)
            logger.info(f"Saved file to {target_path}")
        except Exception as e:
            logger.error(f"Failed to write file to {target_path}: {e}")
            raise

        # Set saved_path on attachment (relative to workspace)
        relative_path = str(target_path.relative_to(Path(self.workspace_path)))
        attachment.saved_path = relative_path

        # Clear data if configured
        if self.clear_data_after_save:
            attachment.data = None

        # Build enrichment text
        size_str = _format_size(file_size)
        mime_str = attachment.mime_type or "unknown type"
        enrichment = FILE_RECEIVED_TEMPLATE.format(
            filename=target_path.name,
            size=size_str,
            mime_type=mime_str,
            saved_path=relative_path,
        )

        # Build metadata
        metadata = {
            "original_path": relative_path,
            "filename": target_path.name,
            "mime_type": attachment.mime_type,
            "size_bytes": file_size,
        }

        return {"enrichment": enrichment, "metadata": metadata}

    def _generate_filename(self, attachment: Attachment, message: Message) -> str:
        """Generate a filename for an attachment.

        Uses attachment.filename if available, otherwise generates a fallback
        based on attachment type and MIME type.

        Args:
            attachment: The attachment to generate a filename for.
            message: The parent message (for ID-based fallback).

        Returns:
            Generated filename.
        """
        if attachment.filename:
            return attachment.filename

        # Generate fallback based on type
        extension = self._guess_extension(attachment)

        if attachment.type == "audio":
            return f"voice_{message.id}{extension}"
        elif attachment.type == "image":
            return f"photo_{message.id}{extension}"
        elif attachment.type == "video":
            return f"video_{message.id}{extension}"
        else:
            return f"upload_{message.id}{extension}"

    def _guess_extension(self, attachment: Attachment) -> str:
        """Guess file extension from MIME type or attachment type.

        Args:
            attachment: The attachment to guess extension for.

        Returns:
            File extension (including dot), or '.bin' if unknown.
        """
        # Try MIME type mapping first
        if attachment.mime_type:
            ext = _MIME_TO_EXT.get(attachment.mime_type)
            if ext:
                return ext

            # Try mimetypes.guess_extension as fallback
            ext = mimetypes.guess_extension(attachment.mime_type)
            if ext:
                return ext

        # Fallback based on attachment type
        if attachment.type == "audio":
            return ".ogg"
        elif attachment.type == "image":
            return ".jpg"
        elif attachment.type == "video":
            return ".mp4"
        else:
            return ".bin"
