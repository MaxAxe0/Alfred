"""Run from the project folder: python -m unittest discover -s tests -v"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import tools


class FileToolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="alfred-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sandbox = self.root / "sandbox"
        self.sandbox.mkdir()
        location = patch.object(tools, "__file__", str(self.root / "tools.py"))
        location.start()
        self.addCleanup(location.stop)

    def test_list_missing_sandbox_returns_error(self):
        self.sandbox.rmdir()
        self.assertEqual(tools.list_files(), "Error: the sandbox folder does not exist.")

    def test_list_files_excludes_folders(self):
        (self.sandbox / "note.txt").write_text("Hello", encoding="utf-8")
        (self.sandbox / "subfolder").mkdir()
        self.assertEqual(tools.list_files(), ["note.txt"])

    def test_read_rejects_outside_and_invalid_paths(self):
        (self.root / "outside.txt").write_text("Private", encoding="utf-8")
        for filename in ("../outside.txt", "invalid\x00.txt", "file.txt:stream"):
            with self.subTest(filename=filename):
                self.assertTrue(tools.read_file(filename).startswith("Error:"))

    def test_read_enforces_byte_limit(self):
        with patch.object(config, "MAX_READ_BYTES", 4):
            target = self.sandbox / "note.txt"
            target.write_bytes(b"1234")
            self.assertEqual(tools.read_file("note.txt"), "1234")
            target.write_bytes(b"12345")
            self.assertIn("4-byte read limit", tools.read_file("note.txt"))


    def test_approved_creation_writes_exact_content(self):
        with patch("builtins.input", return_value="yes"):
            self.assertEqual(tools.create_file_with_approval("approved.txt", "Exact text"), "Created approved.txt.")
        self.assertEqual((self.sandbox / "approved.txt").read_text(encoding="utf-8"), "Exact text")

    def test_denied_or_interrupted_approval_writes_nothing(self):
        for answer in ("no", "", "y", KeyboardInterrupt(), EOFError()):
            with self.subTest(answer=repr(answer)):
                if isinstance(answer, BaseException):
                    approval = patch("builtins.input", side_effect=answer)
                else:
                    approval = patch("builtins.input", return_value=answer)
                with approval:
                    self.assertTrue(tools.create_file_with_approval("cancelled.txt", "Text").startswith("Cancelled:"))
                self.assertFalse((self.sandbox / "cancelled.txt").exists())

    def test_existing_file_is_not_overwritten_or_offered_for_approval(self):
        target = self.sandbox / "existing.txt"
        target.write_text("Original", encoding="utf-8")
        with patch("builtins.input") as approval:
            self.assertTrue(tools.create_file_with_approval("existing.txt", "Replacement").startswith("Error:"))
            approval.assert_not_called()
        self.assertTrue(tools.create_file("existing.txt", "Replacement").startswith("Error:"))
        self.assertEqual(target.read_text(encoding="utf-8"), "Original")

    def test_outside_creation_is_rejected_before_approval(self):
        with patch("builtins.input") as approval:
            self.assertTrue(tools.create_file_with_approval("../outside.txt", "Text").startswith("Error:"))
            approval.assert_not_called()
        self.assertFalse((self.root / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
