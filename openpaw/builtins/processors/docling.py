"""Docling document processor for inbound PDFs and documents."""

import asyncio
import logging
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
from openpaw.tools.sandbox import resolve_sandboxed_path

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

# ISO 639-1 to Tesseract ISO 639-2/3 language code mapping
_TESSERACT_LANG_MAP: dict[str, str] = {
    "en": "eng", "fr": "fra", "de": "deu", "es": "spa", "it": "ita",
    "pt": "por", "nl": "nld", "ru": "rus", "zh": "chi_sim", "ja": "jpn",
    "ko": "kor", "ar": "ara", "hi": "hin", "th": "tha", "vi": "vie",
    "pl": "pol", "uk": "ukr", "cs": "ces", "sv": "swe", "da": "dan",
    "fi": "fin", "no": "nor", "hu": "hun", "ro": "ron", "el": "ell",
    "tr": "tur", "he": "heb", "id": "ind",
}

# ISO 639-1 to OcrMac locale mapping
_OCRMAC_LANG_MAP: dict[str, str] = {
    "en": "en-US", "fr": "fr-FR", "de": "de-DE", "es": "es-ES", "it": "it-IT",
    "pt": "pt-BR", "zh": "zh-Hans", "ja": "ja-JP", "ko": "ko-KR",
}


