"""Approved email sending for Alfred and the standalone terminal test."""

import base64
import config
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.message import EmailMessage

import httplib2
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from gmail_auth import connect_gmail



def send_email_with_approval(recipient: str, subject: str, body: str) -> str:
    """Preview and send one plain-text email only after terminal approval."""
    if not all(isinstance(value, str) for value in (recipient, subject, body)):
        return "Error: recipient, subject, and body must be strings."
    if len(recipient) > 254 or not subject.strip() or len(subject) > 200:
        return "Error: supply one email address and a subject of 1 to 200 characters."
    if not body.strip() or len(body) > config.MAX_EMAIL_BODY_CHARS:
        return f"Error: body must contain 1 to {config.MAX_EMAIL_BODY_CHARS:,} characters."
    if any(ord(char) < 32 or ord(char) == 127 for char in recipient + subject):
        return "Error: recipient and subject cannot contain control characters."
    # Quoted names are legal but let an address look like another one:
    # "a@b.com"@evil.example is delivered to evil.example.
    if '"' in recipient or "\\" in recipient:
        return "Error: recipient cannot contain quotes or backslashes."

    try:
        address = Address(addr_spec=recipient)
        if not address.username or not address.domain or not recipient.isascii():
            return "Error: supply one plain ASCII email address."
        message = EmailMessage()
        message["To"] = address
        message["Subject"] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    except (ValueError, IndexError, HeaderParseError):
        return "Error: invalid email address or message headers."

    # Freeze the message before approval. Credentials never enter the preview.
    print("[Email] Sender: the Gmail account authorized for Alfred")
    print("[Email] To:", repr(str(message["To"])))
    print("[Email] Subject:", repr(subject))
    print("[Email] Body (escaped):", repr(body))
    print("[Email] Attachments: none")
    try:
        approval = input("Send this exact email? Type yes to approve: ")
    except (KeyboardInterrupt, EOFError):
        print()
        return "Cancelled: email was not approved."
    if approval.strip().lower() != "yes":
        return "Cancelled: email was not approved."

    service = None
    send_started = False
    try:
        # Sending never opens sign-in or asks for broader permissions.
        credentials = connect_gmail(interactive=False)
        transport = AuthorizedHttp(credentials, http=httplib2.Http(timeout=30))
        service = build("gmail", "v1", http=transport, cache_discovery=False)
        request = service.users().messages().send(userId="me", body={"raw": raw})
        send_started = True
        response = request.execute(num_retries=0)
        if response.get("id"):
            return "Gmail accepted the email. This does not confirm inbox delivery."
        return "Uncertain: Gmail returned no message ID. Check Sent before sending again."
    except HttpError as error:
        if error.resp.status < 500:
            return f"Error: Gmail rejected the request (HTTP {error.resp.status}). No automatic retry was made."
        return "Uncertain: Gmail reported a server error. Check Sent before sending again. No automatic retry was made."
    except KeyboardInterrupt:
        print()
        if send_started:
            return "Uncertain: sending was interrupted. Check Sent before sending again."
        return "Cancelled: sending stopped before the send request started."
    except Exception:
        # Avoid printing token values or full provider responses on failures.
        if send_started:
            return "Uncertain: sending did not return a confirmed result. Check Sent before sending again. No automatic retry was made."
        return "Error: Gmail could not be prepared. Check the connection or run gmail_auth.py again. No send was attempted."
    finally:
        if service is not None:
            try:
                service.close()
            except Exception:
                pass  # Closing the transport must not hide a send result.


if __name__ == "__main__":
    try:
        recipient = input("To (one email address): ")
        subject = input("Subject: ")
        body = input("Body (one line for this test): ")
        print(send_email_with_approval(recipient, subject, body))
    except (KeyboardInterrupt, EOFError):
        print("\n[Email] Cancelled.")
