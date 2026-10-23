"""Exercise real email approval through Alfred; mock all model and Gmail calls."""

import io
import runpy
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ollama import Message


SCRIPT = Path(__file__).resolve().parents[1] / "assistant.py"


def proposal(arguments=None):
    if arguments is None:
        arguments = {"recipient": "recipient@example.com", "subject": "Test", "body": "Hello"}
    return SimpleNamespace(message=Message(role="assistant", content="", tool_calls=[{
        "function": {"name": "send_email_with_approval", "arguments": arguments}
    }]))


def reply():
    return SimpleNamespace(message=Message(role="assistant", content="Reported result."))


class EmailIntegrationTests(unittest.TestCase):
    def run_assistant(self, inputs, responses):
        client = Mock()
        client.chat.side_effect = responses
        with patch("ollama.Client", return_value=client):
            with patch("builtins.input", side_effect=inputs):
                with redirect_stdout(io.StringIO()) as output:
                    state = runpy.run_path(str(SCRIPT), run_name="__main__")
        tool_results = [m["content"] for m in state["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
        offered = client.chat.call_args_list[0].kwargs["tools"]
        self.assertIn("send_email_with_approval", [function.__name__ for function in offered])
        return tool_results, output.getvalue()

    def test_cancellation_never_accesses_gmail(self):
        with patch("gmail_tools.connect_gmail") as authorize, patch("gmail_tools.build") as build:
            results, output = self.run_assistant(["Email a test", "no", "exit"], [proposal(), reply()])
        authorize.assert_not_called()
        build.assert_not_called()
        self.assertTrue(results[0].startswith("Cancelled:"))
        self.assertIn("[Email] To:", output)

    def test_approval_sends_once_and_returns_acceptance_to_model(self):
        with patch("gmail_tools.connect_gmail") as authorize, patch("gmail_tools.AuthorizedHttp"), patch("gmail_tools.build") as build:
            execute = build.return_value.users.return_value.messages.return_value.send.return_value.execute
            execute.return_value = {"id": "fake-id"}
            results, output = self.run_assistant(["Email a test", "yes", "exit"], [proposal(), reply()])
        authorize.assert_called_once_with(interactive=False)
        execute.assert_called_once_with(num_retries=0)
        self.assertIn("Gmail accepted", results[0])

    def test_uncertain_send_cannot_be_retried_by_model_in_same_turn(self):
        with patch("gmail_tools.connect_gmail"), patch("gmail_tools.AuthorizedHttp"), patch("gmail_tools.build") as build:
            execute = build.return_value.users.return_value.messages.return_value.send.return_value.execute
            execute.side_effect = OSError("simulated network failure")
            results, output = self.run_assistant(["Email a test", "yes", "exit"], [proposal(), proposal(), reply()])
        execute.assert_called_once_with(num_retries=0)
        self.assertTrue(results[0].startswith("Uncertain:"))
        self.assertIn("one email proposal", results[1])
        self.assertIn("Uncertain:", output)

    def test_missing_arguments_do_not_access_gmail(self):
        with patch("gmail_tools.connect_gmail") as authorize:
            results, output = self.run_assistant(["Email a test", "exit"], [proposal({"subject": "Missing recipient"}), reply()])
        authorize.assert_not_called()
        self.assertTrue(results[0].startswith("Error:"))


if __name__ == "__main__":
    unittest.main()
