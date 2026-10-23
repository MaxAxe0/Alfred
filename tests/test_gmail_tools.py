"""No real email is sent: authorization and Gmail service are mocked."""

import base64
import io
import unittest
from contextlib import redirect_stdout
from email import policy
from email.parser import BytesParser
from unittest.mock import Mock, patch

import config
import gmail_tools


class GmailSendTests(unittest.TestCase):
    def setUp(self):
        authorize = patch("gmail_tools.connect_gmail")
        self.authorize = authorize.start()
        self.addCleanup(authorize.stop)
        build = patch("gmail_tools.build")
        self.build = build.start()
        self.addCleanup(build.stop)
        transport = patch("gmail_tools.AuthorizedHttp")
        transport.start()
        self.addCleanup(transport.stop)
        self.request = self.build.return_value.users.return_value.messages.return_value.send.return_value
        self.request.execute.return_value = {"id": "fake-message-id"}
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_rejection_and_interruption_never_access_gmail(self):
        for response in ("no", "", "y", KeyboardInterrupt(), EOFError()):
            with self.subTest(response=repr(response)):
                approval = (patch("builtins.input", side_effect=response) if isinstance(response, BaseException)
                            else patch("builtins.input", return_value=response))
                with approval:
                    result = gmail_tools.send_email_with_approval("recipient@example.com", "Subject", "Body")
                self.assertTrue(result.startswith("Cancelled:"))
        self.authorize.assert_not_called()
        self.build.assert_not_called()

    def test_invalid_headers_and_multiple_recipients_are_rejected(self):
        for recipient, subject in (("a@example.com,b@example.com", "Subject"), ("a@example.com\nBcc: b@example.com", "Subject"), ("a@example.com", "Subject\nBcc: b@example.com"), ("not-an-address", "Subject")):
            with self.subTest(recipient=recipient), patch("builtins.input") as approval:
                result = gmail_tools.send_email_with_approval(recipient, subject, "Body")
                self.assertTrue(result.startswith("Error:"))
                approval.assert_not_called()
        self.authorize.assert_not_called()

    def test_approval_sends_exact_message_once_without_retry(self):
        with patch("builtins.input", return_value="yes"):
            result = gmail_tools.send_email_with_approval("recipient@example.com", "My subject", "Hello\nWorld")
        self.assertIn("Gmail accepted", result)
        self.authorize.assert_called_once_with(interactive=False)
        self.request.execute.assert_called_once_with(num_retries=0)
        send = self.build.return_value.users.return_value.messages.return_value.send
        self.assertEqual(send.call_args.kwargs["userId"], "me")
        raw = send.call_args.kwargs["body"]["raw"]
        message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw))
        self.assertEqual(str(message["To"]), "recipient@example.com")
        self.assertEqual(str(message["Subject"]), "My subject")
        self.assertEqual(message.get_content(), "Hello\nWorld\n")
        self.assertIsNone(message["Cc"])
        self.assertIsNone(message["Bcc"])
        self.build.return_value.close.assert_called_once()

    def test_network_failure_during_send_is_uncertain_not_retried(self):
        self.request.execute.side_effect = OSError("simulated connection loss")
        with patch("builtins.input", return_value="yes"):
            result = gmail_tools.send_email_with_approval("recipient@example.com", "Subject", "Body")
        self.assertTrue(result.startswith("Uncertain:"))
        self.request.execute.assert_called_once_with(num_retries=0)

    def test_missing_authorization_does_not_send(self):
        self.authorize.side_effect = ValueError("not connected")
        with patch("builtins.input", return_value="yes"):
            result = gmail_tools.send_email_with_approval("recipient@example.com", "Subject", "Body")
        self.assertIn("No send was attempted", result)
        self.build.assert_not_called()

    def test_body_limit_prevents_approval(self):
        with patch.object(config, "MAX_EMAIL_BODY_CHARS", 4), patch("builtins.input") as approval:
            result = gmail_tools.send_email_with_approval("recipient@example.com", "Subject", "12345")
            self.assertTrue(result.startswith("Error:"))
            approval.assert_not_called()


if __name__ == "__main__":
    unittest.main()
