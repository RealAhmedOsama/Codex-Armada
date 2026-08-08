from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

from codex_armada.console import Console
from codex_armada.process import command_prefix, run_process


class ProcessTests(unittest.TestCase):
    def test_command_prefix_keeps_existing_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "simple-script.py"
            executable.write_text("", encoding="utf-8")
            self.assertEqual([str(executable.resolve())], command_prefix(str(executable)))

    @unittest.skipUnless(os.name == "nt", "Windows path reconstruction is Windows-specific")
    def test_command_prefix_preserves_ambiguous_executable_path_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "codex with space"
            workspace.mkdir()
            executable = workspace / "fake-codex.py"
            executable.write_text("", encoding="utf-8")
            command = f"{executable} --version"
            self.assertEqual(
                [str(executable.resolve()), "--version"],
                command_prefix(command),
            )

    def test_command_prefix_preserves_non_ascii_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "unicode-space"
            workspace.mkdir()
            executable = workspace / "fake-codex.py"
            executable.write_text("", encoding="utf-8")
            self.assertEqual(
                [str(executable.resolve())],
                command_prefix(str(executable)),
            )

    def test_run_process_returns_unicode_stdout_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "unicode.py"
            script.write_text(
                "import sys\nprint('unicode output ' + chr(0x2728))\n"
                "sys.stderr.write('stderr ' + chr(0x00A9) + '\\n')\n"
                "print('ok', flush=True)\n",
                encoding="utf-8",
            )
            result = run_process([sys.executable, str(script)])
            self.assertEqual(0, result.return_code)
            self.assertIn("unicode output", result.stdout)
            self.assertIn(chr(0x2728), result.stdout)
            self.assertIn(chr(0x00A9), result.stderr)

    def test_console_prints_without_unicode_errors(self) -> None:
        stream = io.BytesIO()
        writer = io.TextIOWrapper(stream, encoding="ascii", errors="strict")
        Console._safe_print("\u2713 done", stream=writer)
        writer.flush()
        self.assertIn("\\u2713", stream.getvalue().decode("ascii", errors="replace"))


if __name__ == "__main__":
    unittest.main()
