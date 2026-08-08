from __future__ import annotations

import filecmp
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .errors import LunaForgeError
from .git import GitRepository
from .process import run_process
from .util import digest_object, sha256_file

if TYPE_CHECKING:
    from .config import AppConfig

SKILL_RELATIVE_PATH = Path(".agents/skills/luna-forge")
AGENT_RELATIVE_PATH = Path(".codex/agents/luna-worker.toml")
BACKUP_RELATIVE_PATH = Path(".luna-forge-backups")
SOURCE_SKILL = Path("skill/luna-forge")
SOURCE_AGENT = Path("codex/agents/luna-worker.toml")
SOURCE_VERSION = Path("VERSION")
SOURCE_MANIFEST = Path("MANIFEST.sha256")
SOURCE_VALIDATE = Path("scripts/validate.py")
SOURCE_INSTALLER = Path("scripts/install.py")


@dataclass(slots=True)
class LunaForgeStatus:
    enabled: bool
    repository: str
    requested_ref: str
    expected_commit: str
    resolved_commit: str | None
    required_version: str
    source_version: str | None
    source_valid: bool
    source_digest: str | None
    cache_path: str
    integration_mode: str
    skill_path: str
    agent_path: str
    skill_exact: bool
    agent_exact: bool
    installed: bool
    conflict: bool
    auto_fetch: bool
    auto_install: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def digest(self) -> str:
        return digest_object(
            {
                "repository": self.repository,
                "requested_ref": self.requested_ref,
                "expected_commit": self.expected_commit,
                "resolved_commit": self.resolved_commit,
                "required_version": self.required_version,
                "source_version": self.source_version,
                "source_valid": self.source_valid,
                "source_digest": self.source_digest,
                "skill_exact": self.skill_exact,
                "agent_exact": self.agent_exact,
                "installed": self.installed,
                "conflict": self.conflict,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "repository": self.repository,
            "requested_ref": self.requested_ref,
            "expected_commit": self.expected_commit,
            "resolved_commit": self.resolved_commit,
            "required_version": self.required_version,
            "source_version": self.source_version,
            "source_valid": self.source_valid,
            "source_digest": self.source_digest,
            "cache_path": self.cache_path,
            "integration_mode": self.integration_mode,
            "skill_path": self.skill_path,
            "agent_path": self.agent_path,
            "skill_exact": self.skill_exact,
            "agent_exact": self.agent_exact,
            "installed": self.installed,
            "conflict": self.conflict,
            "auto_fetch": self.auto_fetch,
            "auto_install": self.auto_install,
            "errors": self.errors,
            "warnings": self.warnings,
            "digest": self.digest,
        }


@dataclass(slots=True)
class LunaForgeInstallResult:
    changed: bool
    dry_run: bool
    fetched: bool
    backed_up: list[str]
    installed: list[str]
    status: LunaForgeStatus
    command_output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "dry_run": self.dry_run,
            "fetched": self.fetched,
            "backed_up": self.backed_up,
            "installed": self.installed,
            "command_output": self.command_output,
            "status": self.status.to_dict(),
        }


