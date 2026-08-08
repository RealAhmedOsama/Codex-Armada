from __future__ import annotations

import json
import os
import secrets
import time
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from .domain import RunRecord
from .errors import StateError
from .paths import ProjectPaths
from .util import atomic_write_json, compact_timestamp, read_json, slugify, utc_now


class StateStore:
    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths

    def create_run_id(self, goal: str) -> str:
        return f"{compact_timestamp()}-{slugify(goal, fallback='run', max_length=30)}-{secrets.token_hex(2)}"

    def save(self, record: RunRecord) -> Path:
        record.touch()
        path = self.paths.run_root(record.run_id) / "run.json"
        atomic_write_json(path, record.to_dict())
        return path

    def load(self, run_id: str) -> RunRecord:
        path = self.paths.run_root(run_id) / "run.json"
        if not path.is_file():
            raise StateError(f"Run not found: {run_id}")
        try:
            return RunRecord.from_dict(read_json(path))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise StateError(f"Run state is invalid: {path}: {exc}") from exc

    def list(self) -> list[RunRecord]:
        if not self.paths.runs_root.is_dir():
            return []
        records: list[RunRecord] = []
        for path in sorted(self.paths.runs_root.glob("*/run.json"), reverse=True):
            try:
                records.append(RunRecord.from_dict(read_json(path)))
            except Exception:
                continue
        return records

    def latest(self) -> RunRecord:
        records = self.list()
        if not records:
            raise StateError("No runs exist for this repository")
        return records[0]

    def artifact_dir(self, run_id: str, *parts: str) -> Path:
        path = self.paths.run_root(run_id).joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path


class ProjectLock(AbstractContextManager["ProjectLock"]):
    def __init__(self, path: Path, *, stale_after_seconds: int = 12 * 3600) -> None:
        self.path = path
        self.stale_after_seconds = stale_after_seconds
        self.acquired = False

    def __enter__(self) -> "ProjectLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(json.dumps({"pid": os.getpid(), "created_at": utc_now()}))
                self.acquired = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > self.stale_after_seconds:
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                detail = ""
                try:
                    detail = self.path.read_text(encoding="utf-8")
                except OSError:
                    pass
                raise StateError(f"Another Codex Armada run holds the project lock: {detail or self.path}")
        raise StateError(f"Could not acquire project lock: {self.path}")

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False
