"""Tests for Whisper audio transcription processor."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from openpaw.builtins.processors.whisper import WhisperProcessor
from openpaw.model.message import Attachment, Message, MessageDirection


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    return tmp_path


@pytest.fixture
def processor(workspace_path: Path) -> WhisperProcessor:
    """Create a WhisperProcessor instance with test config."""
    config = {
        "workspace_path": str(workspace_path),
        "api_key": "test-api-key",
        "model": "whisper-1",
    }
    return WhisperProcessor(config=config)


@pytest.fixture
def processor_no_workspace() -> WhisperProcessor:
    """Create a WhisperProcessor without workspace_path."""
    config = {
        "api_key": "test-api-key",
    }
    return WhisperProcessor(config=config)


@pytest.fixture
def sample_message() -> Message:
    """Create a sample message without attachments."""
    return Message(
        id="123",
        channel="telegram",
        session_key="telegram:456",
        user_id="789",
        content="Please listen to this",
        direction=MessageDirection.INBOUND,
        timestamp=datetime.now(),
    )


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for Whisper."""
    mock_client = AsyncMock()
    mock_transcription = Mock()
    mock_transcription.text = "Hello, this is a test transcription."
    mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_transcription)
    return mock_client


def test_processor_metadata():
    """Verify WhisperProcessor metadata is correctly defined."""
    assert WhisperProcessor.metadata.name == "whisper"
    assert WhisperProcessor.metadata.display_name == "Whisper Audio Transcription"
    assert WhisperProcessor.metadata.group == "voice"
    assert WhisperProcessor.metadata.prerequisites.env_vars == ["OPENAI_API_KEY"]


def test_processor_no_workspace_path():
    """Verify processor handles missing workspace_path gracefully."""
    processor = WhisperProcessor(config={"api_key": "test-key"})
    assert processor.workspace_path is None


@pytest.mark.asyncio
async def test_pass_through_no_audio(processor: WhisperProcessor, sample_message: Message):
    """Verify messages without audio attachments pass through unchanged."""
    result = await processor.process_inbound(sample_message)

    assert result.message == sample_message
    assert not result.skip_agent


@pytest.mark.asyncio
async def test_pass_through_non_audio_attachment(processor: WhisperProcessor, sample_message: Message):
    """Verify messages with non-audio attachments pass through unchanged."""
    sample_message.attachments = [
        Attachment(
            type="document",
            data=b"fake pdf data",
            mime_type="application/pdf",
            filename="report.pdf",
        )
    ]

    result = await processor.process_inbound(sample_message)

    assert result.message == sample_message
    assert not result.skip_agent


@pytest.mark.asyncio
async def test_successful_transcription(
    processor: WhisperProcessor, sample_message: Message, mock_openai_client: AsyncMock
):
    """Verify successful audio transcription appends to message content."""
    sample_message.attachments = [
        Attachment(
            type="audio",
            data=b"fake audio data",
            mime_type="audio/ogg",
            filename="voice.ogg",
        )
    ]

    # Inject mock client
    processor._client = mock_openai_client

    result = await processor.process_inbound(sample_message)

    # Verify transcription in content
    assert "[Voice message]: Hello, this is a test transcription." in result.message.content
    assert "Please listen to this" in result.message.content
    assert result.message.metadata.get("transcribed") is True


@pytest.mark.asyncio
async def test_transcription_with_caption(processor: WhisperProcessor, mock_openai_client: AsyncMock):
    """Verify transcription preserves existing message content."""
    message = Message(
        id="123",
        channel="telegram",
        session_key="telegram:456",
        user_id="789",
        content="Check out this voice note",
        direction=MessageDirection.INBOUND,
        timestamp=datetime.now(),
        attachments=[
            Attachment(
                type="audio",
                data=b"fake audio data",
                mime_type="audio/ogg",
            )
        ],
    )

    processor._client = mock_openai_client

    result = await processor.process_inbound(message)

    # Both original content and transcription present
    assert "Check out this voice note" in result.message.content
    assert "[Voice message]: Hello, this is a test transcription." in result.message.content


@pytest.mark.asyncio
async def test_transcription_failure(processor: WhisperProcessor, sample_message: Message):
    """Verify graceful handling of transcription API errors."""
    sample_message.attachments = [
        Attachment(
            type="audio",
            data=b"fake audio data",
            mime_type="audio/ogg",
            filename="voice.ogg",
        )
    ]

    # Mock client that raises error
    mock_client = AsyncMock()
    mock_client.audio.transcriptions.create = AsyncMock(side_effect=Exception("API error"))
    processor._client = mock_client

    result = await processor.process_inbound(sample_message)

    # Error message in content
    assert "[Voice message: Unable to transcribe audio" in result.message.content
    assert "API error" in result.message.content


