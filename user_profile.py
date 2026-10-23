"""Load small private preferences; never load credentials into model context."""

import json
from email.errors import HeaderParseError
from email.headerregistry import Address
from pathlib import Path


PROFILE_PATH = Path(__file__).resolve().parent / ".local" / "profile.json"
DEFAULT_PROFILE = {"preferred_name": "", "timezone": "", "default_email": ""}


def load_profile(path=None):
    """Read a small JSON profile, rejecting unsupported fields and invalid values."""
    path = Path(path) if path is not None else PROFILE_PATH
    try:
        with path.open("rb") as file:
            data = file.read(4097)
    except FileNotFoundError:
        return DEFAULT_PROFILE.copy()
    if len(data) > 4096:
        raise ValueError("Profile exceeds the 4,096-byte limit.")
    try:
        values = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("Profile must be valid UTF-8 JSON.") from None
    if not isinstance(values, dict) or set(values) - set(DEFAULT_PROFILE):
        raise ValueError("Use only preferred_name, timezone, and default_email fields.")

    profile = DEFAULT_PROFILE.copy()
    for field, value in values.items():
        if not isinstance(value, str) or len(value) > 254:
            raise ValueError("Profile fields must be strings of at most 254 characters.")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Profile fields cannot contain control characters.")
        profile[field] = value.strip()
    if profile["default_email"]:
        try:
            address = Address(addr_spec=profile["default_email"])
            if not address.username or not address.domain or not profile["default_email"].isascii():
                raise ValueError()
        except (ValueError, IndexError, HeaderParseError):
            raise ValueError("default_email must be one plain ASCII email address.") from None
    return profile


def build_system_context(profile):
    """Send only a short allowlisted preference summary, never the email address."""
    prompt = Path(__file__).resolve().with_name("system_prompt.txt").read_text(encoding="utf-8")
    summary = {
        "preferred_name": profile["preferred_name"],
        "timezone": profile["timezone"],
        "default_email_configured": bool(profile["default_email"]),
    }
    return prompt.strip() + "\n\nPrivate preferences: " + json.dumps(summary, ensure_ascii=False)


def resolve_email_recipient(recipient, profile):
    """Resolve the exact 'me' alias; explicit recipient addresses are unchanged."""
    if isinstance(recipient, str) and recipient.strip().lower() == "me":
        if not profile["default_email"]:
            raise ValueError("No default email is configured. Set default_email in .local/profile.json or provide an explicit address.")
        return profile["default_email"]
    return recipient
