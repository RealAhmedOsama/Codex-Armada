from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run(command: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=check, capture_output=True, text=True, encoding="utf-8")


def initialize_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for command in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.name", "Test User"],
        ["git", "config", "user.email", "test@example.com"],
    ):
        result = run(command, cwd=path, check=False)
        if result.returncode != 0 and command[:2] == ["git", "init"]:
            run(["git", "init", "-q"], cwd=path)
        elif result.returncode != 0:
            raise RuntimeError(result.stderr)
    (path / "README.md").write_text("# Fixture\n", encoding="utf-8")
    run(["git", "add", "README.md"], cwd=path)
    run(["git", "commit", "-q", "-m", "chore: initialize fixture"], cwd=path)


def create_fake_luna_forge(
    path: Path,
    *,
    version: str = "2.2.1",
    additional_files: dict[str, str] | None = None,
) -> tuple[Path, str]:
    """Create a clean, commit-pinned Luna Forge-compatible upstream fixture."""

    root = path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    skill = root / "skill" / "luna-forge"
    agent = root / "codex" / "agents"
    scripts = root / "scripts"
    skill.mkdir(parents=True)
    agent.mkdir(parents=True)
    scripts.mkdir(parents=True)

    (skill / "SKILL.md").write_text(
        "---\nname: luna-forge\ndescription: Test bounded Luna execution skill.\n---\n\n# Luna Forge Fixture\n",
        encoding="utf-8",
    )
    (agent / "luna-worker.toml").write_text(
        'name = "luna_worker"\n'
        'description = "Test Luna worker."\n'
        'model = "gpt-5.6-luna"\n'
        'model_reasoning_effort = "high"\n'
        'sandbox_mode = "workspace-write"\n'
        'developer_instructions = "Bounded fixture worker."\n',
        encoding="utf-8",
    )
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    (root / "LICENSE").write_text("MIT fixture\n", encoding="utf-8")
    (root / "README.md").write_text("# Luna Forge Fixture\n", encoding="utf-8")

    (scripts / "validate.py").write_text(
        """#!/usr/bin/env python3
from pathlib import Path
import sys
root = Path(__file__).resolve().parents[1]
required = [root/'VERSION', root/'MANIFEST.sha256', root/'skill/luna-forge/SKILL.md', root/'codex/agents/luna-worker.toml']
missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
if missing:
    print('missing: ' + ', '.join(missing), file=sys.stderr)
    raise SystemExit(1)
print('VALIDATION PASSED')
""",
        encoding="utf-8",
    )
    (scripts / "install.py").write_text(
        """#!/usr/bin/env python3
from __future__ import annotations
import argparse
import filecmp
import hashlib
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skill/luna-forge'
AGENT = ROOT / 'codex/agents/luna-worker.toml'

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def same_tree(left: Path, right: Path) -> bool:
    if not left.is_dir() or not right.is_dir():
        return False
    comp = filecmp.dircmp(left, right)
    if comp.left_only or comp.right_only or comp.funny_files:
        return False
    if any(not filecmp.cmp(left/name, right/name, shallow=False) for name in comp.common_files):
        return False
    return all(same_tree(left/name, right/name) for name in comp.common_dirs)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', choices=['project'], required=True)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    project = args.project_root.resolve()
    skill_dest = project / '.agents/skills/luna-forge'
    agent_dest = project / '.codex/agents/luna-worker.toml'
    backup = project / '.luna-forge-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    changed = False
    for source, dest, label in ((SKILL, skill_dest, 'skill'), (AGENT, agent_dest, 'agent')):
        identical = same_tree(source, dest) if source.is_dir() else (dest.is_file() and sha(source) == sha(dest))
        if identical:
            print(f'NO-OP identical {label}: {dest}')
            continue
        if dest.exists() or dest.is_symlink():
            if not args.force:
                print(f'ERROR: different {label} exists at {dest}', file=sys.stderr)
                return 2
            target = backup / label
            print(f'BACKUP {dest} -> {target}')
            if not args.dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                if dest.is_dir() and not dest.is_symlink():
                    shutil.copytree(dest, target)
                    shutil.rmtree(dest)
                else:
                    shutil.copy2(dest, target)
                    dest.unlink()
            print(f'REPLACE {label} {dest}')
        else:
            print(f'INSTALL {label} {dest}')
        changed = True
        if not args.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, dest)
            else:
                shutil.copy2(source, dest)
    print('Installation completed.' if not args.dry_run else 'Installation plan completed.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
""",
        encoding="utf-8",
    )

    if additional_files:
        for relative, content in additional_files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    _write_manifest(root, additional_files=additional_files)
    for command in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.name", "Luna Forge Fixture"],
        ["git", "config", "user.email", "fixture@example.com"],
    ):
        result = run(command, cwd=root, check=False)
        if result.returncode != 0 and command[:2] == ["git", "init"]:
            run(["git", "init", "-q"], cwd=root)
        elif result.returncode != 0:
            raise RuntimeError(result.stderr)
    run(["git", "add", "."], cwd=root)
    run(["git", "commit", "-q", "-m", "release: fake Luna Forge"], cwd=root)
    commit = run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip().lower()
    return root, commit


def write_test_config(path: Path, *, repository: Path, commit: str, cache_dir: Path, version: str = "2.2.1") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "version = 1",
                "",
                "[luna_forge]",
                f"repository = {json.dumps(str(repository.resolve()))}",
                f"ref = {json.dumps(commit)}",
                f"expected_commit = {json.dumps(commit)}",
                f"required_version = {json.dumps(version)}",
                "auto_fetch = true",
                "auto_install = true",
                'install_scope = "project"',
                "strict_integrity = true",
                "allow_non_github_source = true",
                f"cache_dir = {json.dumps(str(cache_dir.resolve()))}",
                'skill_name = "luna-forge"',
                'agent_name = "luna_worker"',
                'default_effort = "high"',
                'invoke_for_aliases = ["luna"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def configure_repo_for_fake_forge(repo: Path, *, repository: Path, commit: str, cache_dir: Path) -> Path:
    overlay = write_test_config(
        repo / ".codex-armada.toml",
        repository=repository,
        commit=commit,
        cache_dir=cache_dir,
    )
    exclude = run(["git", "rev-parse", "--git-path", "info/exclude"], cwd=repo).stdout.strip()
    exclude_path = Path(exclude)
    if not exclude_path.is_absolute():
        exclude_path = (repo / exclude_path).resolve()
    with exclude_path.open("a", encoding="utf-8") as stream:
        stream.write("\n# Codex Armada test overlay\n.codex-armada.toml\n")
    return overlay


def test_environment(project_root: Path, state_root: Path, cache_root: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    env["CODEX_ARMADA_HOME"] = str(state_root)
    env["CODEX_HOME"] = str(state_root / "codex-home")
    if cache_root is not None:
        env["CODEX_ARMADA_CACHE_DIR"] = str(cache_root)
    env["CODEX_ARMADA_CODEX_BINARY"] = f"{sys.executable} {project_root / 'tests' / 'fake_codex.py'}"
    return env


def _write_manifest(root: Path, *, additional_files: dict[str, str] | None = None) -> None:
    lines: list[str] = []
    excluded = {path.strip("/") for path in (additional_files or {}).keys()}
    for file in sorted(path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts):
        relative = file.relative_to(root).as_posix()
        if relative in excluded or relative == "MANIFEST.sha256":
            continue
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}")
    (root / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_cli(project_root: Path, env: dict[str, str], *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", "-m", "codex_armada", *args],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
