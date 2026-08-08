from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .util import sha256_text


@dataclass(slots=True)
class ProjectPaths:
    repo: Path
    state_root: Path
    project_root: Path
    runs_root: Path
    worktrees_root: Path
    capabilities_file: Path
    project_lock: Path

    def run_root(self, run_id: str) -> Path:
        return self.runs_root / run_id


def app_state_root() -> Path:
    override = os.environ.get("CODEX_ARMADA_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if local:
            return Path(local) / "CodexArmada"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CodexArmada"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "codex-armada"
    return Path.home() / ".local" / "share" / "codex-armada"


def project_paths(repo: Path) -> ProjectPaths:
    resolved = repo.expanduser().resolve()
    identity = str(resolved).casefold() if os.name == "nt" else str(resolved)
    project_key = sha256_text(identity)[:16]
    root = app_state_root()
    project = root / "projects" / project_key
    return ProjectPaths(
        repo=resolved,
        state_root=root,
        project_root=project,
        runs_root=project / "runs",
        worktrees_root=project / "worktrees",
        capabilities_file=project / "capabilities.lock.json",
        project_lock=project / "project.lock",
    )
