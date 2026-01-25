"""Email notification via Gmail API."""

import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional, Dict, List
from googleapiclient.discovery import Resource

from logger_setup import get_logger

logger = get_logger()


def create_message(
    sender: str,
    to: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
) -> dict:
    """
    Create an email message for the Gmail API.

    Args:
        sender: Sender email address
        to: Recipient email address
        subject: Email subject
        body_text: Plain text body
        body_html: Optional HTML body

    Returns:
        Message dict ready for Gmail API
    """
    if body_html:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(body_text, "plain"))
        message.attach(MIMEText(body_html, "html"))
    else:
        message = MIMEText(body_text)

    message["to"] = to
    message["from"] = sender
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return {"raw": raw}


def send_notification(
    gmail_service: Resource,
    recipient: str,
    extract_results: Dict[str, dict],
    date_range: Optional[tuple] = None,
) -> bool:
    """
    Send a notification email summarizing the extract results.

    Args:
        gmail_service: Authenticated Gmail API service
        recipient: Email recipient
        extract_results: Dict mapping tab names to result info
        date_range: Optional tuple of (from_date, to_date)

    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        # Get sender email from Gmail API
        profile = gmail_service.users().getProfile(userId="me").execute()
        sender = profile.get("emailAddress", "noreply@example.com")

        # Build subject
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        subject = f"HIVE Extract Completed - {timestamp}"

        # Build body
        lines = ["HIVE Extract Summary", "=" * 40, ""]

        if date_range:
            from_date, to_date = date_range
            lines.append(f"Date Range: {from_date} to {to_date}")
            lines.append("")

        lines.append("Results:")
        lines.append("-" * 40)

        success_count = 0
        error_count = 0

        for tab_name, result in extract_results.items():
            status = result.get("status", "unknown")
            rows = result.get("rows", 0)
            error = result.get("error", "")

            if status == "success":
                lines.append(f"✓ {tab_name}: {rows} rows written")
                success_count += 1
            else:
                lines.append(f"✗ {tab_name}: FAILED - {error}")
                error_count += 1

        lines.append("")
        lines.append("-" * 40)
        lines.append(f"Total: {success_count} successful, {error_count} failed")

        body_text = "\n".join(lines)

        # Create and send message
        message = create_message(sender, recipient, subject, body_text)
        gmail_service.users().messages().send(userId="me", body=message).execute()

        logger.info(f"Notification email sent to {recipient}")
        return True

    except Exception as e:
        logger.error(f"Failed to send notification email: {e}")
        return False


def send_error_notification(
    gmail_service: Resource,
    recipient: str,
    error_message: str,
) -> bool:
    """
    Send an error notification email.

    Args:
        gmail_service: Authenticated Gmail API service
        recipient: Email recipient
        error_message: Error description

    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        profile = gmail_service.users().getProfile(userId="me").execute()
        sender = profile.get("emailAddress", "noreply@example.com")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        subject = f"HIVE Extract FAILED - {timestamp}"

        body_text = f"""HIVE Extract Failed
{"=" * 40}

The HIVE Extract process encountered an error:

{error_message}

Please check the logs for more details.
"""

        message = create_message(sender, recipient, subject, body_text)
        gmail_service.users().messages().send(userId="me", body=message).execute()

        logger.info(f"Error notification email sent to {recipient}")
        return True

    except Exception as e:
        logger.error(f"Failed to send error notification: {e}")
        return False
