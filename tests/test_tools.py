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


if __name__ == "__main__":
    unittest.main()
