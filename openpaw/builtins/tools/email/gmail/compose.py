"""Gmail message composition — build RFC 2822 MIME messages."""

from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class GmailComposer:
    """Construct MIME messages for Gmail API submission."""

    def __init__(self, delegated_user: str) -> None:
        self._delegated_user = delegated_user

    def build_mime_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None,
        bcc: list[str] | None,
        reply_to_message_id: str | None,
        attachments: list[tuple[str, bytes, str]] | None,
    ) -> MIMEMultipart | MIMEText:
        """Construct a RFC 2822 MIME message ready for base64url encoding.

        Uses MIMEMultipart when attachments are present, otherwise falls back to a
        simple MIMEText to keep the message compact.

        Args:
            to: Primary recipient list.
            subject: Subject line.
            body: Plain text body.
            cc: CC recipients.
            bcc: BCC recipients (included in headers; Gmail handles actual delivery).
            reply_to_message_id: RFC 2822 Message-ID for threading.
            attachments: List of (filename, content_bytes, mime_type) tuples.

        Returns:
            Assembled MIME message object.
        """
        if attachments:
            msg: MIMEMultipart | MIMEText = MIMEMultipart()
            msg.attach(MIMEText(body, "plain", "utf-8"))
        else:
            msg = MIMEText(body, "plain", "utf-8")

        msg["From"] = self._delegated_user
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject

        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)

        if reply_to_message_id:
            # Strip any surrounding angle brackets before adding them back, to be safe.
            clean_id = reply_to_message_id.strip().strip("<>")
            msg["In-Reply-To"] = f"<{clean_id}>"
            msg["References"] = f"<{clean_id}>"

        if attachments and isinstance(msg, MIMEMultipart):
            for filename, content_bytes, mime_type in attachments:
                main_type, _, sub_type = mime_type.partition("/")
                if main_type and sub_type:
                    part: MIMEBase = MIMEBase(main_type, sub_type)
                    part.set_payload(content_bytes)
                    from email import encoders

                    encoders.encode_base64(part)
                else:
                    # Fallback for unrecognised or missing MIME types.
                    part = MIMEApplication(content_bytes)

                part.add_header("Content-Disposition", "attachment", filename=filename)
                msg.attach(part)

        return msg
