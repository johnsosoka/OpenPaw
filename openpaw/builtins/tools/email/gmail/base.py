"""Gmail provider base utilities."""

import logging

logger = logging.getLogger(__name__)


def _format_api_error(action: str, exc: Exception) -> str:
    """Return a user-friendly error string for a Gmail API exception.

    Attempts to extract a meaningful message from HttpError responses.
    Falls back to a generic message for unexpected exception types.

    Args:
        action: Short description of what was being attempted (e.g., "send email").
        exc: The caught exception.

    Returns:
        A formatted "[Error: ...]" string safe to return to the agent.
    """
    # googleapiclient.errors.HttpError exposes .status_code (int) directly,
    # or .resp.status on the underlying httplib2 response object.
    status_code: int | None = None
    try:
        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            resp = getattr(exc, "resp", None)
            if resp is not None:
                status_code = getattr(resp, "status", None)
        if status_code is not None:
            status_code = int(status_code)
    except (ValueError, TypeError):
        pass

    if status_code == 429:
        return "[Error: Gmail API rate limit reached. Please wait a moment and try again.]"
    if status_code == 401:
        return "[Error: Gmail authentication failed. Check the service account credentials.]"
    if status_code == 403:
        return (
            "[Error: Gmail API access denied. "
            "Verify that domain-wide delegation is enabled for this service account "
            "and that the correct scopes have been granted.]"
        )
    if status_code == 404:
        return "[Error: Requested Gmail resource not found. Check the message or attachment ID.]"
    if status_code is not None and status_code >= 500:
        return f"[Error: Gmail API server error ({status_code}). Please try again later.]"

    # Generic fallback — include the exception message but avoid raw tracebacks.
    logger.error(f"Unexpected error during '{action}': {exc}", exc_info=True)
    return f"[Error: Failed to {action}: {exc}]"


def _pad_base64(data: str) -> str:
    """Add missing base64 padding characters.

    Gmail uses base64url without padding. Python's base64.urlsafe_b64decode
    requires correct padding.

    Args:
        data: Potentially unpadded base64url string.

    Returns:
        Properly padded base64url string.
    """
    remainder = len(data) % 4
    if remainder:
        data += "=" * (4 - remainder)
    return data
