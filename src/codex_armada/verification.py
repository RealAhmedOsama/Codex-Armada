from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

from .config import AppConfig
from .domain import CommandResult, VerificationSpec
from .errors import VerificationError
from .git import GitRepository
from .process import run_process
from .util import atomic_write_text

_FORBIDDEN_TOKENS = {"&&", "||", ";", "|", ">", ">>", "<", "2>", "2>>", "&"}
_SAFE_GIT_SUBCOMMANDS = {"diff", "status", "rev-parse", "log", "show", "grep", "ls-files"}
_SAFE_DOTNET_SUBCOMMANDS = {"build", "test"}
_SAFE_PYTHON_MODULES = {"compileall", "mypy", "pytest", "ruff", "unittest"}
_SAFE_CARGO_SUBCOMMANDS = {"build", "check", "clippy", "fmt", "test"}
_SAFE_GO_SUBCOMMANDS = {"build", "fmt", "test", "vet"}
_DIRECT_SAFE_TOOLS = {"pytest", "ruff", "mypy"}
_PACKAGE_MANAGERS = {"npm", "pnpm", "yarn", "bun"}
_MAVEN_TOOLS = {"mvn", "mvnw"}
_GRADLE_TOOLS = {"gradle", "gradlew"}
_SAFE_PACKAGE_SCRIPT = re.compile(
    r"^(?:test|lint|check|verify|validate|build|typecheck|type-check|ci|"
    r"format(?::check|-check)?)(?::[A-Za-z0-9._-]+)*$",
    re.IGNORECASE,
)
_SAFE_MAVEN_GOAL = re.compile(
    r"^(?:test|verify|package|compile|checkstyle:check|spotbugs:check|pmd:check)$",
    re.IGNORECASE,
)
_SAFE_GRADLE_TASK = re.compile(
    r"^(?:(?::?[A-Za-z0-9_.-]+):)*(?:test|check|build|assemble|lint|verify)$",
    re.IGNORECASE,
)


def _split_command(command: str, *, windows: bool | None = None) -> list[str]:
    """Split a verification command without invoking a shell.

    Windows paths use backslashes, which POSIX shlex treats as escapes. On Windows,
    non-POSIX parsing preserves those paths; matching outer quotes are then removed
    because subprocess receives an argument vector rather than a command line.
    """

    windows = os.name == "nt" if windows is None else windows
    try:
        parts = shlex.split(command, posix=not windows)
    except ValueError as exc:
        raise VerificationError(f"Invalid verification command: {command}: {exc}") from exc
    if windows:
        parts = [
            token[1:-1]
            if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}
            else token
            for token in parts
        ]
    return parts


def _normalized_executable(value: str) -> str:
    executable = Path(value).name.lower()
    for suffix in (".exe", ".cmd", ".bat", ".sh"):
        if executable.endswith(suffix):
            executable = executable[: -len(suffix)]
            break
    return executable


def _require_package_command(parts: list[str], command: str) -> None:
    if len(parts) < 2:
        raise VerificationError(f"Package-manager verification needs a test/check script: {command}")
    subcommand = parts[1].lower()
    if subcommand == "test":
        return
    if subcommand != "run" or len(parts) < 3 or not _SAFE_PACKAGE_SCRIPT.fullmatch(parts[2]):
        raise VerificationError(
            "Package-manager verification may run only test/build/lint/check/verify/validate/typecheck/CI scripts: "
            f"{command}"
        )


def _require_maven_command(parts: list[str], command: str) -> None:
    goals = [token for token in parts[1:] if not token.startswith("-")]
    if not goals or any(not _SAFE_MAVEN_GOAL.fullmatch(goal) for goal in goals):
        raise VerificationError(f"Maven verification contains an unsafe or unsupported goal: {command}")


def _require_gradle_command(parts: list[str], command: str) -> None:
    tasks = [token for token in parts[1:] if not token.startswith("-")]
    if not tasks or any(not _SAFE_GRADLE_TASK.fullmatch(task) for task in tasks):
        raise VerificationError(f"Gradle verification contains an unsafe or unsupported task: {command}")


class VerificationRunner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def validate(self, command: str) -> list[str]:
        parts = _split_command(command)
        if not parts:
            raise VerificationError("Verification command is empty")
        if any(token in _FORBIDDEN_TOKENS for token in parts):
            raise VerificationError(f"Shell operators are forbidden in verification: {command}")
        executable = _normalized_executable(parts[0])
        allowlisted = {item.lower() for item in self.config.allowed_verification_tools}
        if executable not in allowlisted:
            raise VerificationError(f"Verification tool `{executable}` is not allowlisted")

        if executable == "git":
            if len(parts) < 2 or parts[1] not in _SAFE_GIT_SUBCOMMANDS:
                raise VerificationError(f"Unsafe Git verification command: {command}")
        elif executable == "dotnet":
            if len(parts) < 2 or parts[1] not in _SAFE_DOTNET_SUBCOMMANDS:
                raise VerificationError(f"Unsafe dotnet verification command: {command}")
        elif executable in {"python", "python3", "py"}:
            module_index = 1
            if executable == "py" and len(parts) > 1 and parts[1].startswith("-") and parts[1] != "-m":
                module_index += 1
            if len(parts) <= module_index + 1 or parts[module_index] != "-m":
                raise VerificationError(
                    f"Python verification must use an allowlisted `-m` module, not an arbitrary script: {command}"
                )
            module = parts[module_index + 1].split(".", 1)[0]
            if module not in _SAFE_PYTHON_MODULES:
                raise VerificationError(f"Unsafe Python verification module `{module}`: {command}")
        elif executable in _PACKAGE_MANAGERS:
            _require_package_command(parts, command)
        elif executable == "cargo":
            if len(parts) < 2 or parts[1] not in _SAFE_CARGO_SUBCOMMANDS:
                raise VerificationError(f"Unsafe Cargo verification command: {command}")
        elif executable == "go":
            if len(parts) < 2 or parts[1] not in _SAFE_GO_SUBCOMMANDS:
                raise VerificationError(f"Unsafe Go verification command: {command}")
        elif executable in _MAVEN_TOOLS:
            _require_maven_command(parts, command)
        elif executable in _GRADLE_TOOLS:
            _require_gradle_command(parts, command)
        elif executable not in _DIRECT_SAFE_TOOLS:
            raise VerificationError(
                f"Verification tool `{executable}` is allowlisted but has no built-in safety policy"
            )
        return parts

    def run(
        self,
        *,
        repo: Path,
        git: GitRepository,
        spec: VerificationSpec,
        artifact_dir: Path,
        index: int,
    ) -> CommandResult:
        parts = self.validate(spec.command)
        before = git.snapshot(cwd=repo)
        timeout = spec.timeout_seconds or self.config.verification_timeout_seconds
        result = run_process(parts, cwd=repo, timeout=timeout)
        stdout_path = artifact_dir / f"{index:02d}.stdout.log"
        stderr_path = artifact_dir / f"{index:02d}.stderr.log"
        atomic_write_text(stdout_path, result.stdout)
        atomic_write_text(stderr_path, result.stderr)
        after = git.snapshot(cwd=repo)
        mutation = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
        error = None
        passed = result.succeeded
        if mutation:
            passed = False
            error = f"Verification mutated tracked/untracked repository state: {mutation}"
        elif not result.succeeded:
            error = "Command timed out" if result.timed_out else f"Exit code {result.return_code}"
        return CommandResult(
            command=spec.command,
            exit_code=result.return_code,
            duration_seconds=result.duration_seconds,
            passed=passed,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            error=error,
        )
