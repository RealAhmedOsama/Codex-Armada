from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_armada.version import __version__
from tests.helpers import initialize_repo, run_cli, test_environment


class CliVersionTests(unittest.TestCase):
    def test_version_forms_are_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            initialize_repo(repo)
            state = Path(temporary) / "state"
            env = test_environment(repo, state)
            versions: set[str] = set()
            for command in (["--version"], ["-V"], ["version"]):
                result = run_cli(repo, env, *command)
                self.assertEqual(0, result.returncode, msg=result.stdout + result.stderr)
                versions.add(result.stdout.strip())
            self.assertEqual(1, len(versions))
            self.assertEqual({__version__}, versions)


if __name__ == "__main__":
    unittest.main()
