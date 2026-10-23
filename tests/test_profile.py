"""Private profile checks use temporary files and synthetic preferences."""

import io
import json
import runpy
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ollama import Message

from user_profile import DEFAULT_PROFILE, build_system_context, load_profile, resolve_email_recipient


class ProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="alfred-profile-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "profile.json"

    def test_missing_profile_returns_independent_defaults(self):
        profile = load_profile(self.path)
        self.assertEqual(profile, DEFAULT_PROFILE)
        profile["preferred_name"] = "Changed"
        self.assertEqual(DEFAULT_PROFILE["preferred_name"], "")

    def test_valid_profile_is_loaded(self):
        self.path.write_text(json.dumps({"preferred_name": "Test user", "timezone": "America/New_York", "default_email": "private@example.com"}), encoding="utf-8")
        self.assertEqual(load_profile(self.path)["default_email"], "private@example.com")

    def test_invalid_profiles_are_rejected(self):
        cases = ["not JSON", "[]", '{"password":"secret-placeholder"}', '{"preferred_name":123}', '{"default_email":"invalid"}', '{"default_email":"a@example.com,b@example.com"}', '{"preferred_name":"bad\\nname"}']
        # Include an actual control character through JSON escaping.
        cases[-1] = json.dumps({"preferred_name": "bad\nname"})
        for content in cases:
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_profile(self.path)

    def test_large_profile_is_rejected(self):
        self.path.write_bytes(b" " * 4097)
        with self.assertRaises(ValueError):
            load_profile(self.path)

    def test_context_excludes_actual_email_and_unknown_fields(self):
        profile = {"preferred_name": "Test user", "timezone": "America/New_York", "default_email": "private@example.com", "secret": "NEVER_INCLUDE_THIS"}
        context = build_system_context(profile)
        self.assertIn("Test user", context)
        self.assertIn('"default_email_configured": true', context)
        self.assertNotIn("private@example.com", context)
        self.assertNotIn("NEVER_INCLUDE_THIS", context)

    def test_alias_resolves_without_changing_explicit_addresses(self):
        profile = {**DEFAULT_PROFILE, "default_email": "private@example.com"}
        self.assertEqual(resolve_email_recipient("me", profile), "private@example.com")
        self.assertEqual(resolve_email_recipient("other@example.com", profile), "other@example.com")
        with self.assertRaises(ValueError):
            resolve_email_recipient("me", DEFAULT_PROFILE)

    def test_dispatcher_resolves_alias_but_keeps_address_out_of_model_history(self):
        profile = {**DEFAULT_PROFILE, "default_email": "private@example.com"}
        client = Mock()
        client.chat.side_effect = [
            SimpleNamespace(message=Message(role="assistant", content="", tool_calls=[{"function": {"name": "send_email_with_approval", "arguments": {"recipient": "me", "subject": "Test", "body": "Hello"}}}])),
            SimpleNamespace(message=Message(role="assistant", content="Cancelled.")),
        ]
        with patch("user_profile.load_profile", return_value=profile), patch("ollama.Client", return_value=client):
            with patch("gmail_tools.send_email_with_approval", return_value="Cancelled: email was not approved.") as send:
                with patch("builtins.input", side_effect=["Email me a test", "/clear", "exit"]), redirect_stdout(io.StringIO()):
                    state = runpy.run_path(str(Path(__file__).resolve().parents[1] / "assistant.py"), run_name="__main__")
        send.assert_called_once_with("private@example.com", "Test", "Hello")
        self.assertEqual(len(state["messages"]), 1)
        self.assertNotIn("private@example.com", state["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