class LunaForgeManager:
    """Fetch, validate, and install a commit-pinned upstream Luna Forge checkout."""

    def __init__(self, config: "AppConfig") -> None:
        self.config = config
        self.settings = config.luna_forge
        self.cache_root = self._cache_root()
        self.checkout = self.cache_root / self.settings.expected_commit

    def applies_to_alias(self, alias: str) -> bool:
        return self.settings.enabled and alias in self.settings.invoke_for_aliases

    def inspect(self, repo: Path) -> LunaForgeStatus:
        repo = repo.expanduser().resolve()
        errors: list[str] = []
        warnings: list[str] = []
        source_valid = False
        resolved_commit: str | None = None
        source_version: str | None = None
        source_digest: str | None = None

        if self.settings.enabled:
            try:
                source = self._validate_cached_source()
                source_valid = True
                resolved_commit = source["commit"]
                source_version = source["version"]
                source_digest = source["digest"]
            except LunaForgeError as exc:
                warnings.append(str(exc))

        skill_dest = repo / SKILL_RELATIVE_PATH
        agent_dest = repo / AGENT_RELATIVE_PATH
        try:
            self._require_safe_destination(repo, skill_dest)
            self._require_safe_destination(repo, agent_dest)
            self._require_safe_destination(repo, repo / BACKUP_RELATIVE_PATH)
        except LunaForgeError as exc:
            errors.append(str(exc))

        source_skill = self.checkout / SOURCE_SKILL
        source_agent = self.checkout / SOURCE_AGENT
        skill_exact = source_valid and not errors and self._same_tree(source_skill, skill_dest)
        agent_exact = source_valid and not errors and self._same_file(source_agent, agent_dest)
        skill_exists = skill_dest.exists() or skill_dest.is_symlink()
        agent_exists = agent_dest.exists() or agent_dest.is_symlink()
        installed = skill_exact and agent_exact
        conflict = False

        if skill_exists and source_valid and not skill_exact:
            conflict = True
            errors.append(f"Different or unsafe Luna Forge skill exists at {skill_dest}")
        if agent_exists and source_valid and not agent_exact:
            conflict = True
            errors.append(f"Different or unsafe Luna worker agent exists at {agent_dest}")
        if source_valid and skill_exact != agent_exact:
            conflict = True
            errors.append("Luna Forge installation is partial; the skill and agent must both match upstream")
        if self.settings.enabled and not source_valid:
            warnings.append("The pinned Luna Forge source is not cached and validated yet")
        if self.settings.enabled and source_valid and not installed and not conflict:
            warnings.append("Luna Forge is not installed in this repository yet")

        return LunaForgeStatus(
            enabled=self.settings.enabled,
            repository=self.settings.repository,
            requested_ref=self.settings.ref,
            expected_commit=self.settings.expected_commit,
            resolved_commit=resolved_commit,
            required_version=self.settings.required_version,
            source_version=source_version,
            source_valid=source_valid,
            source_digest=source_digest,
            cache_path=str(self.checkout),
            integration_mode="pinned-github-source",
            skill_path=str(skill_dest),
            agent_path=str(agent_dest),
            skill_exact=skill_exact,
            agent_exact=agent_exact,
            installed=installed,
            conflict=conflict,
            auto_fetch=self.settings.auto_fetch,
            auto_install=self.settings.auto_install,
            errors=errors,
            warnings=_deduplicate(warnings),
        )

    def fetch_source(self, *, force: bool = False) -> tuple[Path, bool]:
        if not self.settings.enabled:
            raise LunaForgeError("Luna Forge integration is disabled")
        self._validate_repository_url()
        try:
            self._validate_cached_source()
            if not force:
                return self.checkout, False
        except LunaForgeError:
            pass

        self._require_safe_cache_root(create=True)
        lock = self.cache_root / f".{self.settings.expected_commit}.lock"
        self._acquire_lock(lock)
        try:
            try:
                self._validate_cached_source()
                if not force:
                    return self.checkout, False
            except LunaForgeError:
                pass

            temporary = Path(tempfile.mkdtemp(prefix=".luna-forge-fetch-", dir=self.cache_root))
            try:
                self._run_git(["init", "-q"], cwd=temporary)
                self._run_git(["remote", "add", "origin", self.settings.repository], cwd=temporary)
                fetch = run_process(
                    ["git", "fetch", "--depth", "1", "origin", self.settings.ref],
                    cwd=temporary,
                    timeout=min(self.config.command_timeout_seconds, 900),
                )
                if not fetch.succeeded:
                    raise LunaForgeError(
                        "Could not fetch the pinned Luna Forge ref from GitHub: "
                        + (fetch.stderr.strip() or fetch.stdout.strip())
                    )
                self._run_git(["checkout", "--detach", "-q", "FETCH_HEAD"], cwd=temporary)
                self._validate_source(temporary, force_validator=True)
                if self.checkout.exists():
                    if not force:
                        raise LunaForgeError(f"Validated cache destination already exists: {self.checkout}")
                    shutil.rmtree(self.checkout)
                os.replace(temporary, self.checkout)
            except Exception:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
            self._validate_cached_source()
            return self.checkout, True
        finally:
            shutil.rmtree(lock, ignore_errors=True)

    def ensure_project_install(
        self,
        repo: Path,
        *,
        force: bool = False,
        dry_run: bool = False,
        add_local_excludes: bool = True,
    ) -> LunaForgeInstallResult:
        repo = repo.expanduser().resolve()
        if not self.settings.enabled:
            status = self.inspect(repo)
            return LunaForgeInstallResult(False, dry_run, False, [], [], status)

        fetched = False
        try:
            self._validate_cached_source()
        except LunaForgeError:
            if not self.settings.auto_fetch and not force:
                raise LunaForgeError(
                    "Pinned Luna Forge source is not cached. Run `codex-armada forge fetch` "
                    "or enable [luna_forge].auto_fetch."
                )
            _, fetched = self.fetch_source(force=False)

        before = self.inspect(repo)
        if before.installed:
            if add_local_excludes and not dry_run:
                self._add_excludes(repo)
            return LunaForgeInstallResult(False, dry_run, fetched, [], [], self.inspect(repo))
        if before.conflict and not force:
            raise LunaForgeError(
                "Luna Forge conflicts with existing project files. Review them and use `--force` only when replacement "
                "is intentional.\n- " + "\n- ".join(before.errors)
            )

        command = [
            sys.executable,
            str(self.checkout / SOURCE_INSTALLER),
            "--scope",
            "project",
            "--project-root",
            str(repo),
        ]
        if dry_run:
            command.append("--dry-run")
        if force:
            command.append("--force")
        result = run_process(command, cwd=self.checkout, timeout=min(self.config.command_timeout_seconds, 900))
        if not result.succeeded:
            raise LunaForgeError(result.stderr.strip() or result.stdout.strip() or "Luna Forge installer failed")

        if add_local_excludes and not dry_run:
            self._add_excludes(repo)
        after = self.inspect(repo)
        if not dry_run and (not after.installed or after.errors):
            raise LunaForgeError("Upstream installer completed, but the project installation failed exact verification")

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        backups = [line[len("BACKUP ") :] for line in lines if line.startswith("BACKUP ")]
        installed = [
            line.split(" ", 1)[1]
            for line in lines
            if line.startswith(("INSTALL ", "REPLACE ")) and " " in line
        ]
        changed = any(line.startswith(("INSTALL ", "REPLACE ")) for line in lines)
        return LunaForgeInstallResult(changed, dry_run, fetched, backups, installed, after, result.stdout)

    def require_installed(self, repo: Path) -> LunaForgeStatus:
        status = self.inspect(repo)
        if not status.source_valid:
            raise LunaForgeError("The pinned Luna Forge source is unavailable or failed validation")
        if not status.installed or status.conflict or status.errors:
            detail = "\n- ".join(status.errors + status.warnings)
            raise LunaForgeError("Luna Forge is not installed exactly" + (f":\n- {detail}" if detail else ""))
        return status

    def require_unchanged(self, repo: Path, baseline: LunaForgeStatus, *, actor: str) -> LunaForgeStatus:
        current = self.require_installed(repo)
        if current.digest != baseline.digest:
            raise LunaForgeError(
                f"{actor} changed Luna Forge source or project installation; acceptance is blocked "
                f"(before={baseline.digest[:16]}, after={current.digest[:16]})"
            )
        return current

    def remove_exact_project_install(self, repo: Path) -> None:
        status = self.inspect(repo)
        if not status.installed:
            return
        skill = repo.resolve() / SKILL_RELATIVE_PATH
        agent = repo.resolve() / AGENT_RELATIVE_PATH
        shutil.rmtree(skill)
        agent.unlink()
        for parent in (agent.parent, skill.parent, skill.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                pass

    def _validate_cached_source(self) -> dict[str, str]:
        self._require_safe_cache_root(create=False)
        if self.checkout.is_symlink() or not self.checkout.is_dir():
            raise LunaForgeError(f"Pinned Luna Forge cache is missing: {self.checkout}")
        return self._validate_source(self.checkout)

    def _validate_source(self, root: Path, *, force_validator: bool = False) -> dict[str, str]:
        for required in (
            SOURCE_SKILL,
            SOURCE_AGENT,
            SOURCE_VERSION,
            SOURCE_MANIFEST,
            SOURCE_VALIDATE,
            SOURCE_INSTALLER,
        ):
            candidate = root / required
            if not candidate.exists() or candidate.is_symlink():
                raise LunaForgeError(f"Luna Forge source is missing or unsafe: {required.as_posix()}")

        commit = self._git_output(["rev-parse", "HEAD"], cwd=root).lower()
        if commit != self.settings.expected_commit:
            raise LunaForgeError(
                f"Luna Forge commit mismatch: expected {self.settings.expected_commit}, observed {commit}"
            )
        status = self._git_output(["status", "--porcelain=v1", "--untracked-files=all"], cwd=root)
        if status.strip():
            raise LunaForgeError("Cached Luna Forge checkout is modified or contains untracked files")
        version = (root / SOURCE_VERSION).read_text(encoding="utf-8").strip()
        if version != self.settings.required_version:
            raise LunaForgeError(
                f"Luna Forge version mismatch: expected {self.settings.required_version}, observed {version}"
            )
        self._require_no_untracked_and_no_submodules(root)

        manifest_summary = self._verify_manifest(root)
        manifest_hash = sha256_file(root / SOURCE_MANIFEST)
        validator_hash = sha256_file(root / SOURCE_VALIDATE)
        validation_key = {
            "commit": commit,
            "version": version,
            "manifest_sha256": manifest_hash,
            "validator_sha256": validator_hash,
        }
        if self.settings.strict_integrity and (force_validator or not self._validation_marker_matches(validation_key)):
            validation = run_process(
                [sys.executable, str(root / SOURCE_VALIDATE)],
                cwd=root,
                timeout=min(self.config.command_timeout_seconds, 900),
            )
            if not validation.succeeded:
                raise LunaForgeError(
                    "Upstream Luna Forge validation failed: "
                    + (validation.stderr.strip() or validation.stdout.strip())
                )
            post_status = self._git_output(["status", "--porcelain=v1", "--untracked-files=all"], cwd=root)
            if post_status.strip():
                raise LunaForgeError("Upstream Luna Forge validation modified the pinned checkout")
            self._write_validation_marker(validation_key)

        return {
            "commit": commit,
            "version": version,
            "digest": digest_object(
                {
                    "repository": self.settings.repository,
                    "commit": commit,
                    "version": version,
                    "manifest_sha256": manifest_hash,
                    "manifest_entries": manifest_summary["entries"],
                    "manifest_mode": manifest_summary["mode"],
                    "manifest_unmanifested": manifest_summary["unmanifested"],
                    "validator_sha256": validator_hash,
                }
            ),
        }

    @property
    def _validation_marker_path(self) -> Path:
        return self.cache_root / f".{self.settings.expected_commit}.validated.json"

    def _validation_marker_matches(self, expected: dict[str, str]) -> bool:
        marker = self._validation_marker_path
        if not marker.is_file() or marker.is_symlink():
            return False
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return False
        return payload == expected

    def _write_validation_marker(self, payload: dict[str, str]) -> None:
        self._require_safe_cache_root(create=True)
        marker = self._validation_marker_path
        temporary = marker.with_name(f".{marker.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, marker)

    def _verify_manifest(self, root: Path) -> dict[str, Any]:
        entries = 0
        manifest_paths: set[str] = set()
        manifest_source = root / SOURCE_MANIFEST
        for line_number, raw in enumerate(manifest_source.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            parts = raw.split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                raise LunaForgeError(f"Invalid MANIFEST.sha256 line {line_number}")
            expected, relative = parts[0].lower(), parts[1].strip().replace("\\", "/")
            relative_path = PurePosixPath(relative)
            if (
                not relative
                or relative == SOURCE_MANIFEST.as_posix()
                or relative_path.is_absolute()
                or any(part in {"", ".", ".."} for part in relative_path.parts)
                or (relative_path.parts and ":" in relative_path.parts[0])
                or "\x00" in relative
            ):
                raise LunaForgeError(f"Unsafe manifest path: {relative}")
            if relative in manifest_paths:
                raise LunaForgeError(f"Duplicate manifest path: {relative}")
            manifest_paths.add(relative)
            candidate = (root / Path(*relative_path.parts)).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError as exc:
                raise LunaForgeError(f"Manifest path escapes the source root: {relative}") from exc
            if not candidate.is_file() or candidate.is_symlink():
                raise LunaForgeError(f"Manifest file is missing or unsafe: {relative}")
            actual = sha256_file(candidate)
            if actual != expected:
                raise LunaForgeError(f"Manifest digest mismatch: {relative}")
            entries += 1
        if entries == 0:
            raise LunaForgeError("Luna Forge manifest is empty")

        try:
            tracked_files = self._tracked_files(root)
        except LunaForgeError:
            tracked_files = {
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_file() and ".git" not in path.relative_to(root).parts
            }
        tracked_managed = {
            path
            for path in tracked_files
            if path != SOURCE_MANIFEST.as_posix() and not path.startswith(f"{SOURCE_MANIFEST.as_posix()}/")
        }

        actual_paths: set[str] = set()
        for candidate in root.rglob("*"):
            relative_path = candidate.relative_to(root)
            if ".git" in relative_path.parts:
                continue
            relative = relative_path.as_posix()
            if relative == SOURCE_MANIFEST.as_posix():
                continue
            if candidate.is_symlink():
                raise LunaForgeError(f"Untrusted symbolic link in Luna Forge source: {relative}")
            if candidate.is_file():
                actual_paths.add(relative)
        unmanifested = sorted(tracked_managed - manifest_paths)
        missing = sorted(manifest_paths - actual_paths)
        mode = "complete"
        if unmanifested:
            mode = "package"
        if missing:
            raise LunaForgeError(f"Manifest paths missing from Luna Forge source: {missing[:10]}")
        if mode == "complete":
            return {"entries": entries, "mode": mode, "unmanifested": []}
        return {"entries": entries, "mode": mode, "unmanifested": unmanifested}

    def _tracked_files(self, root: Path) -> set[str]:
        raw = self._git_output(["ls-files", "-z"], cwd=root)
        if not raw:
            return set()
        files = {Path(item).as_posix() for item in raw.split("\u0000") if item}
        return files

    def _require_no_untracked_and_no_submodules(self, root: Path) -> None:
        stage = self._git_output(["ls-files", "--stage"], cwd=root)
        for line in stage.splitlines():
            fields = line.split()
            if len(fields) < 4:
                continue
            if fields[1] == "160000":
                raise LunaForgeError(f"Unexpected submodule in Luna Forge checkout: {fields[3]}")
        status = self._git_output(["status", "--porcelain=v1", "--untracked-files=all"], cwd=root)
        if status.strip():
            raise LunaForgeError("Cached Luna Forge checkout is modified or contains untracked files")

    def _validate_repository_url(self) -> None:
        value = self.settings.repository.strip()
        if not value:
            raise LunaForgeError("Luna Forge repository URL is empty")
        if self.settings.allow_non_github_source:
            return
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
            raise LunaForgeError(
                "Luna Forge source must be an HTTPS GitHub repository unless allow_non_github_source is explicit"
            )

    def _require_safe_cache_root(self, *, create: bool) -> None:
        if create:
            self.cache_root.mkdir(parents=True, exist_ok=True)
        if not self.cache_root.exists():
            return
        if self.cache_root.is_symlink() or not self.cache_root.is_dir():
            raise LunaForgeError(f"Luna Forge cache root is not a real directory: {self.cache_root}")
        if self.checkout.exists() or self.checkout.is_symlink():
            if self.checkout.is_symlink():
                raise LunaForgeError(f"Pinned Luna Forge cache must not be a symbolic link: {self.checkout}")
            try:
                self.checkout.resolve().relative_to(self.cache_root.resolve())
            except ValueError as exc:
                raise LunaForgeError(f"Pinned Luna Forge cache escapes its cache root: {self.checkout}") from exc

    def _cache_root(self) -> Path:
        if self.settings.cache_dir:
            return Path(os.path.expandvars(self.settings.cache_dir)).expanduser().resolve()
        override = os.environ.get("CODEX_ARMADA_CACHE_DIR")
        if override:
            return Path(override).expanduser().resolve() / "luna-forge"
        if os.name == "nt":
            local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            if local:
                return Path(local) / "CodexArmada" / "cache" / "luna-forge"
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Caches" / "CodexArmada" / "luna-forge"
        xdg = os.environ.get("XDG_CACHE_HOME")
        if xdg:
            return Path(xdg) / "codex-armada" / "luna-forge"
        return Path.home() / ".cache" / "codex-armada" / "luna-forge"

    def _add_excludes(self, repo: Path) -> None:
        git = GitRepository(repo)
        git.add_local_exclude(SKILL_RELATIVE_PATH.as_posix() + "/", comment="Codex Armada Luna Forge skill")
        git.add_local_exclude(AGENT_RELATIVE_PATH.as_posix(), comment="Codex Armada Luna Forge agent")
        git.add_local_exclude(BACKUP_RELATIVE_PATH.as_posix() + "/", comment="Luna Forge local backups")

    def _require_safe_destination(self, repo: Path, destination: Path) -> None:
        repo = repo.resolve()
        try:
            destination.resolve(strict=False).relative_to(repo)
        except ValueError as exc:
            raise LunaForgeError(f"Luna Forge destination escapes the repository: {destination}") from exc
        current = destination
        while current != repo:
            if current.is_symlink():
                raise LunaForgeError(f"Luna Forge destination traverses a symbolic link: {current}")
            current = current.parent

    @staticmethod
    def _same_file(left: Path, right: Path) -> bool:
        return (
            left.is_file()
            and right.is_file()
            and not left.is_symlink()
            and not right.is_symlink()
            and sha256_file(left) == sha256_file(right)
        )

    @classmethod
    def _same_tree(cls, left: Path, right: Path) -> bool:
        if not left.is_dir() or not right.is_dir() or left.is_symlink() or right.is_symlink():
            return False
        comparison = filecmp.dircmp(left, right)
        if comparison.left_only or comparison.right_only or comparison.funny_files:
            return False
        if any(not cls._same_file(left / name, right / name) for name in comparison.common_files):
            return False
        return all(cls._same_tree(left / name, right / name) for name in comparison.common_dirs)

    @staticmethod
    def _acquire_lock(lock: Path, *, timeout: int = 60, stale_after: int = 900) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                lock.mkdir()
                (lock / "owner").write_text(f"pid={os.getpid()}\ncreated={time.time()}\n", encoding="utf-8")
                return
            except FileExistsError:
                try:
                    age = time.time() - lock.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > stale_after:
                    shutil.rmtree(lock, ignore_errors=True)
                    continue
                if time.monotonic() >= deadline:
                    raise LunaForgeError(f"Timed out waiting for Luna Forge cache lock: {lock}")
                time.sleep(0.1)

    @staticmethod
    def _run_git(args: list[str], *, cwd: Path) -> None:
        result = run_process(["git", *args], cwd=cwd, timeout=300)
        if not result.succeeded:
            raise LunaForgeError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")

    @staticmethod
    def _git_output(args: list[str], *, cwd: Path) -> str:
        result = run_process(["git", *args], cwd=cwd, timeout=120)
        if not result.succeeded:
            raise LunaForgeError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
        return result.stdout.strip()


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
