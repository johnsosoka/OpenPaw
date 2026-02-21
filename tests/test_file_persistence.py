"""Tests for FilePersistenceProcessor."""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from openpaw.builtins.processors.file_persistence import FilePersistenceProcessor
from openpaw.model.message import Attachment, Message, MessageDirection


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def processor(temp_workspace):
    """Create a FilePersistenceProcessor with temp workspace."""
    config = {"workspace_path": temp_workspace}
    return FilePersistenceProcessor(config)


@pytest.fixture
def sample_message():
    """Create a sample message."""
    return Message(
        id="msg123",
        channel="telegram",
        session_key="telegram:user123",
        user_id="user123",
        content="Check out this file!",
        direction=MessageDirection.INBOUND,
    )


@pytest.mark.asyncio
async def test_single_document_saved(processor, sample_message, temp_workspace):
    """Test that a single document attachment is saved correctly."""
    # Create attachment
    file_data = b"PDF content here"
    attachment = Attachment(
        type="document",
        data=file_data,
        filename="report.pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment]

    # Process
    result = await processor.process_inbound(sample_message)

    # Verify file was saved
    uploads_dir = Path(temp_workspace) / "uploads"
    assert uploads_dir.exists()

    # Find the saved file (date-based subdirectory)
    saved_files = list(uploads_dir.rglob("*.pdf"))
    assert len(saved_files) == 1
    saved_file = saved_files[0]
    assert saved_file.read_bytes() == file_data
    assert saved_file.name == "report.pdf"

    # Verify saved_path is set
    assert attachment.saved_path is not None
    assert attachment.saved_path.startswith("uploads/")
    assert attachment.saved_path.endswith("report.pdf")

    # Verify content enrichment
    assert "[File received: report.pdf" in result.message.content
    assert "[Saved to:" in result.message.content
    assert "Check out this file!" in result.message.content

    # Verify metadata
    assert "uploaded_files" in result.message.metadata
    assert len(result.message.metadata["uploaded_files"]) == 1
    file_meta = result.message.metadata["uploaded_files"][0]
    assert file_meta["filename"] == "report.pdf"
    assert file_meta["mime_type"] == "application/pdf"
    assert file_meta["size_bytes"] == len(file_data)


@pytest.mark.asyncio
async def test_multiple_attachments(processor, sample_message, temp_workspace):
    """Test that multiple attachments are all saved and listed."""
    # Create multiple attachments
    attachments = [
        Attachment(
            type="document",
            data=b"PDF data",
            filename="report.pdf",
            mime_type="application/pdf",
        ),
        Attachment(
            type="image",
            data=b"PNG data",
            filename="screenshot.png",
            mime_type="image/png",
        ),
        Attachment(
            type="audio",
            data=b"OGG data",
            filename="voice.ogg",
            mime_type="audio/ogg",
        ),
    ]
    sample_message.attachments = attachments

    # Process
    result = await processor.process_inbound(sample_message)

    # Verify all files saved
    uploads_dir = Path(temp_workspace) / "uploads"
    saved_files = list(uploads_dir.rglob("*"))
    saved_files = [f for f in saved_files if f.is_file()]
    assert len(saved_files) == 3

    # Verify all saved_paths set
    for attachment in attachments:
        assert attachment.saved_path is not None
        assert attachment.saved_path.startswith("uploads/")

    # Verify all listed in content
    assert "report.pdf" in result.message.content
    assert "screenshot.png" in result.message.content
    assert "voice.ogg" in result.message.content

    # Verify metadata
    assert len(result.message.metadata["uploaded_files"]) == 3


@pytest.mark.asyncio
async def test_audio_no_filename(processor, sample_message, temp_workspace):
    """Test that audio with no filename generates voice_{id}.ogg."""
    attachment = Attachment(
        type="audio",
        data=b"Audio data",
        filename=None,
        mime_type="audio/ogg",
    )
    sample_message.attachments = [attachment]

    # Process
    await processor.process_inbound(sample_message)

    # Verify filename generated
    uploads_dir = Path(temp_workspace) / "uploads"
    saved_files = list(uploads_dir.rglob("*.ogg"))
    assert len(saved_files) == 1
    assert saved_files[0].name.startswith("voice_msg123")
    assert saved_files[0].name.endswith(".ogg")


@pytest.mark.asyncio
async def test_photo_no_filename(processor, sample_message, temp_workspace):
    """Test that photo with no filename generates photo_{id}.jpg."""
    attachment = Attachment(
        type="image",
        data=b"Image data",
        filename=None,
        mime_type="image/jpeg",
    )
    sample_message.attachments = [attachment]

    # Process
    await processor.process_inbound(sample_message)

    # Verify filename generated
    uploads_dir = Path(temp_workspace) / "uploads"
    saved_files = list(uploads_dir.rglob("*.jpg"))
    assert len(saved_files) == 1
    assert saved_files[0].name.startswith("photo_msg123")
    assert saved_files[0].name.endswith(".jpg")


@pytest.mark.asyncio
async def test_file_too_large(processor, sample_message, temp_workspace):
    """Test that files exceeding max_file_size are skipped with error note."""
    # Set small max file size
    processor.max_file_size = 100

    # Create large file
    attachment = Attachment(
        type="document",
        data=b"x" * 1000,  # 1000 bytes, exceeds limit
        filename="large.pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment]

    # Process
    result = await processor.process_inbound(sample_message)

    # Verify file NOT saved
    uploads_dir = Path(temp_workspace) / "uploads"
    if uploads_dir.exists():
        saved_files = list(uploads_dir.rglob("*.pdf"))
        assert len(saved_files) == 0

    # Verify error note in content
    assert "[File too large:" in result.message.content
    assert "large.pdf" in result.message.content


@pytest.mark.asyncio
async def test_no_workspace_path():
    """Test that processor passes through unchanged when no workspace_path."""
    processor = FilePersistenceProcessor(config={})
    message = Message(
        id="msg123",
        channel="telegram",
        session_key="telegram:user123",
        user_id="user123",
        content="Test",
        direction=MessageDirection.INBOUND,
        attachments=[
            Attachment(
                type="document",
                data=b"data",
                filename="test.pdf",
            )
        ],
    )

    result = await processor.process_inbound(message)

    # Message should be unchanged
    assert result.message.content == "Test"
    assert result.message.attachments[0].saved_path is None


@pytest.mark.asyncio
async def test_attachment_no_data(processor, sample_message, temp_workspace):
    """Test that attachments without data are skipped."""
    attachment = Attachment(
        type="document",
        data=None,  # No data
        url="https://example.com/file.pdf",
        filename="remote.pdf",
    )
    sample_message.attachments = [attachment]

    # Process
    result = await processor.process_inbound(sample_message)

    # No files should be saved
    uploads_dir = Path(temp_workspace) / "uploads"
    if uploads_dir.exists():
        saved_files = list(uploads_dir.rglob("*"))
        saved_files = [f for f in saved_files if f.is_file()]
        assert len(saved_files) == 0

    # Message content unchanged
    assert result.message.content == sample_message.content


@pytest.mark.asyncio
async def test_filename_collision(processor, sample_message, temp_workspace):
    """Test that filename collisions get dedup suffix applied."""
    # Save first file
    attachment1 = Attachment(
        type="document",
        data=b"First file",
        filename="report.pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment1]
    await processor.process_inbound(sample_message)

    # Save second file with same name
    attachment2 = Attachment(
        type="document",
        data=b"Second file",
        filename="report.pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment2]
    await processor.process_inbound(sample_message)

    # Verify both files exist
    uploads_dir = Path(temp_workspace) / "uploads"
    saved_files = list(uploads_dir.rglob("*.pdf"))
    assert len(saved_files) == 2

    # One should be report.pdf, other should be report(1).pdf
    filenames = {f.name for f in saved_files}
    assert "report.pdf" in filenames
    assert "report(1).pdf" in filenames


@pytest.mark.asyncio
async def test_content_enrichment_format(processor, sample_message, temp_workspace):
    """Test that content enrichment format matches spec."""
    attachment = Attachment(
        type="document",
        data=b"x" * 2_400_000,  # ~2.3 MB
        filename="report.pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment]

    # Process
    result = await processor.process_inbound(sample_message)

    # Check format
    content_lines = result.message.content.split("\n")
    assert len(content_lines) >= 2

    # First line: [File received: ...]
    assert content_lines[0].startswith("[File received: report.pdf")
    assert "2.3 MB" in content_lines[0] or "2.2 MB" in content_lines[0]  # Float precision
    assert "application/pdf" in content_lines[0]

    # Second line: [Saved to: ...]
    assert content_lines[1].startswith("[Saved to:")
    assert "uploads/" in content_lines[1]
    assert "report.pdf" in content_lines[1]

    # User caption preserved
    assert "Check out this file!" in result.message.content


@pytest.mark.asyncio
async def test_metadata_populated(processor, sample_message, temp_workspace):
    """Test that uploaded_files metadata is populated correctly."""
    attachment = Attachment(
        type="document",
        data=b"PDF data",
        filename="test.pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment]

    # Process
    result = await processor.process_inbound(sample_message)

    # Check metadata
    assert "uploaded_files" in result.message.metadata
    files = result.message.metadata["uploaded_files"]
    assert len(files) == 1

    file_meta = files[0]
    assert file_meta["filename"] == "test.pdf"
    assert file_meta["mime_type"] == "application/pdf"
    assert file_meta["size_bytes"] == len(b"PDF data")
    assert "original_path" in file_meta
    assert file_meta["original_path"].startswith("uploads/")


@pytest.mark.asyncio
async def test_clear_data_after_save(temp_workspace, sample_message):
    """Test that clear_data_after_save=True clears attachment.data."""
    processor = FilePersistenceProcessor(
        config={"workspace_path": temp_workspace, "clear_data_after_save": True}
    )

    attachment = Attachment(
        type="document",
        data=b"PDF data",
        filename="test.pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment]

    # Process
    await processor.process_inbound(sample_message)

    # Verify data is None
    assert attachment.data is None


@pytest.mark.asyncio
async def test_clear_data_default_false(processor, sample_message):
    """Test that clear_data_after_save defaults to False."""
    attachment = Attachment(
        type="document",
        data=b"PDF data",
        filename="test.pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment]

    # Process
    await processor.process_inbound(sample_message)

    # Verify data is still present
    assert attachment.data is not None
    assert attachment.data == b"PDF data"


@pytest.mark.asyncio
async def test_disk_write_error(processor, sample_message, temp_workspace):
    """Test graceful degradation when disk write fails."""
    attachment = Attachment(
        type="document",
        data=b"PDF data",
        filename="test.pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment]

    # Mock write_bytes to raise exception
    with patch.object(Path, "write_bytes", side_effect=OSError("Disk full")):
        result = await processor.process_inbound(sample_message)

    # Message should contain error note
    assert "[Error saving file:" in result.message.content


@pytest.mark.asyncio
async def test_empty_content_with_file(processor, temp_workspace):
    """Test that files are saved even when message content is empty."""
    message = Message(
        id="msg123",
        channel="telegram",
        session_key="telegram:user123",
        user_id="user123",
        content="",  # Empty content
        direction=MessageDirection.INBOUND,
        attachments=[
            Attachment(
                type="document",
                data=b"PDF data",
                filename="test.pdf",
                mime_type="application/pdf",
            )
        ],
    )

    result = await processor.process_inbound(message)

    # File info should be in content
    assert "[File received:" in result.message.content
    assert "[Saved to:" in result.message.content
    # No user caption should be added
    assert "User caption:" not in result.message.content


@pytest.mark.asyncio
async def test_mime_type_fallback(processor, sample_message, temp_workspace):
    """Test that MIME type is guessed for files without mime_type."""
    attachment = Attachment(
        type="document",
        data=b"Data",
        filename="test.json",
        mime_type=None,  # No MIME type
    )
    sample_message.attachments = [attachment]

    await processor.process_inbound(sample_message)

    # File should still be saved
    uploads_dir = Path(temp_workspace) / "uploads"
    saved_files = list(uploads_dir.rglob("*.json"))
    assert len(saved_files) == 1


@pytest.mark.asyncio
async def test_binary_file_no_extension(processor, sample_message, temp_workspace):
    """Test that binary files with no extension get .bin."""
    attachment = Attachment(
        type="file",
        data=b"Binary data",
        filename=None,
        mime_type=None,
    )
    sample_message.attachments = [attachment]

    await processor.process_inbound(sample_message)

    # Should generate upload_{id}.bin
    uploads_dir = Path(temp_workspace) / "uploads"
    saved_files = list(uploads_dir.rglob("*.bin"))
    assert len(saved_files) == 1
    assert saved_files[0].name.startswith("upload_msg123")


@pytest.mark.asyncio
async def test_date_partitioning(processor, sample_message, temp_workspace):
    """Test that files are saved in date-based subdirectories."""
    from openpaw.core.timezone import workspace_now

    attachment = Attachment(
        type="document",
        data=b"PDF data",
        filename="test.pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment]

    await processor.process_inbound(sample_message)

    # Verify date-based directory (processor defaults to UTC timezone)
    today = workspace_now("UTC").strftime("%Y-%m-%d")
    expected_dir = Path(temp_workspace) / "uploads" / today
    assert expected_dir.exists()
    assert expected_dir.is_dir()

    # Verify file is in that directory
    saved_files = list(expected_dir.glob("*.pdf"))
    assert len(saved_files) == 1


@pytest.mark.asyncio
async def test_special_characters_sanitized(processor, sample_message, temp_workspace):
    """Test that filenames with special characters are sanitized."""
    attachment = Attachment(
        type="document",
        data=b"PDF data",
        filename="My Report (Q3) [Final].pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment]

    await processor.process_inbound(sample_message)

    # Filename should be sanitized
    uploads_dir = Path(temp_workspace) / "uploads"
    saved_files = list(uploads_dir.rglob("*.pdf"))
    assert len(saved_files) == 1

    # Should be lowercase, underscores instead of spaces, no brackets
    saved_name = saved_files[0].name
    assert " " not in saved_name
    assert "(" not in saved_name
    assert "[" not in saved_name
    assert saved_name.islower() or saved_name == saved_name.lower()


@pytest.mark.asyncio
async def test_timezone_aware_date_partition(temp_workspace, sample_message):
    """Test that date partition uses workspace timezone, not server timezone.

    Scenario: File uploaded at 11:30pm Mountain Time on Feb 7.
    If server is UTC, that's 06:30am UTC on Feb 8.
    File should land in 2026-02-07 folder (Mountain Time), not 2026-02-08.
    """
    from openpaw.core.timezone import workspace_now

    # Create processor with Mountain Time timezone
    processor = FilePersistenceProcessor(
        config={
            "workspace_path": temp_workspace,
            "timezone": "America/Denver"
        }
    )

    # Mock workspace_now to return 11:30pm Mountain Time on Feb 7
    # (which would be 06:30am UTC on Feb 8)
    mock_mountain_time = datetime(
        2026, 2, 7, 23, 30, 0,
        tzinfo=ZoneInfo("America/Denver")
    )

    attachment = Attachment(
        type="document",
        data=b"Late night upload",
        filename="report.pdf",
        mime_type="application/pdf",
    )
    sample_message.attachments = [attachment]

    # Mock workspace_now to return our test timestamp
    with patch("openpaw.builtins.processors.file_persistence.workspace_now") as mock_now:
        mock_now.return_value = mock_mountain_time
        await processor.process_inbound(sample_message)

    # Verify file landed in 2026-02-07 (Mountain Time date), NOT 2026-02-08
    expected_dir = Path(temp_workspace) / "uploads" / "2026-02-07"
    assert expected_dir.exists(), "Expected Mountain Time date directory to exist"

    saved_files = list(expected_dir.glob("*.pdf"))
    assert len(saved_files) == 1, "Expected one file in Mountain Time date directory"
    assert saved_files[0].name == "report.pdf"

    # Verify no file in the UTC date directory
    utc_dir = Path(temp_workspace) / "uploads" / "2026-02-08"
    assert not utc_dir.exists(), "UTC date directory should not exist"