@pytest.mark.asyncio
async def test_attachment_no_data(processor: WhisperProcessor, sample_message: Message):
    """Verify handling of audio attachment without data."""
    sample_message.attachments = [
        Attachment(
            type="audio",
            data=None,  # No data
            mime_type="audio/ogg",
            filename="voice.ogg",
        )
    ]

    result = await processor.process_inbound(sample_message)

    # Error note in content
    assert "[Voice message: Unable to transcribe audio" in result.message.content
    assert "has no data" in result.message.content


@pytest.mark.asyncio
async def test_multiple_audio_attachments(processor: WhisperProcessor, sample_message: Message):
    """Verify transcription of multiple audio attachments."""
    sample_message.attachments = [
        Attachment(
            type="audio",
            data=b"fake audio data 1",
            mime_type="audio/ogg",
            filename="voice1.ogg",
        ),
        Attachment(
            type="audio",
            data=b"fake audio data 2",
            mime_type="audio/mp3",
            filename="voice2.mp3",
        ),
    ]

    # Mock client with different transcriptions
    mock_client = AsyncMock()
    mock_transcription_1 = Mock()
    mock_transcription_1.text = "First transcription."
    mock_transcription_2 = Mock()
    mock_transcription_2.text = "Second transcription."

    mock_client.audio.transcriptions.create = AsyncMock(side_effect=[mock_transcription_1, mock_transcription_2])
    processor._client = mock_client

    result = await processor.process_inbound(sample_message)

    # Both transcriptions present
    assert "First transcription." in result.message.content
    assert "Second transcription." in result.message.content
    assert result.message.metadata.get("transcribed") is True


@pytest.mark.asyncio
async def test_partial_transcription_failure(processor: WhisperProcessor, sample_message: Message):
    """Verify handling when some transcriptions succeed and others fail."""
    sample_message.attachments = [
        Attachment(
            type="audio",
            data=b"fake audio data 1",
            mime_type="audio/ogg",
            filename="voice1.ogg",
        ),
        Attachment(
            type="audio",
            data=b"fake audio data 2",
            mime_type="audio/ogg",
            filename="voice2.ogg",
        ),
    ]

    # First succeeds, second fails
    mock_client = AsyncMock()
    mock_transcription = Mock()
    mock_transcription.text = "Successful transcription."
    mock_client.audio.transcriptions.create = AsyncMock(
        side_effect=[mock_transcription, Exception("Second audio failed")]
    )
    processor._client = mock_client

    result = await processor.process_inbound(sample_message)

    # Success message and failure note both present
    assert "Successful transcription." in result.message.content
    assert "[Note: 1 audio file could not be transcribed" in result.message.content
    assert "Second audio failed" in result.message.content


@pytest.mark.asyncio
async def test_transcript_saved_to_disk(
    processor: WhisperProcessor,
    sample_message: Message,
    workspace_path: Path,
    mock_openai_client: AsyncMock,
):
    """Verify transcript is saved as sibling .txt file."""
    # Create the saved audio file on disk
    uploads_dir = workspace_path / "data" / "uploads" / "2026-02-07"
    uploads_dir.mkdir(parents=True)
    audio_path = uploads_dir / "voice_123.ogg"
    audio_path.write_bytes(b"fake audio data")

    sample_message.attachments = [
        Attachment(
            type="audio",
            data=b"fake audio data",
            mime_type="audio/ogg",
            filename="voice_123.ogg",
            saved_path="data/uploads/2026-02-07/voice_123.ogg",
        )
    ]

    processor._client = mock_openai_client

    result = await processor.process_inbound(sample_message)

    # Verify transcript file exists
    txt_path = uploads_dir / "voice_123.txt"
    assert txt_path.exists()
    assert txt_path.read_text(encoding="utf-8") == "Hello, this is a test transcription."

    # Verify processed_path in metadata
    attachment = result.message.attachments[0]
    assert attachment.metadata.get("processed_path") == "data/uploads/2026-02-07/voice_123.txt"


