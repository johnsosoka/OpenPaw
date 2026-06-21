"""Attachment type mapping utilities for channel adapters.

Provides a platform-agnostic MIME-type to attachment-type mapper used
when downloading or classifying file attachments.
"""


def map_mime_type_to_attachment_type(mime_type: str | None) -> str:
    """Map a MIME type to a simplified attachment category.

    Categories:
        - "audio" for MIME types starting with "audio/"
        - "image" for MIME types starting with "image/"
        - "document" for everything else (including unknown/None)

    Args:
        mime_type: The MIME type string, or None if unknown.

    Returns:
        One of "audio", "image", or "document".
    """
    if mime_type and mime_type.startswith("audio/"):
        return "audio"
    if mime_type and mime_type.startswith("image/"):
        return "image"
    return "document"
