from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.path.insert(0, str(SRC))

from codex_armada.config import load_config
from codex_armada.luna_forge import LunaForgeManager


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    if command and os.path.basename(command[0]) == os.path.basename(sys.executable) and "-B" not in command:
        command = [*command]
        command.insert(1, "-B")
    child_env = os.environ.copy()
    if env:
        child_env.update(env)
    completed = subprocess.run(command, cwd=cwd, env=child_env, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or completed.stdout.strip())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="codex-armada-upstream-") as temporary:
        root = Path(temporary)
        repo = root / "repo"
        repo.mkdir()
        run(["git", "init", "-q", "-b", "main"], cwd=repo)
        run(["git", "config", "user.name", "Codex Armada Upstream Check"], cwd=repo)
        run(["git", "config", "user.email", "upstream-check@example.invalid"], cwd=repo)
        (repo / "README.md").write_text("# upstream fixture\n", encoding="utf-8")
        run(["git", "add", "README.md"], cwd=repo)
        run(["git", "commit", "-q", "-m", "chore: initialize upstream fixture"], cwd=repo)
        os.environ["CODEX_ARMADA_HOME"] = str(root / "state")
        os.environ["CODEX_ARMADA_CACHE_DIR"] = str(root / "cache")
        config = load_config(repo)
        manager = LunaForgeManager(config)
        _, fetched = manager.fetch_source()
        installed = manager.ensure_project_install(repo)
        verified = manager.require_installed(repo)
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, text=True, capture_output=True, check=True, env=os.environ.copy()
        ).stdout.strip()
        if dirty:
            raise SystemExit(f"Project-local Luna Forge installation made the Git tree dirty: {dirty}")
        payload = {
            "fetched": fetched,
            "installed": installed.status.installed,
            "source_valid": verified.source_valid,
            "repository": verified.repository,
            "commit": verified.resolved_commit,
            "version": verified.source_version,
            "digest": verified.digest,
        }
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