@pytest.mark.asyncio
async def test_transcript_no_saved_path(
    processor: WhisperProcessor, sample_message: Message, mock_openai_client: AsyncMock
):
    """Verify no disk write when saved_path is not set."""
    sample_message.attachments = [
        Attachment(
            type="audio",
            data=b"fake audio data",
            mime_type="audio/ogg",
            filename="voice.ogg",
            # No saved_path
        )
    ]

    processor._client = mock_openai_client

    result = await processor.process_inbound(sample_message)

    # Transcription succeeds but no file written
    assert "[Voice message]: Hello, this is a test transcription." in result.message.content
    assert "processed_path" not in result.message.attachments[0].metadata


@pytest.mark.asyncio
async def test_transcript_no_workspace_path(
    processor_no_workspace: WhisperProcessor,
    sample_message: Message,
    tmp_path: Path,
    mock_openai_client: AsyncMock,
):
    """Verify no disk write when workspace_path is not configured."""
    # Create audio file (won't be used for saving)
    uploads_dir = tmp_path / "data" / "uploads" / "2026-02-07"
    uploads_dir.mkdir(parents=True)
    audio_path = uploads_dir / "voice_123.ogg"
    audio_path.write_bytes(b"fake audio data")

    sample_message.attachments = [
        Attachment(
            type="audio",
            data=b"fake audio data",
            mime_type="audio/ogg",
            filename="voice_123.ogg",
            saved_path="data/uploads/2026-02-07/voice_123.ogg",
        )
    ]

    processor_no_workspace._client = mock_openai_client

    result = await processor_no_workspace.process_inbound(sample_message)

    # Transcription succeeds but no file written
    assert "[Voice message]: Hello, this is a test transcription." in result.message.content
    assert "processed_path" not in result.message.attachments[0].metadata


@pytest.mark.asyncio
async def test_transcript_disk_write_failure(
    processor: WhisperProcessor,
    sample_message: Message,
    workspace_path: Path,
    mock_openai_client: AsyncMock,
):
    """Verify graceful degradation when disk write fails."""
    # Don't create the audio file on disk - will cause path resolution error
    sample_message.attachments = [
        Attachment(
            type="audio",
            data=b"fake audio data",
            mime_type="audio/ogg",
            filename="voice_123.ogg",
            saved_path="uploads/2026-02-07/voice_123.ogg",  # Path doesn't exist
        )
    ]

    processor._client = mock_openai_client

    result = await processor.process_inbound(sample_message)

    # Transcription still succeeds despite disk write failure
    assert "[Voice message]: Hello, this is a test transcription." in result.message.content
    assert result.message.metadata.get("transcribed") is True


@pytest.mark.asyncio
async def test_metadata_transcribed_flag(
    processor: WhisperProcessor, sample_message: Message, mock_openai_client: AsyncMock
):
    """Verify transcribed flag is set in message metadata."""
    sample_message.attachments = [
        Attachment(
            type="audio",
            data=b"fake audio data",
            mime_type="audio/ogg",
        )
    ]

    processor._client = mock_openai_client

    result = await processor.process_inbound(sample_message)

    assert result.message.metadata.get("transcribed") is True


@pytest.mark.asyncio
async def test_mime_type_detection(processor: WhisperProcessor, sample_message: Message, mock_openai_client: AsyncMock):
    """Verify correct file extension detection from MIME types."""
    mime_types = [
        ("audio/ogg", "ogg"),
        ("audio/mpeg", "mp3"),
        ("audio/mp4", "m4a"),
        ("audio/wav", "wav"),
        ("audio/webm", "webm"),
        ("audio/unknown", "ogg"),  # Default fallback
    ]

    processor._client = mock_openai_client

    for mime_type, expected_ext in mime_types:
        attachment = Attachment(
            type="audio",
            data=b"fake audio data",
            mime_type=mime_type,
        )

        # Call _transcribe to verify file extension handling
        text = await processor._transcribe(attachment)

        # Verify the create call was made with correct extension
        call_kwargs = mock_openai_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["file"].name.endswith(f".{expected_ext}")
        assert text == "Hello, this is a test transcription."


@pytest.mark.asyncio
async def test_empty_transcription_result(processor: WhisperProcessor, sample_message: Message):
    """Verify handling of empty transcription response."""
    sample_message.attachments = [
        Attachment(
            type="audio",
            data=b"fake audio data",
            mime_type="audio/ogg",
        )
    ]

    # Mock client returning empty text
    mock_client = AsyncMock()
    mock_transcription = Mock()
    mock_transcription.text = ""
    mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_transcription)
    processor._client = mock_client

    result = await processor.process_inbound(sample_message)

    # Error message for empty transcription
    assert "[Voice message: Unable to transcribe audio" in result.message.content
    assert "Transcription returned empty" in result.message.content
