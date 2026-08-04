from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_armada.config import load_config
from codex_armada.errors import VerificationError
from codex_armada.verification import VerificationRunner, _split_command


class VerificationSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.runner = VerificationRunner(load_config(Path(self.temporary.name)))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_rejects_shell_operators(self) -> None:
        with self.assertRaises(VerificationError):
            self.runner.validate("git diff --check && git status")

    def test_rejects_destructive_git(self) -> None:
        with self.assertRaises(VerificationError):
            self.runner.validate("git reset --hard")

    def test_preserves_quoted_arguments_cross_platform(self) -> None:
        parts = self.runner.validate('dotnet test "tests/My Project.Tests.csproj" --no-restore')
        self.assertEqual("tests/My Project.Tests.csproj", parts[2])

    def test_windows_split_preserves_backslashes_and_quotes(self) -> None:
        self.assertEqual(
            ["dotnet", "test", r"tests\My Project.Tests.csproj", "--no-restore"],
            _split_command(r'dotnet test "tests\My Project.Tests.csproj" --no-restore', windows=True),
        )

    def test_rejects_arbitrary_python_script(self) -> None:
        with self.assertRaises(VerificationError):
            self.runner.validate("python scripts/check.py")

    def test_accepts_allowlisted_python_module(self) -> None:
        self.assertEqual(
            ["python", "-m", "unittest", "discover"],
            self.runner.validate("python -m unittest discover"),
        )

    def test_rejects_arbitrary_node_make_java_and_npx_execution_by_default(self) -> None:
        for command in ("node scripts/check.js", "make test", "java Main", "npx arbitrary-package"):
            with self.subTest(command=command), self.assertRaises(VerificationError):
                self.runner.validate(command)

    def test_accepts_safe_package_scripts(self) -> None:
        for command in ("npm test", "npm run test:unit", "pnpm run lint", "yarn run typecheck", "bun run build"):
            with self.subTest(command=command):
                self.assertEqual(command.split(), self.runner.validate(command))

    def test_rejects_unsafe_package_scripts(self) -> None:
        for command in ("npm run deploy", "pnpm run publish", "yarn run release", "bun run migrate"):
            with self.subTest(command=command), self.assertRaises(VerificationError):
                self.runner.validate(command)

    def test_accepts_safe_maven_and_gradle_goals(self) -> None:
        for command in ("mvn -q verify", "mvnw test", "gradle check", "./gradlew :app:test"):
            with self.subTest(command=command):
                self.runner.validate(command)

    def test_rejects_unsafe_maven_and_gradle_goals(self) -> None:
        for command in ("mvn deploy", "mvnw release:prepare", "gradle publish", "./gradlew deploy"):
            with self.subTest(command=command), self.assertRaises(VerificationError):
                self.runner.validate(command)

    def test_accepts_dotnet_test(self) -> None:
        self.assertEqual(
            ["dotnet", "test", "Project.Tests.csproj"],
            self.runner.validate("dotnet test Project.Tests.csproj"),
        )


if __name__ == "__main__":
    unittest.main()
