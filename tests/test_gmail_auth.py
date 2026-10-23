"""OAuth tests use fake credentials and never open a browser or contact Google."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import gmail_auth


class GmailAuthTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="alfred-gmail-tests-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        paths = patch.multiple(gmail_auth, AUTH_DIR=self.folder,
                               CLIENT_FILE=self.folder / "credentials.json",
                               TOKEN_FILE=self.folder / "token.json")
        paths.start()
        self.addCleanup(paths.stop)

    def test_missing_client_file_does_not_open_sign_in(self):
        with patch.object(gmail_auth.InstalledAppFlow, "from_client_secrets_file") as flow:
            with self.assertRaises(FileNotFoundError):
                gmail_auth.connect_gmail()
            flow.assert_not_called()
        self.assertFalse((self.folder / "token.json").exists())

    def test_cached_send_only_token_does_not_open_browser(self):
        token = self.folder / "token.json"
        token.write_text("{}", encoding="utf-8")
        credentials = Mock(valid=True, expired=False, scopes=gmail_auth.SCOPES)
        credentials.to_json.return_value = '{"test": true}'
        with patch.object(gmail_auth.Credentials, "from_authorized_user_file", return_value=credentials):
            with patch.object(gmail_auth.InstalledAppFlow, "from_client_secrets_file") as flow:
                self.assertIs(gmail_auth.connect_gmail(), credentials)
                flow.assert_not_called()
        self.assertFalse((self.folder / "token.tmp").exists())

    def test_broader_saved_scope_is_rejected(self):
        (self.folder / "token.json").write_text("{}", encoding="utf-8")
        credentials = Mock(scopes=gmail_auth.SCOPES + ["https://www.googleapis.com/auth/gmail.readonly"])
        with patch.object(gmail_auth.Credentials, "from_authorized_user_file", return_value=credentials):
            with self.assertRaises(ValueError):
                gmail_auth.connect_gmail()
        credentials.refresh.assert_not_called()

    def test_new_flow_requests_only_send_permission(self):
        (self.folder / "credentials.json").write_text("{}", encoding="utf-8")
        credentials = Mock(valid=True)
        credentials.to_json.return_value = '{"test": true}'
        with patch.object(gmail_auth.InstalledAppFlow, "from_client_secrets_file") as flow:
            flow.return_value.run_local_server.return_value = credentials
            gmail_auth.connect_gmail()
            flow.assert_called_once_with(str(self.folder / "credentials.json"), gmail_auth.SCOPES)
            self.assertEqual(flow.return_value.run_local_server.call_args.kwargs["bind_addr"], "127.0.0.1")
        self.assertEqual(gmail_auth.SCOPES, ["https://www.googleapis.com/auth/gmail.send"])
        self.assertTrue((self.folder / "token.json").exists())


    def test_noninteractive_mode_never_opens_sign_in(self):
        with patch.object(gmail_auth.InstalledAppFlow, "from_client_secrets_file") as flow:
            with self.assertRaises(ValueError):
                gmail_auth.connect_gmail(interactive=False)
            flow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
