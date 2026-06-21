"""Processor output templates for file handling and transcription."""

from langchain_core.prompts import PromptTemplate

# File persistence processor output
FILE_RECEIVED_TEMPLATE = PromptTemplate(
    template="[File received: {filename} ({size}, {mime_type})]\n[Saved to: {saved_path}]",
    input_variables=["filename", "size", "mime_type", "saved_path"],
)

# Whisper transcription success
VOICE_MESSAGE_TEMPLATE = PromptTemplate(
    template="[Voice message]: {text}",
    input_variables=["text"],
)

# Whisper transcription failure
VOICE_MESSAGE_ERROR_TEMPLATE = PromptTemplate(
    template="[Voice message: Unable to transcribe audio - {error}]",
    input_variables=["error"],
)

# Timestamp processor default template (static text with variable)
# Note: This is config-driven, so we document the default format here
# but don't expose it as a PromptTemplate since it's rarely used directly
TIMESTAMP_DEFAULT_TEMPLATE = "[Current time: {datetime}]"
