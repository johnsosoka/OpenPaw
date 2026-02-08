"""Tests for Docling document processor."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from openpaw.builtins.processors.docling import DoclingProcessor
from openpaw.channels.base import Attachment, Message, MessageDirection


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    return tmp_path


@pytest.fixture
def processor(workspace_path: Path) -> DoclingProcessor:
    """Create a DoclingProcessor instance with test config."""
    config = {
        "workspace_path": workspace_path,
        "max_file_size": 50 * 1024 * 1024,  # 50 MB
    }
    return DoclingProcessor(config=config)


@pytest.fixture
def sample_message() -> Message:
    """Create a sample message without attachments."""
    return Message(
        id="123",
        channel="telegram",
        session_key="telegram:456",
        user_id="789",
        content="Please review this document",
        direction=MessageDirection.INBOUND,
        timestamp=datetime.now(),
    )


@pytest.fixture
def mock_docling():
    """Mock the docling module for testing."""
    # Create mock objects
    mock_document = Mock()
    mock_document.export_to_markdown = Mock(return_value="# Test Document\n\nContent here")

    mock_result = Mock()
    mock_result.document = mock_document

    mock_converter_instance = Mock()
    mock_converter_instance.convert = Mock(return_value=mock_result)

    mock_converter_class = Mock(return_value=mock_converter_instance)

    # Create a fake docling module
    mock_docling_module = Mock()
    mock_docling_module.document_converter = Mock()
    mock_docling_module.document_converter.DocumentConverter = mock_converter_class

    return {
        "module": mock_docling_module,
        "converter_class": mock_converter_class,
        "converter_instance": mock_converter_instance,
        "result": mock_result,
        "document": mock_document,
    }


def test_processor_metadata():
    """Verify DoclingProcessor metadata is correctly defined."""
    assert DoclingProcessor.metadata.name == "docling"
    assert DoclingProcessor.metadata.display_name == "Docling Document Processor"
    assert DoclingProcessor.metadata.group == "document"
    assert not DoclingProcessor.metadata.prerequisites.env_vars


def test_processor_no_workspace_path():
    """Verify processor handles missing workspace_path gracefully."""
    processor = DoclingProcessor(config={})
    assert processor.workspace_path is None


@pytest.mark.asyncio
async def test_pass_through_no_attachments(processor: DoclingProcessor, sample_message: Message):
    """Verify messages without attachments pass through unchanged."""
    result = await processor.process_inbound(sample_message)

    assert result.message == sample_message
    assert not result.skip_agent
    assert not result.attachments


@pytest.mark.asyncio
async def test_pass_through_unsupported_attachment(processor: DoclingProcessor, sample_message: Message):
    """Verify unsupported file types pass through unchanged."""
    # Add an audio attachment (not supported by Docling)
    sample_message.attachments = [
        Attachment(
            type="audio",
            data=b"fake audio data",
            mime_type="audio/ogg",
            filename="voice.ogg",
        )
    ]

    result = await processor.process_inbound(sample_message)

    assert result.message == sample_message
    assert not result.skip_agent


@pytest.mark.asyncio
async def test_supported_mime_types(processor: DoclingProcessor, sample_message: Message):
    """Verify supported MIME types are detected correctly."""
    supported_types = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/html",
        "image/png",
        "image/jpeg",
        "image/tiff",
    ]

    for mime_type in supported_types:
        attachment = Attachment(
            type="document",
            data=b"fake data",
            mime_type=mime_type,
            filename="test.pdf",
        )
        assert processor._is_supported_document(attachment)


@pytest.mark.asyncio
async def test_supported_extensions_fallback(processor: DoclingProcessor):
    """Verify file extension fallback when MIME type is missing."""
    supported_extensions = [".pdf", ".docx", ".pptx", ".xlsx", ".html", ".png", ".jpg", ".jpeg", ".tiff"]

    for ext in supported_extensions:
        attachment = Attachment(
            type="document",
            data=b"fake data",
            filename=f"test{ext}",
        )
        assert processor._is_supported_document(attachment)


@pytest.mark.asyncio
async def test_docling_not_installed(processor: DoclingProcessor, sample_message: Message):
    """Verify graceful handling when docling package is missing."""
    sample_message.attachments = [
        Attachment(
            type="document",
            data=b"fake pdf data",
            mime_type="application/pdf",
            filename="report.pdf",
        )
    ]

    with patch.object(processor, "_check_docling_available", return_value=False):
        result = await processor.process_inbound(sample_message)

    assert "docling not installed" in result.message.content
    assert result.message.metadata.get("docling_unavailable") is True
    assert not result.skip_agent


@pytest.mark.asyncio
async def test_attachment_without_data(processor: DoclingProcessor, sample_message: Message):
    """Verify handling of attachment without data."""
    sample_message.attachments = [
        Attachment(
            type="document",
            data=None,  # No data
            mime_type="application/pdf",
            filename="report.pdf",
        )
    ]

    with patch.object(processor, "_check_docling_available", return_value=True):
        result = await processor.process_inbound(sample_message)

    assert "has no data" in result.message.content or "could not be processed" in result.message.content


@pytest.mark.asyncio
async def test_file_too_large(processor: DoclingProcessor, sample_message: Message):
    """Verify file size limit enforcement."""
    # Create attachment larger than 50 MB
    large_data = b"x" * (51 * 1024 * 1024)
    sample_message.attachments = [
        Attachment(
            type="document",
            data=large_data,
            mime_type="application/pdf",
            filename="huge_report.pdf",
        )
    ]

    with patch.object(processor, "_check_docling_available", return_value=True):
        result = await processor.process_inbound(sample_message)

    assert "too large" in result.message.content


@pytest.mark.asyncio
async def test_successful_processing(processor: DoclingProcessor, sample_message: Message, workspace_path: Path, mock_docling: dict):
    """Verify successful document processing with mocked docling."""
    pdf_data = b"%PDF-1.4 fake pdf content"
    sample_message.attachments = [
        Attachment(
            type="document",
            data=pdf_data,
            mime_type="application/pdf",
            filename="quarterly_report.pdf",
        )
    ]

    # Update document mock to return expected content
    mock_docling["document"].export_to_markdown.return_value = "# Quarterly Report\n\nContent here"

    # Mock the import and processing
    with patch.object(processor, "_check_docling_available", return_value=True), \
         patch.dict(sys.modules, {"docling": mock_docling["module"], "docling.document_converter": mock_docling["module"].document_converter}), \
         patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:

        mock_to_thread.return_value = mock_docling["result"]

        result = await processor.process_inbound(sample_message)

    # Verify message enrichment
    assert "Document received: quarterly_report.pdf" in result.message.content
    assert "Processed to: inbox/" in result.message.content
    assert "document.md" in result.message.content
    assert "User caption: Please review this document" in result.message.content

    # Verify metadata
    assert result.message.metadata.get("docling_processed") is True
    assert result.message.metadata.get("processed_count") == 1

    # Verify inbox structure
    today = datetime.now().strftime("%Y-%m-%d")
    inbox_dir = workspace_path / "inbox" / today / "quarterly_report"
    assert inbox_dir.exists()
    md_file = inbox_dir / "document.md"
    assert md_file.exists()
    assert "# Quarterly Report" in md_file.read_text()


@pytest.mark.asyncio
async def test_filename_sanitization(processor: DoclingProcessor):
    """Verify filename sanitization for directory creation."""
    test_cases = [
        ("My Report.pdf", "my_report"),
        ("Q1-2024 Financial.pdf", "q1-2024_financial"),
        ("report (final).pdf", "report_final"),
        ("file@#$%^&*.pdf", "file"),
        ("a" * 150 + ".pdf", "a" * 100),  # Length limit
        ("..pdf", "document"),  # Fallback for empty
    ]

    for original, expected in test_cases:
        sanitized = processor._sanitize_filename(original)
        assert sanitized == expected, f"Failed for {original}: got {sanitized}, expected {expected}"


@pytest.mark.asyncio
async def test_multiple_documents(processor: DoclingProcessor, sample_message: Message, workspace_path: Path, mock_docling: dict):
    """Verify processing multiple documents in one message."""
    sample_message.attachments = [
        Attachment(
            type="document",
            data=b"%PDF-1.4 report",
            mime_type="application/pdf",
            filename="report1.pdf",
        ),
        Attachment(
            type="document",
            data=b"<docx>",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="report2.docx",
        ),
    ]

    # Update document mock
    mock_docling["document"].export_to_markdown.return_value = "# Document Content"

    with patch.object(processor, "_check_docling_available", return_value=True), \
         patch.dict(sys.modules, {"docling": mock_docling["module"], "docling.document_converter": mock_docling["module"].document_converter}), \
         patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:

        mock_to_thread.return_value = mock_docling["result"]

        result = await processor.process_inbound(sample_message)

    # Verify both documents processed
    assert "report1.pdf" in result.message.content
    assert "report2.docx" in result.message.content
    assert result.message.metadata.get("processed_count") == 2


@pytest.mark.asyncio
async def test_conversion_error_handling(processor: DoclingProcessor, sample_message: Message, mock_docling: dict):
    """Verify graceful handling of docling conversion errors."""
    sample_message.attachments = [
        Attachment(
            type="document",
            data=b"corrupt pdf data",
            mime_type="application/pdf",
            filename="corrupt.pdf",
        )
    ]

    with patch.object(processor, "_check_docling_available", return_value=True), \
         patch.dict(sys.modules, {"docling": mock_docling["module"], "docling.document_converter": mock_docling["module"].document_converter}), \
         patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:

        mock_to_thread.side_effect = Exception("Conversion failed")

        result = await processor.process_inbound(sample_message)

    # Should include error note
    assert "could not be processed" in result.message.content


@pytest.mark.asyncio
async def test_no_workspace_path_pass_through(sample_message: Message):
    """Verify pass-through when workspace_path is not configured."""
    processor = DoclingProcessor(config=None)

    sample_message.attachments = [
        Attachment(
            type="document",
            data=b"fake pdf",
            mime_type="application/pdf",
            filename="test.pdf",
        )
    ]

    result = await processor.process_inbound(sample_message)

    assert result.message == sample_message


@pytest.mark.asyncio
async def test_table_and_image_detection(processor: DoclingProcessor, sample_message: Message, mock_docling: dict):
    """Verify detection of tables and images in processed markdown."""
    sample_message.attachments = [
        Attachment(
            type="document",
            data=b"fake pdf",
            mime_type="application/pdf",
            filename="report.pdf",
        )
    ]

    # Mock docling with markdown containing tables and images
    markdown_content = """
# Report

![Figure 1](image1.png)

| Col 1 | Col 2 |
| --- | --- |
| A | B |

![Figure 2](image2.png)
"""

    mock_docling["document"].export_to_markdown.return_value = markdown_content

    with patch.object(processor, "_check_docling_available", return_value=True), \
         patch.dict(sys.modules, {"docling": mock_docling["module"], "docling.document_converter": mock_docling["module"].document_converter}), \
         patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:

        mock_to_thread.return_value = mock_docling["result"]

        result = await processor.process_inbound(sample_message)

    # Verify table and image counts are reported
    assert "1 tables" in result.message.content or "1 table" in result.message.content
    assert "2 images" in result.message.content
