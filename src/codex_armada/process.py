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
    candidate = Path(value).expanduser()
    if candidate.exists():
        return [str(candidate.resolve())]
    return shlex.split(value, posix=os.name != "nt")


def run_process(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    timeout: int = 3600,
    env: Mapping[str, str] | None = None,
) -> ProcessResult:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command),
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
