from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from codex_armada.git import GitRepository, find_pattern_matches, find_scope_violations, path_matches
from tests.helpers import initialize_repo


class GitSafetyTests(unittest.TestCase):
    def test_scope_violation(self) -> None:
        violations = find_scope_violations(
            ["src/Feature/A.cs", "src/Other/B.cs"],
            ["src/Feature/**"],
            [],
        )
        self.assertEqual(["src/Other/B.cs"], violations)

    def test_excluded_path_is_violation(self) -> None:
        violations = find_scope_violations(
            ["src/Feature/Internal/A.cs"],
            ["src/Feature/**"],
            ["src/Feature/Internal/**"],
        )
        self.assertEqual(["src/Feature/Internal/A.cs"], violations)

    def test_protected_pattern(self) -> None:
        self.assertTrue(path_matches("config/.env", "**/.env"))
        self.assertEqual(["keys/server.pem"], find_pattern_matches(["keys/server.pem"], ["**/*.pem"]))
        self.assertEqual([".codex-armada.toml"], find_pattern_matches([".codex-armada.toml"], [".codex-armada.toml"]))

    def test_rename_tracks_and_commits_both_source_and_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_path = Path(temporary) / "repo"
            initialize_repo(repo_path)
            (repo_path / "old.txt").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "add", "old.txt"], cwd=repo_path, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "commit", "-m", "chore: add old file"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "mv", "old.txt", "new.txt"], cwd=repo_path, check=True, capture_output=True, text=True
            )

            repo = GitRepository(repo_path)
            self.assertEqual(["new.txt", "old.txt"], repo.changed_files())
            self.assertEqual(["old.txt"], repo.deleted_files())
            commit = repo.commit(repo.changed_files(), "refactor: rename file", cwd=repo_path)

            self.assertTrue(repo.commit_exists(commit))
            self.assertEqual([], repo.changed_files())
            self.assertTrue((repo_path / "new.txt").is_file())
            self.assertFalse((repo_path / "old.txt").exists())

    @unittest.skipIf(os.name == "nt", "Creating symlinks may require elevated Windows privileges")
    def test_changed_symlinks_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo_path = Path(temporary) / "repo"
            initialize_repo(repo_path)
            os.symlink("README.md", repo_path / "linked.txt")
            repo = GitRepository(repo_path)
            self.assertEqual(["linked.txt"], repo.symlink_files(repo.changed_files()))


if __name__ == "__main__":
    unittest.main()
