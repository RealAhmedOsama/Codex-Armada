from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from .errors import GitSafetyError
from .process import ProcessResult, run_process
from .util import atomic_write_text, normalize_git_path, sha256_file, sha256_text, slugify


@dataclass(slots=True)
class GitStatusEntry:
    path: str
    code: str
    original_path: str | None = None

    @property
    def deleted(self) -> bool:
        return "D" in self.code

    @property
    def renamed(self) -> bool:
        return "R" in self.code and self.original_path is not None

    @property
    def display_path(self) -> str:
        return f"{self.original_path} -> {self.path}" if self.renamed else self.path


class GitRepository:
    def __init__(self, repo: Path) -> None:
        self.repo = repo.expanduser().resolve()
        result = self._run(["rev-parse", "--show-toplevel"], timeout=30)
        if not result.succeeded:
            raise GitSafetyError(f"Not a Git repository: {self.repo}: {result.stderr.strip()}")
        top = Path(result.stdout.strip()).resolve()
        if top != self.repo:
            self.repo = top

    def _run(self, args: list[str], *, cwd: Path | None = None, timeout: int = 120) -> ProcessResult:
        return run_process(["git", *args], cwd=cwd or self.repo, timeout=timeout)

    def require_clean(self) -> None:
        entries = self.status()
        if entries:
            rendered = ", ".join(f"{item.code} {item.display_path}" for item in entries[:20])
            raise GitSafetyError(f"Working tree must be clean before orchestration: {rendered}")

    def status(self, *, cwd: Path | None = None) -> list[GitStatusEntry]:
        result = self._run(["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=cwd)
        if not result.succeeded:
            raise GitSafetyError(result.stderr.strip() or "git status failed")
        return _parse_status_z(result.stdout)

    def changed_files(self, *, cwd: Path | None = None) -> list[str]:
        changed: set[str] = set()
        for item in self.status(cwd=cwd):
            changed.add(item.path)
            if item.renamed and item.original_path:
                changed.add(item.original_path)
        return sorted(changed)

    def deleted_files(self, *, cwd: Path | None = None) -> list[str]:
        deleted: set[str] = set()
        for item in self.status(cwd=cwd):
            if item.deleted:
                deleted.add(item.path)
            if item.renamed and item.original_path:
                deleted.add(item.original_path)
        return sorted(deleted)

    def symlink_files(self, paths: Iterable[str], *, cwd: Path | None = None) -> list[str]:
        root = (cwd or self.repo).resolve()
        return sorted(
            normalize_git_path(path)
            for path in paths
            if (root / normalize_git_path(path)).is_symlink()
        )

    def head(self, *, cwd: Path | None = None) -> str:
        result = self._run(["rev-parse", "HEAD"], cwd=cwd)
        if not result.succeeded:
            raise GitSafetyError(result.stderr.strip() or "Unable to resolve HEAD")
        return result.stdout.strip()

    def branch(self, *, cwd: Path | None = None) -> str:
        result = self._run(["branch", "--show-current"], cwd=cwd)
        if not result.succeeded:
            raise GitSafetyError(result.stderr.strip() or "Unable to resolve branch")
        return result.stdout.strip() or "(detached)"

    def snapshot(self, *, cwd: Path | None = None) -> dict[str, str]:
        root = (cwd or self.repo).resolve()
        result: dict[str, str] = {}

        def capture(path: str, code: str) -> None:
            candidate = root / path
            if candidate.is_symlink():
                try:
                    content = f"symlink:{os.readlink(candidate)}"
                except OSError:
                    content = "symlink:unreadable"
            elif candidate.is_file():
                try:
                    content = sha256_file(candidate)
                except OSError:
                    content = "unreadable"
            elif candidate.exists():
                content = "non-file"
            else:
                content = "missing"
            result[path] = f"{code}:{content}"

        for item in self.status(cwd=cwd):
            capture(item.path, item.code)
            if item.renamed and item.original_path:
                capture(item.original_path, "D ")
        return result

    def diff(self, paths: list[str] | None = None, *, cwd: Path | None = None) -> str:
        tracked_args = ["diff", "--no-ext-diff", "--binary"]
        cached_args = ["diff", "--cached", "--no-ext-diff", "--binary"]
        if paths:
            tracked_args.extend(["--", *paths])
            cached_args.extend(["--", *paths])
        tracked = self._run(tracked_args, cwd=cwd, timeout=300)
        cached = self._run(cached_args, cwd=cwd, timeout=300)
        if not tracked.succeeded or not cached.succeeded:
            raise GitSafetyError((tracked.stderr or cached.stderr).strip() or "git diff failed")
        return tracked.stdout + cached.stdout

    def evidence_diff(self, paths: list[str], *, cwd: Path | None = None) -> str:
        root = (cwd or self.repo).resolve()
        rendered = self.diff(paths, cwd=cwd)
        status_by_path = {item.path: item.code for item in self.status(cwd=cwd)}
        for path in paths:
            if status_by_path.get(path) != "??":
                continue
            candidate = root / path
            if not candidate.is_file():
                continue
            result = run_process(
                ["git", "diff", "--no-index", "--binary", "--", os.devnull, str(candidate)],
                cwd=root,
                timeout=120,
            )
            if result.return_code in {0, 1}:
                rendered += result.stdout
            else:
                rendered += f"\n# Untracked file: {path} (diff unavailable: {result.stderr.strip()})\n"
        return rendered

    def create_worktree(self, *, path: Path, base_commit: str, branch_name: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise GitSafetyError(f"Worktree path already exists: {path}")
        result = self._run(["worktree", "add", "-b", branch_name, str(path), base_commit], timeout=300)
        if not result.succeeded:
            raise GitSafetyError(f"Could not create worktree: {result.stderr.strip()}")

    def remove_worktree(self, path: Path, *, branch_name: str | None = None, force: bool = False) -> None:
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(path))
        result = self._run(args, timeout=300)
        if not result.succeeded and path.exists():
            raise GitSafetyError(f"Could not remove worktree: {result.stderr.strip()}")
        self._run(["worktree", "prune"], timeout=120)
        if branch_name:
            delete = self._run(["branch", "-D", branch_name], timeout=120)
            if not delete.succeeded and "not found" not in delete.stderr.lower():
                raise GitSafetyError(f"Could not remove temporary branch: {delete.stderr.strip()}")

    def commit(self, paths: list[str], message: str, *, cwd: Path) -> str:
        if not paths:
            raise GitSafetyError("Refusing to create an empty task commit")
        normalized = sorted({normalize_git_path(path) for path in paths})
        existing = [path for path in normalized if (cwd / path).exists() or (cwd / path).is_symlink()]
        missing = [path for path in normalized if path not in existing]
        if existing:
            stage_existing = self._run(["add", "--", *existing], cwd=cwd, timeout=300)
            if not stage_existing.succeeded:
                raise GitSafetyError(f"Could not stage task files: {stage_existing.stderr.strip()}")
        for missing_path in missing:
            # Deleted paths and rename sources no longer exist in the worktree. `git
            # add -u` stages their tracked removal. A path moved with `git mv` may
            # already be staged and then no longer matches a pathspec; accept that
            # case only when no unstaged diff remains for the original path.
            stage_missing = self._run(["add", "-u", "--", missing_path], cwd=cwd, timeout=300)
            if not stage_missing.succeeded:
                unstaged = self._run(["diff", "--name-only", "--", missing_path], cwd=cwd, timeout=120)
                if not unstaged.succeeded or unstaged.stdout.strip():
                    raise GitSafetyError(
                        f"Could not stage deleted task file {missing_path}: {stage_missing.stderr.strip()}"
                    )
        staged = self._run(["diff", "--cached", "--name-only", "-z"], cwd=cwd, timeout=120)
        if not staged.succeeded:
            raise GitSafetyError(staged.stderr.strip() or "Could not inspect staged files")
        staged_files = sorted(filter(None, staged.stdout.split("\0")))
        unexpected = sorted(set(staged_files) - set(normalized))
        if unexpected:
            raise GitSafetyError(f"Unexpected staged files: {unexpected}")
        commit = self._run(["commit", "-m", message], cwd=cwd, timeout=300)
        if not commit.succeeded:
            raise GitSafetyError(f"Task commit failed: {commit.stderr.strip() or commit.stdout.strip()}")
        return self.head(cwd=cwd)

    def apply_commit(self, commit_sha: str) -> str:
        self.require_clean()
        before = self.head()
        result = self._run(["cherry-pick", commit_sha], timeout=600)
        if not result.succeeded:
            abort = self._run(["cherry-pick", "--abort"], timeout=120)
            if not abort.succeeded and self.head() != before:
                raise GitSafetyError(
                    f"Cherry-pick failed and automatic rollback also failed: {result.stderr.strip()} | {abort.stderr.strip()}"
                )
            raise GitSafetyError(f"Could not apply accepted task commit: {result.stderr.strip() or result.stdout.strip()}")
        return self.head()

    def commit_exists(self, commit_sha: str) -> bool:
        return self._run(["cat-file", "-e", f"{commit_sha}^{{commit}}"], timeout=30).succeeded

    def branch_name_for_task(self, run_id: str, task_id: str) -> str:
        suffix = sha256_text(run_id)[:6]
        return f"codex-armada/{slugify(run_id, max_length=20)}-{suffix}/{slugify(task_id, max_length=24)}"

    def add_local_exclude(
        self, relative_path: str, *, comment: str = "Codex Armada local project artifact"
    ) -> Path:
        normalized = normalize_git_path(relative_path)
        if not normalized or normalized.startswith("../") or "/../" in normalized:
            raise GitSafetyError(f"Unsafe local exclude path: {relative_path}")
        resolved = self._run(["rev-parse", "--git-path", "info/exclude"], timeout=30)
        if not resolved.succeeded or not resolved.stdout.strip():
            raise GitSafetyError(resolved.stderr.strip() or "Could not locate Git info/exclude")
        exclude_path = Path(resolved.stdout.strip())
        if not exclude_path.is_absolute():
            exclude_path = (self.repo / exclude_path).resolve()
        existing = exclude_path.read_text(encoding="utf-8", errors="replace") if exclude_path.is_file() else ""
        lines = [line.strip() for line in existing.splitlines()]
        if normalized not in lines:
            value = existing
            if value and not value.endswith("\n"):
                value += "\n"
            value += f"# {comment}\n{normalized}\n"
            atomic_write_text(exclude_path, value)
        return exclude_path


def path_matches(path: str, pattern: str) -> bool:
    path_value = normalize_git_path(path)
    pattern_value = normalize_git_path(pattern)
    if not pattern_value:
        return False
    pure = PurePosixPath(path_value)
    if pure.match(pattern_value):
        return True
    return fnmatch.fnmatchcase(path_value, pattern_value)


def find_scope_violations(
    changed_files: Iterable[str],
    owned_paths: Iterable[str],
    excluded_paths: Iterable[str],
) -> list[str]:
    owned = [normalize_git_path(value) for value in owned_paths]
    excluded = [normalize_git_path(value) for value in excluded_paths]
    violations: list[str] = []
    for file in changed_files:
        normalized = normalize_git_path(file)
        is_owned = any(path_matches(normalized, pattern) for pattern in owned)
        is_excluded = any(path_matches(normalized, pattern) for pattern in excluded)
        if not is_owned or is_excluded:
            violations.append(normalized)
    return sorted(set(violations))


def find_pattern_matches(paths: Iterable[str], patterns: Iterable[str]) -> list[str]:
    result: list[str] = []
    normalized_patterns = [normalize_git_path(pattern) for pattern in patterns]
    for path in paths:
        if any(path_matches(path, pattern) for pattern in normalized_patterns):
            result.append(normalize_git_path(path))
    return sorted(set(result))


def _parse_status_z(value: str) -> list[GitStatusEntry]:
    parts = value.split("\0")
    result: list[GitStatusEntry] = []
    index = 0
    while index < len(parts):
        record = parts[index]
        index += 1
        if not record:
            continue
        if len(record) < 3:
            continue
        code = record[:2]
        path = normalize_git_path(record[3:])
        original_path: str | None = None
        if "R" in code or "C" in code:
            if index < len(parts) and parts[index]:
                # In porcelain v1 -z output the destination path comes first,
                # followed by the original/source path.
                original_path = normalize_git_path(parts[index])
                index += 1
        result.append(GitStatusEntry(path=path, code=code, original_path=original_path))
    return result
