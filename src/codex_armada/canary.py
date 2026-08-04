from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .codex import CodexRunner
from .config import AppConfig
from .costs import CostCalculator
from .errors import LunaForgeError
from .luna_forge import LunaForgeManager
from .paths import ProjectPaths
from .process import run_process
from .prompts import PromptBuilder
from .resources import resource_path
from .util import atomic_write_json, compact_timestamp


_EFFORT_RANK = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "xhigh": 4,
    "max": 5,
}


class CanaryRunner:
    def __init__(self, config: AppConfig, paths: ProjectPaths) -> None:
        self.config = config
        self.paths = paths
        self.codex = CodexRunner(config)
        self.costs = CostCalculator(config)
        self.prompts = PromptBuilder()
        self.luna_forge = LunaForgeManager(config)

    def run(self, *, model_alias: str = "luna", effort: str = "medium", keep: bool = False) -> dict[str, object]:
        model = self.config.model_for_alias(model_alias)
        requested_effort = effort
        use_forge = self.luna_forge.applies_to_alias(model_alias)
        if use_forge and _EFFORT_RANK.get(effort, -1) < _EFFORT_RANK.get(
            self.config.luna_forge.default_effort, 3
        ):
            effort = self.config.luna_forge.default_effort

        temporary = Path(tempfile.mkdtemp(prefix="codex-armada-canary-"))
        artifact = self.paths.project_root / "canaries" / compact_timestamp()
        try:
            _initialize_repo(temporary)
            forge_baseline = None
            forge_install = None
            if use_forge:
                forge_install = self.luna_forge.ensure_project_install(temporary)
                forge_baseline = forge_install.status
                atomic_write_json(artifact / "luna-forge-install.json", forge_install.to_dict())

            execution = self.codex.run(
                repo=temporary,
                prompt=self.prompts.canary(use_luna_forge=use_forge),
                model=model,
                effort=effort,
                sandbox="workspace-write",
                schema_path=resource_path("schemas", "canary.schema.json"),
                artifact_dir=artifact,
                label="canary",
            )
            forge_error: str | None = None
            forge_status: dict[str, object] | None = None
            if forge_baseline is not None:
                try:
                    current = self.luna_forge.require_unchanged(
                        temporary, forge_baseline, actor="Luna Forge canary"
                    )
                    forge_status = current.to_dict()
                    atomic_write_json(artifact / "luna-forge-after.json", forge_status)
                except LunaForgeError as exc:
                    forge_error = str(exc)

            expected = "Codex Armada canary OK\n"
            target = temporary / "canary.txt"
            changed = _changed_files(temporary)
            succeeded = (
                execution.succeeded
                and not execution.attestation.mismatch
                and forge_error is None
                and target.is_file()
                and target.read_text(encoding="utf-8") == expected
                and changed == ["canary.txt"]
                and (execution.final_response or {}).get("status") == "ok"
            )
            calculation = self.costs.calculate(model, execution.usage)
            result: dict[str, object] = {
                "succeeded": succeeded,
                "model_alias": model_alias,
                "model": model,
                "requested_effort": requested_effort,
                "effort": effort,
                "worker_protocol": "luna-forge" if use_forge else "standard",
                "worker_skill": self.config.luna_forge.skill_name if use_forge else None,
                "worker_skill_version": self.config.luna_forge.required_version if use_forge else None,
                "changed_files": changed,
                "content_valid": target.is_file() and target.read_text(encoding="utf-8") == expected,
                "return_code": execution.return_code,
                "attestation": execution.attestation.to_dict(),
                "usage": execution.usage.to_dict(),
                "credits": calculation.credits,
                "credits_source": calculation.source,
                "luna_forge": forge_status,
                "luna_forge_error": forge_error,
                "artifact_dir": str(artifact),
                "temporary_repo": str(temporary) if keep else None,
            }
            atomic_write_json(artifact / "canary-result.json", result)
            return result
        finally:
            if not keep:
                shutil.rmtree(temporary, ignore_errors=True)


def _initialize_repo(path: Path) -> None:
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.name", "Codex Armada Canary"],
        ["git", "config", "user.email", "canary@localhost"],
    ]
    for command in commands:
        result = run_process(command, cwd=path, timeout=30)
        if not result.succeeded:
            raise RuntimeError(result.stderr.strip() or f"Failed: {' '.join(command)}")
    (path / "README.md").write_text("# Canary\n", encoding="utf-8")
    add = run_process(["git", "add", "README.md"], cwd=path, timeout=30)
    commit = run_process(["git", "commit", "-q", "-m", "chore: initialize canary"], cwd=path, timeout=30)
    if not add.succeeded or not commit.succeeded:
        raise RuntimeError((add.stderr or commit.stderr).strip() or "Could not initialize canary commit")


def _changed_files(path: Path) -> list[str]:
    result = run_process(["git", "status", "--porcelain=v1"], cwd=path, timeout=30)
    if not result.succeeded:
        return []
    return sorted(line[3:].replace("\\", "/") for line in result.stdout.splitlines() if len(line) >= 4)
