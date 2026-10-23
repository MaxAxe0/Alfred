"""Connect Gmail explicitly from the terminal. This script never sends mail."""

from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
AUTH_DIR = Path(__file__).resolve().parent / ".local" / "gmail"
CLIENT_FILE = AUTH_DIR / "credentials.json"
TOKEN_FILE = AUTH_DIR / "token.json"


def connect_gmail(interactive=True):
    """Authorize send-only Gmail access and save the local token."""
    credentials = None
    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE))
        if set(credentials.scopes or []) != set(SCOPES):
            raise ValueError("Saved token has different permissions. Remove the local token and reconnect.")
        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except RefreshError:
                # Revoked or expired consent requires a fresh browser sign-in.
                credentials = None

    if not credentials or not credentials.valid:
        if not interactive:
            raise ValueError("Run gmail_auth.py to authorize Gmail before sending.")
        if not CLIENT_FILE.exists():
            raise FileNotFoundError("Save your Desktop OAuth JSON as .local/gmail/credentials.json first. See GMAIL_SETUP.md.")
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
        credentials = flow.run_local_server(
            host="localhost",
            bind_addr="127.0.0.1",
            port=0,
            timeout_seconds=180,
            prompt="consent",
            success_message="Alfred's Gmail sign-in is complete. You may close this tab.",
        )

    if not credentials or not credentials.valid:
        raise ValueError("Google sign-in did not complete. Run gmail_auth.py again.")
    if not credentials.has_scopes(SCOPES):
        raise ValueError("Send permission was not granted. Reconnect and review the permission request.")

    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    # Replace atomically so an interrupted save does not truncate an existing token.
    temporary = TOKEN_FILE.with_suffix(".tmp")
    temporary.write_text(credentials.to_json(), encoding="utf-8")
    temporary.replace(TOKEN_FILE)
    return credentials


if __name__ == "__main__":
    try:
        connect_gmail()
    except (KeyboardInterrupt, EOFError):
        print("\n[Gmail] Sign-in cancelled.")
    except FileNotFoundError as error:
        print("[Gmail]", error)
    except ValueError:
        print("[Gmail] Credentials, permissions, or sign-in are invalid. Check GMAIL_SETUP.md and reconnect.")
    except Exception:
        # Do not echo authentication responses or tokens into terminal logs.
        print("[Gmail] Sign-in failed. Check the connection and Google consent setup, then retry.")
    else:
        print("[Gmail] Send-only authorization saved locally. No email was sent.")
