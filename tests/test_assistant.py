"""Model failures are simulated: these tests do not contact Ollama."""

import io
import runpy
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from httpx import ReadTimeout, RemoteProtocolError
from ollama import Message, ResponseError

import config


SCRIPT = Path(__file__).resolve().parents[1] / "assistant.py"


def answer(text):
    return SimpleNamespace(message=Message(role="assistant", content=text))


class RequestRecoveryTests(unittest.TestCase):
    def run_assistant(self, inputs, outcomes):
        client = Mock()
        snapshots = []
        outcomes = iter(outcomes)

        def request(**kwargs):
            # Copy now: the assistant changes the history list afterward.
            snapshots.append(list(kwargs["messages"]))
            outcome = next(outcomes)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        client.chat.side_effect = request
        with patch("ollama.Client", return_value=client) as constructor:
            with patch("builtins.input", side_effect=inputs):
                with redirect_stdout(io.StringIO()) as output:
                    state = runpy.run_path(str(SCRIPT), run_name="__main__")
        self.assertEqual(constructor.call_args_list[1].kwargs["timeout"], config.REQUEST_TIMEOUT_SECONDS)
        return state, output.getvalue(), snapshots, client

    def test_request_failures_preserve_earlier_turns_and_allow_recovery(self):
        cases = [
            (ConnectionError("offline"), "Cannot connect"),
            (ReadTimeout("stalled"), "timed out"),
            (ResponseError("model missing", status_code=404), "ollama pull"),
            (ResponseError("server failure", status_code=500), "Ollama error (500)"),
            (RemoteProtocolError("connection lost"), "Communication with Ollama failed"),
        ]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__, detail=expected):
                state, output, snapshots, client = self.run_assistant(
                    ["Earlier question", "Failed question", "Try again", "exit"],
                    [answer("Earlier answer"), error, answer("Recovered")],
                )
                self.assertIn(expected, output)
                self.assertEqual(client.chat.call_count, 3)
                self.assertEqual(len(state["messages"]), 5)
                self.assertEqual(snapshots[-1][0]["role"], "system")
                self.assertEqual(snapshots[-1][1]["content"], "Earlier question")
                self.assertEqual(snapshots[-1][-1]["content"], "Try again")
                self.assertNotIn("Failed question", str(state["messages"]))

    def test_failure_after_tool_does_not_repeat_the_action(self):
        request = SimpleNamespace(message=Message(
            role="assistant", content="", tool_calls=[{
                "function": {
                    "name": "create_file_with_approval",
                    "arguments": {"filename": "example.txt", "content": "Example"},
                }
            }],
        ))
        with patch("tools.create_file_with_approval", return_value="Created example.txt.") as create:
            state, output, snapshots, client = self.run_assistant(
                ["Create a file", "Continue", "exit"],
                [request, ReadTimeout("stalled after writing"), answer("Recovered")],
            )
        create.assert_called_once_with("example.txt", "Example")
        self.assertEqual(client.chat.call_count, 3)
        self.assertIn("not undone", output)
        self.assertEqual(len(state["messages"]), 3)
        self.assertEqual(snapshots[-1][1]["content"], "Continue")


    def test_prompt_interrupt_and_end_of_input_exit_cleanly(self):
        for interruption in (KeyboardInterrupt(), EOFError()):
            with self.subTest(interruption=type(interruption).__name__):
                state, output, snapshots, client = self.run_assistant([interruption], [])
                self.assertIn("Goodbye", output)
                client.chat.assert_not_called()
                self.assertEqual(len(state["messages"]), 1)

    def test_request_interrupt_preserves_history_and_allows_next_request(self):
        state, output, snapshots, client = self.run_assistant(
            ["Earlier", "Cancel this", "Continue", "exit"],
            [answer("Earlier answer"), KeyboardInterrupt(), answer("Recovered")],
        )
        self.assertIn("Request cancelled", output)
        self.assertEqual(len(state["messages"]), 5)
        self.assertNotIn("Cancel this", str(state["messages"]))
        self.assertEqual(snapshots[-1][0]["role"], "system")
        self.assertEqual(snapshots[-1][1]["content"], "Earlier")

    def test_interrupt_after_tool_does_not_repeat_action(self):
        request = SimpleNamespace(message=Message(
            role="assistant", content="", tool_calls=[{
                "function": {
                    "name": "create_file_with_approval",
                    "arguments": {"filename": "example.txt", "content": "Example"},
                }
            }],
        ))
        with patch("tools.create_file_with_approval", return_value="Created example.txt.") as create:
            state, output, snapshots, client = self.run_assistant(
                ["Create", "Continue", "exit"],
                [request, KeyboardInterrupt(), answer("Recovered")],
            )
        create.assert_called_once()
        self.assertEqual(len(state["messages"]), 3)
        self.assertIn("not undone", output)

    def test_status_interrupt_returns_to_prompt(self):
        with patch("ollama.Client") as constructor:
            constructor.return_value.list.side_effect = KeyboardInterrupt()
            with patch("builtins.input", side_effect=["/status", "exit"]):
                with redirect_stdout(io.StringIO()) as output:
                    state = runpy.run_path(str(SCRIPT), run_name="__main__")
        self.assertIn("Check cancelled", output.getvalue())
        self.assertEqual(len(state["messages"]), 1)
        constructor.return_value.chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
