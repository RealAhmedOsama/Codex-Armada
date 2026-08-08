#!/usr/bin/env python3
"""Build reproducible Codex Armada release artifacts without mutating the repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


class ReleaseError(RuntimeError):
    """Raised when release preconditions or artifact verification fail."""


def run(command: list[str], *, cwd: Path = ROOT) -> str:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise ReleaseError(f"Command failed: {' '.join(command)}\n{detail}")
    return completed.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_identity() -> tuple[str, str, str, str]:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    version = str(project["version"])
    normalized = str(project["name"]).replace("-", "_")
    head = run(["git", "rev-parse", "HEAD"])
    timestamp = run(["git", "show", "-s", "--format=%cI", "HEAD"])
    return str(project["name"]), normalized, version, head + "\n" + timestamp


def require_clean_repository() -> tuple[str, str]:
    inside = run(["git", "rev-parse", "--is-inside-work-tree"])
    if inside != "true":
        raise ReleaseError("Release builds require a Git worktree")
    status = run(["git", "status", "--porcelain=v1", "--untracked-files=all"])
    if status:
        raise ReleaseError("Release builds require a clean repository:\n" + status)
    head = run(["git", "rev-parse", "HEAD"])
    timestamp = run(["git", "show", "-s", "--format=%cI", "HEAD"])
    return head, timestamp


def tracked_files() -> list[Path]:
    raw = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    files: list[Path] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        relative = Path(item.decode("utf-8"))
        candidate = ROOT / relative
        if not candidate.is_file() or candidate.is_symlink():
            raise ReleaseError(f"Tracked release entry is missing or unsafe: {relative.as_posix()}")
        files.append(candidate)
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def add_file(archive: zipfile.ZipFile, source: Path, archive_name: str) -> None:
    info = zipfile.ZipInfo(archive_name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    mode = stat.S_IMODE(source.stat().st_mode)
    info.external_attr = (mode & 0xFFFF) << 16
    archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def write_source_archive(output: Path, *, root_name: str, files: list[Path]) -> Path:
    archive_path = output / f"{root_name}-source.zip"
    archive_path.unlink(missing_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source in files:
            relative = source.relative_to(ROOT).as_posix()
            add_file(archive, source, f"{root_name}/{relative}")
    return archive_path


def portable_git_clone(destination: Path) -> None:
    run(["git", "clone", "--quiet", "--no-hardlinks", "--local", str(ROOT), str(destination)], cwd=ROOT.parent)
    run(["git", "remote", "remove", "origin"], cwd=destination)
    # Standard ZIP extraction does not reliably restore POSIX executable bits.
    # Keep the source repository's tracked modes intact while making the portable
    # clone insensitive to extraction-time mode loss on every supported host.
    run(["git", "config", "core.fileMode", "false"], cwd=destination)
    status = run(["git", "status", "--porcelain=v1"], cwd=destination)
    if status:
        raise ReleaseError("Portable Git clone is unexpectedly dirty:\n" + status)
    for relative in (Path(".git/logs"), Path(".git/hooks")):
        shutil.rmtree(destination / relative, ignore_errors=True)
    exclude = destination / ".git" / "info" / "exclude"
    if exclude.exists():
        exclude.write_text("# Local excludes belong to each clone.\n", encoding="utf-8")

    # Clone populates the index with filesystem timestamps. Rebuild it directly
    # from HEAD after all cleanliness checks so repeated Git-ready archives are
    # byte-for-byte reproducible. The first status command after extraction may
    # refresh stat data, but it remains clean because content and modes match.
    index = destination / ".git" / "index"
    index.unlink(missing_ok=True)
    run(["git", "read-tree", "HEAD"], cwd=destination)


def write_git_ready_archive(output: Path, *, root_name: str) -> Path:
    archive_path = output / f"{root_name}-git-ready.zip"
    archive_path.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-armada-git-ready-") as temporary:
        clone = Path(temporary) / root_name
        portable_git_clone(clone)
        entries = sorted(
            (path for path in clone.rglob("*") if path.is_file() and not path.is_symlink()),
            key=lambda path: path.relative_to(clone).as_posix(),
        )
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for source in entries:
                relative = source.relative_to(clone).as_posix()
                add_file(archive, source, f"{root_name}/{relative}")
    return archive_path


def write_commit_history(output: Path) -> Path:
    path = output / "COMMIT-HISTORY.txt"
    history = run(
        [
            "git",
            "log",
            "--reverse",
            "--date=iso-strict",
            "--pretty=format:%H%nAuthor: %an <%ae>%nDate: %aI%nSubject: %s%n%n%b%n---",
        ]
    )
    path.write_text(history.rstrip() + "\n", encoding="utf-8")
    return path


def copy_optional_artifact(source: Path | None, output: Path) -> Path | None:
    if source is None:
        return None
    source = source.resolve()
    if not source.is_file():
        raise ReleaseError(f"Optional artifact does not exist: {source}")
    destination = output / source.name
    if source != destination:
        shutil.copy2(source, destination)
    return destination


def write_manifest(
    output: Path,
    *,
    version: str,
    head: str,
    commit_timestamp: str,
    source_files: list[Path],
    artifacts: list[Path],
) -> Path:
    with (ROOT / "src" / "codex_armada" / "resources" / "default_config.toml").open("rb") as stream:
        config = tomllib.load(stream)
    forge = config["luna_forge"]
    manifest = {
        "project": "Codex Armada",
        "version": version,
        "source_commit": head,
        "source_commit_timestamp": commit_timestamp,
        "generated_at": commit_timestamp,
        "source_file_count": len(source_files),
        "luna_forge": {
            "repository": forge["repository"],
            "version": forge["required_version"],
            "commit": forge["expected_commit"],
        },
        "artifacts": [
            {
                "name": artifact.name,
                "size_bytes": artifact.stat().st_size,
                "sha256": sha256(artifact),
            }
            for artifact in sorted(artifacts, key=lambda path: path.name)
        ],
    }
    path = output / "RELEASE-MANIFEST.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_checksums(output: Path, artifacts: list[Path]) -> Path:
    path = output / "SHA256SUMS.txt"
    lines = [f"{sha256(item)}  {item.name}" for item in sorted(artifacts, key=lambda candidate: candidate.name)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def verify_archive(archive_path: Path, *, expected_root: str, require_git: bool) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if not names:
            raise ReleaseError(f"Archive is empty: {archive_path}")
        prefix = expected_root + "/"
        if any(not name.startswith(prefix) for name in names):
            raise ReleaseError(f"Archive contains an entry outside {expected_root}: {archive_path}")
        if len(names) != len(set(names)):
            raise ReleaseError(f"Archive contains duplicate entries: {archive_path}")
        has_git = any(name.startswith(prefix + ".git/") for name in names)
        if has_git != require_git:
            raise ReleaseError(f"Unexpected Git metadata state in {archive_path.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, help="Copy an already verified wheel into the release directory")
    parser.add_argument("--test-results", type=Path, help="Copy a verification report into the release directory")
    parser.add_argument("--no-git-ready", action="store_true", help="Skip the portable Git-ready ZIP")
    args = parser.parse_args()

    head, commit_timestamp = require_clean_repository()
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    version = str(project["version"])
    root_name = f"Codex-Armada-{version}"
    source_files = tracked_files()

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for stale in output.iterdir():
        if stale.is_file():
            stale.unlink()
        elif stale.is_dir():
            shutil.rmtree(stale)

    artifacts: list[Path] = []
    source_archive = write_source_archive(output, root_name=root_name, files=source_files)
    verify_archive(source_archive, expected_root=root_name, require_git=False)
    artifacts.append(source_archive)

    if not args.no_git_ready:
        git_archive = write_git_ready_archive(output, root_name=root_name)
        verify_archive(git_archive, expected_root=root_name, require_git=True)
        artifacts.append(git_archive)

    history = write_commit_history(output)
    artifacts.append(history)
    for optional in (copy_optional_artifact(args.wheel, output), copy_optional_artifact(args.test_results, output)):
        if optional is not None:
            artifacts.append(optional)

    manifest = write_manifest(
        output,
        version=version,
        head=head,
        commit_timestamp=commit_timestamp,
        source_files=source_files,
        artifacts=artifacts,
    )
    artifacts.append(manifest)
    checksums = write_checksums(output, artifacts)

    print(json.dumps({
        "version": version,
        "source_commit": head,
        "output_dir": str(output),
        "artifacts": [str(path) for path in artifacts + [checksums]],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
