from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .util import redact


@dataclass(slots=True)
class ProcessResult:
    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.return_code == 0 and not self.timed_out


def command_prefix(value: str) -> list[str]:
    def strip_wrapping_quotes(token: str) -> str:
        token = token.strip()
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
            return token[1:-1]
        return token

    candidate = Path(value).expanduser()
    if candidate.exists():
        return [str(candidate.resolve())]
    try:
        tokens = shlex.split(value, posix=(os.name != "nt"))
    except ValueError:
        tokens = shlex.split(value, posix=False)
    tokens = [strip_wrapping_quotes(token) for token in tokens]
    if not tokens:
        return []
    if os.name == "nt":
        for length in range(len(tokens), 0, -1):
            executable = " ".join(tokens[:length])
            resolved = Path(executable).expanduser()
            if not resolved.exists() or not resolved.is_file():
                continue
            remainder = [strip_wrapping_quotes(token) for token in tokens[length:]]
            if remainder:
                for trailing_length in range(len(remainder), 0, -1):
                    argument = Path(" ".join(remainder[:trailing_length])).expanduser()
                    if argument.exists() and argument.is_file():
                        return [str(resolved.resolve()), str(argument.resolve()), *remainder[trailing_length:]]
            return [str(resolved.resolve()), *remainder]
    return [token for token in tokens if token]


def run_process(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    timeout: int = 3600,
    env: Mapping[str, str] | None = None,
) -> ProcessResult:
    merged_env = os.environ.copy()
    merged_env.setdefault("PYTHONUTF8", "1")
    merged_env.setdefault("PYTHONIOENCODING", "utf-8")
    merged_env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    command = list(command)
    if command and command[0] and os.path.basename(command[0]).lower() in {"python", "python.exe", "python3", "python3.exe"}:
        if "-B" not in command:
            command.insert(1, "-B")
    if env:
        merged_env.update(env)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=merged_env,
            check=False,
        )
        return ProcessResult(
            command=list(command),
            return_code=completed.returncode,
            stdout=redact(completed.stdout),
            stderr=redact(completed.stderr),
            duration_seconds=round(time.monotonic() - started, 3),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return ProcessResult(
            command=list(command),
            return_code=124,
            stdout=redact(stdout),
            stderr=redact(stderr),
            duration_seconds=round(time.monotonic() - started, 3),
            timed_out=True,
        )