class DoclingProcessor(BaseBuiltinProcessor):
    """Converts inbound documents to markdown using Docling.

    Processes document attachments before the message reaches the agent,
    converting PDFs, DOCX, PPTX, XLSX, HTML, and images to markdown format.
    Reads from saved_path (set by FilePersistenceProcessor) or falls back to
    attachment.data. Writes converted markdown as sibling .md file.

    No API key required - runs locally using Docling.

    Config options:
        workspace_path: Path to workspace directory (required, injected by loader)
        max_file_size: Maximum file size in bytes (default: 50 MB)
        ocr_backend: OCR backend selection ('auto', 'mac', 'easyocr', 'tesseract', 'rapidocr')
        ocr_languages: List of ISO 639-1 language codes (default: ['en'])
        force_full_page_ocr: Force full-page OCR (default: True, recommended for scanned docs)
        document_timeout: Per-document timeout in seconds (default: None, no limit)
        do_ocr: Enable OCR processing (default: True)
        do_table_structure: Enable table structure detection (default: True)
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
        self.ocr_backend = config.get("ocr_backend", "auto") if config else "auto"
        self.ocr_languages = config.get("ocr_languages", ["en"]) if config else ["en"]
        self.force_full_page_ocr = config.get("force_full_page_ocr", True) if config else True
        self.document_timeout = config.get("document_timeout", None) if config else None
        self.do_ocr = config.get("do_ocr", True) if config else True
        self.do_table_structure = config.get("do_table_structure", True) if config else True

        if not self.workspace_path:
            logger.warning("DoclingProcessor initialized without workspace_path - will pass through all messages")

    async def process_inbound(self, message: Message) -> ProcessorResult:
        """Convert document attachments to markdown and save as sibling .md files.

        Args:
            message: The incoming message, possibly with document attachments.

        Returns:
            ProcessorResult with enriched message content pointing to processed files.
        """
        if not self.workspace_path:
            logger.warning("No workspace_path configured, skipping document processing")
            return ProcessorResult(message=message)

        # Find supported document attachments
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
            # Must have either saved_path or data
            if not attachment.saved_path and not attachment.data:
                logger.warning("Document attachment has no saved_path or data, skipping")
                errors.append("Document attachment has no data")
                continue

            # Check file size (from saved_path if available, else from data)
            if attachment.saved_path:
                try:
                    source_path = resolve_sandboxed_path(
                        Path(self.workspace_path).resolve(),
                        attachment.saved_path,
                    )
                except ValueError as e:
                    logger.error(f"Invalid saved_path: {e}")
                    errors.append("Invalid file path")
                    continue
                if source_path.exists():
                    file_size = source_path.stat().st_size
                else:
                    logger.warning(f"saved_path does not exist: {source_path}, skipping")
                    errors.append(f"File not found: {attachment.saved_path}")
                    continue
            else:
                # Must have data at this point
                assert attachment.data is not None
                file_size = len(attachment.data)

            # Check file size limit
            if file_size > self.max_file_size:
                size_mb = file_size / (1024 * 1024)
                max_mb = self.max_file_size / (1024 * 1024)
                logger.warning(f"Document too large: {size_mb:.1f} MB (max {max_mb:.1f} MB)")
                errors.append(f"Document too large ({size_mb:.1f} MB, max {max_mb:.1f} MB)")
                continue

            try:
                result_info = await self._process_document(attachment)
                if result_info:
                    processed_files.append(result_info)
                else:
                    errors.append("Conversion failed")
            except Exception as e:
                logger.error(f"Failed to process document: {e}", exc_info=True)
                errors.append(str(e))

        # Build enriched message content
        enrichment_parts = []

        # Add conversion results
        for result_info in processed_files:
            enrichment_parts.append(result_info)

        # Add error notes
        if errors:
            error_detail = "; ".join(errors)
            plural = "files" if len(errors) > 1 else "file"
            enrichment_parts.append(
                f"[Note: {len(errors)} document {plural} could not be processed - {error_detail}]"
            )

        # Append conversion results to existing message content
        if enrichment_parts:
            if message.content:
                new_content = message.content + "\n\n" + "\n".join(enrichment_parts)
            else:
                new_content = "\n".join(enrichment_parts)
        else:
            new_content = message.content

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

    def _write_temp_file(self, attachment: Attachment) -> tuple[Path, bool]:
        """Write attachment data to temp file (fallback when saved_path unavailable).

        Args:
            attachment: The attachment with data to write.

        Returns:
            Tuple of (path, is_temp) - is_temp=True means caller should clean up.
        """
        import tempfile

        assert attachment.data is not None
        suffix = Path(attachment.filename or "document").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(attachment.data)
            return Path(tmp.name), True

    def _build_ocr_options(self) -> Any:
        """Build OCR options based on configured backend and languages.

        Returns:
            An OCR options instance for the configured backend.

        Raises:
            ValueError: If the configured backend is invalid or unavailable on this platform.
        """
        import sys

        backend = self.ocr_backend

        # Auto-select based on platform
        if backend == "auto":
            backend = "mac" if sys.platform == "darwin" else "easyocr"

        if backend == "mac":
            from docling.datamodel.pipeline_options import OcrMacOptions
            if sys.platform != "darwin":
                logger.warning("OcrMacOptions requested but not on macOS, falling back to easyocr")
                return self._build_easyocr_options()
            langs = [_OCRMAC_LANG_MAP.get(lang, f"{lang}-{lang.upper()}") for lang in self.ocr_languages]
            return OcrMacOptions(
                force_full_page_ocr=self.force_full_page_ocr,
                lang=langs,
            )

        if backend == "easyocr":
            return self._build_easyocr_options()

        if backend == "tesseract":
            from docling.datamodel.pipeline_options import TesseractOcrOptions
            langs = [_TESSERACT_LANG_MAP.get(lang, lang) for lang in self.ocr_languages]
            return TesseractOcrOptions(
                force_full_page_ocr=self.force_full_page_ocr,
                lang=langs,
            )

        if backend == "rapidocr":
            from docling.datamodel.pipeline_options import RapidOcrOptions
            return RapidOcrOptions(force_full_page_ocr=self.force_full_page_ocr)

        raise ValueError(f"Unknown OCR backend: {backend}")

    def _build_easyocr_options(self) -> Any:
        """Build EasyOCR options with configured languages.

        Returns:
            An EasyOcrOptions instance.
        """
        from docling.datamodel.pipeline_options import EasyOcrOptions
        return EasyOcrOptions(
            force_full_page_ocr=self.force_full_page_ocr,
            lang=list(self.ocr_languages),
        )

    async def _process_document(self, attachment: Attachment) -> str | None:
        """Process a single document attachment.

        Args:
            attachment: The document attachment to process.

        Returns:
            Info string about the processed document, or None if processing failed.
        """
        # Import docling (already checked for availability)
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as e:
            logger.error(f"Failed to import docling: {e}")
            return None

        # Type assertion - workspace_path is guaranteed non-None by caller check
        assert self.workspace_path is not None

        # Determine source file path
        if attachment.saved_path:
            try:
                source_path = resolve_sandboxed_path(
                    Path(self.workspace_path).resolve(),
                    attachment.saved_path,
                )
            except ValueError as e:
                logger.error(f"Invalid saved_path in document processing: {e}")
                return None
            is_temp = False
        else:
            # Fallback: write attachment.data to temp file
            source_path, is_temp = self._write_temp_file(attachment)

        try:
            # Build OCR options from config
            ocr_options = self._build_ocr_options()

            pipeline_options = PdfPipelineOptions(
                do_ocr=self.do_ocr,
                do_table_structure=self.do_table_structure,
                ocr_options=ocr_options,
            )

            # Create converter with optimized PDF processing
            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            )

            # Run docling conversion in thread pool (CPU-bound)
            # Apply document timeout if configured
            if self.document_timeout:
                async with asyncio.timeout(self.document_timeout):
                    result = await asyncio.to_thread(converter.convert, source_path)
            else:
                result = await asyncio.to_thread(converter.convert, source_path)

            # Export to markdown
            markdown = result.document.export_to_markdown()

            # Write markdown as sibling file (same directory, .md extension)
            md_path = source_path.with_suffix(".md")
            md_path.write_text(markdown, encoding="utf-8")
            logger.info(f"Saved markdown to {md_path}")

            # Calculate relative path for agent reference (only if not temp file)
            if not is_temp:
                relative_md_path = md_path.relative_to(Path(self.workspace_path).resolve())
                # Set metadata for processed path
                if not attachment.metadata:
                    attachment.metadata = {}
                attachment.metadata["processed_path"] = str(relative_md_path)
                md_reference = str(relative_md_path)
            else:
                # For temp files, just use the filename (not persisted)
                md_reference = md_path.name

            # Detect minimal/empty output
            markdown_stripped = markdown.strip()
            # Check if output is essentially empty (just image placeholders or whitespace)
            is_minimal = (
                len(markdown_stripped) < 50  # Very short output
                or markdown_stripped in ["<!-- image -->", ""]  # Exact empty cases
                or (
                    markdown_stripped.startswith("<!-- image -->")
                    and len(markdown_stripped) < 100
                )
            )

            if is_minimal:
                logger.warning(f"Docling produced minimal output for {attachment.filename}: {len(markdown)} bytes")
                result_parts = [f"[Converted to markdown: {md_reference}]"]
                result_parts.append(
                    "[Warning: Document conversion produced minimal output - "
                    "PDF may be image-only, encrypted, or have extraction issues. "
                    "Check the markdown file for details.]"
                )
                return "\n".join(result_parts)

            # Count tables and images (approximate from markdown)
            table_count = markdown.count("| --- |")
            image_count = markdown.count("![")

            # Build result info
            result_parts = [f"[Converted to markdown: {md_reference}]"]

            content_parts = ["full text"]
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
            # Clean up temp file if we created one (both source and markdown)
            if is_temp:
                try:
                    source_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to clean up temp file {source_path}: {e}")
                try:
                    md_path = source_path.with_suffix(".md")
                    if md_path.exists():
                        md_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to clean up temp markdown {md_path}: {e}")
