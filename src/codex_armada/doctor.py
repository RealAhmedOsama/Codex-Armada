from __future__ import annotations

import json
import platform
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .codex import CodexRunner
from .config import AppConfig
from .domain import RiskLevel
from .errors import CapabilityError, LunaForgeError
from .git import GitRepository
from .luna_forge import LunaForgeManager, LunaForgeStatus
from .paths import ProjectPaths
from .process import run_process
from .prompts import PromptBuilder
from .resources import resource_path
from .util import atomic_write_json, digest_object, utc_now


_EFFORT_RANK = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "xhigh": 4,
    "max": 5,
}


@dataclass(slots=True)
class CapabilitySet:
    checked_at: str
    python_version: str
    platform: str
    git_version: str | None
    codex_version: str | None
    flags: dict[str, bool]
    configured_models: dict[str, str]
    available_models: set[str] = field(default_factory=set)
    model_catalog_source: str | None = None
    model_probes: dict[str, dict[str, Any]] = field(default_factory=dict)
    luna_forge: dict[str, Any] = field(default_factory=dict)
    config_digest: str = ""
    repo: str = ""
    repo_head: str | None = None
    repo_branch: str | None = None
    healthy: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def digest(self) -> str:
        return digest_object(
            {
                "python_version": self.python_version,
                "platform": self.platform,
                "git_version": self.git_version,
                "codex_version": self.codex_version,
                "flags": self.flags,
                "configured_models": self.configured_models,
                "available_models": sorted(self.available_models),
                "model_catalog_source": self.model_catalog_source,
                "model_probes": self.model_probes,
                "luna_forge": self.luna_forge.get("status", self.luna_forge),
                "config_digest": self.config_digest,
                "repo": self.repo,
            }
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilitySet":
        return cls(
            checked_at=str(data.get("checked_at", "")),
            python_version=str(data.get("python_version", "")),
            platform=str(data.get("platform", "")),
            git_version=data.get("git_version"),
            codex_version=data.get("codex_version"),
            flags={str(k): bool(v) for k, v in dict(data.get("flags", {})).items()},
            configured_models={str(k): str(v) for k, v in dict(data.get("configured_models", {})).items()},
            available_models=set(str(item) for item in data.get("available_models", [])),
            model_catalog_source=data.get("model_catalog_source"),
            model_probes=dict(data.get("model_probes", {})),
            luna_forge=dict(data.get("luna_forge", {})),
            config_digest=str(data.get("config_digest", "")),
            repo=str(data.get("repo", "")),
            repo_head=data.get("repo_head"),
            repo_branch=data.get("repo_branch"),
            healthy=bool(data.get("healthy", False)),
            warnings=[str(item) for item in data.get("warnings", [])],
            errors=[str(item) for item in data.get("errors", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "python_version": self.python_version,
            "platform": self.platform,
            "git_version": self.git_version,
            "codex_version": self.codex_version,
            "flags": self.flags,
            "configured_models": self.configured_models,
            "available_models": sorted(self.available_models),
            "model_catalog_source": self.model_catalog_source,
            "model_probes": self.model_probes,
            "luna_forge": self.luna_forge,
            "config_digest": self.config_digest,
            "repo": self.repo,
            "repo_head": self.repo_head,
            "repo_branch": self.repo_branch,
            "healthy": self.healthy,
            "warnings": self.warnings,
            "errors": self.errors,
            "digest": self.digest,
        }


class Doctor:
    def __init__(self, config: AppConfig, paths: ProjectPaths) -> None:
        self.config = config
        self.paths = paths
        self.codex = CodexRunner(config)
        self.prompts = PromptBuilder()
        self.luna_forge = LunaForgeManager(config)

    def inspect(
        self,
        *,
        probe_models: bool = False,
        save: bool = True,
        repair_luna_forge: bool | None = None,
    ) -> CapabilitySet:
        errors: list[str] = []
        warnings: list[str] = []
        python_version = platform.python_version()
        if tuple(int(part) for part in python_version.split(".")[:2]) < (3, 11):
            errors.append("Python 3.11 or newer is required")

        git_version: str | None = None
        git_result = run_process(["git", "--version"], timeout=30)
        if git_result.succeeded:
            git_version = git_result.stdout.strip()
        else:
            errors.append("Git executable is unavailable")

        repo_head: str | None = None
        repo_branch: str | None = None
        try:
            git = GitRepository(self.paths.repo)
            repo_head = git.head()
            repo_branch = git.branch()
            if self.config.commit_per_task:
                name = run_process(["git", "config", "user.name"], cwd=git.repo, timeout=30)
                email = run_process(["git", "config", "user.email"], cwd=git.repo, timeout=30)
                if not name.succeeded or not name.stdout.strip() or not email.succeeded or not email.stdout.strip():
                    errors.append("Git user.name and user.email must be configured because commit_per_task is enabled")
        except Exception as exc:
            errors.append(str(exc))

        forge_payload = self._inspect_luna_forge(
            errors=errors,
            warnings=warnings,
            repair=repair_luna_forge,
        )

        codex_version: str | None = None
        flags_dict: dict[str, bool] = {}
        try:
            codex_version = self.codex.version()
            flags = self.codex.flags()
            flags_dict = flags.to_dict()
            if not flags.required_ready:
                errors.append("Codex CLI does not expose every required non-interactive exec flag")
        except Exception as exc:
            errors.append(f"Codex CLI preflight failed: {exc}")

        available_models: set[str] = set()
        model_source: str | None = None
        if codex_version:
            available_models, model_source = self.codex.try_model_catalog()
            if not available_models:
                warnings.append(
                    "Codex did not expose a machine-readable model catalog; configured model IDs will be tried exactly"
                )

        model_probes: dict[str, dict[str, Any]] = {}
        if probe_models and codex_version and not errors:
            model_probes = self._probe_models()
            available_models.update(
                item["model"] for item in model_probes.values() if item.get("succeeded") and item.get("model")
            )
            failed = [key for key, item in model_probes.items() if not item.get("succeeded")]
            if failed:
                errors.append(f"Model probes failed: {', '.join(failed)}")

        capabilities = CapabilitySet(
            checked_at=utc_now(),
            python_version=python_version,
            platform=platform.platform(),
            git_version=git_version,
            codex_version=codex_version,
            flags=flags_dict,
            configured_models=self.config.models.copy(),
            available_models=available_models,
            model_catalog_source=model_source,
            model_probes=model_probes,
            luna_forge=forge_payload,
            config_digest=self.config.digest,
            repo=str(self.paths.repo),
            repo_head=repo_head,
            repo_branch=repo_branch,
            healthy=not errors,
            warnings=warnings,
            errors=errors,
        )
        if save:
            atomic_write_json(self.paths.capabilities_file, capabilities.to_dict())
        return capabilities

    def require_healthy(
        self,
        *,
        probe_models: bool = False,
        repair_luna_forge: bool | None = None,
    ) -> CapabilitySet:
        capabilities = self.inspect(
            probe_models=probe_models,
            repair_luna_forge=repair_luna_forge,
        )
        if not capabilities.healthy:
            raise CapabilityError("Capability doctor failed:\n- " + "\n- ".join(capabilities.errors))
        return capabilities

    def load_cached(self) -> CapabilitySet | None:
        if not self.paths.capabilities_file.is_file():
            return None
        try:
            data = json.loads(self.paths.capabilities_file.read_text(encoding="utf-8"))
            return CapabilitySet.from_dict(data)
        except Exception:
            return None

    def _inspect_luna_forge(
        self,
        *,
        errors: list[str],
        warnings: list[str],
        repair: bool | None,
    ) -> dict[str, Any]:
        if not self.config.luna_forge.enabled:
            status = self.luna_forge.inspect(self.paths.repo)
            return {"status": status.to_dict(), "install": None}

        should_repair = self.config.luna_forge.auto_install if repair is None else repair
        install_payload: dict[str, Any] | None = None
        try:
            if should_repair:
                installation = self.luna_forge.ensure_project_install(self.paths.repo)
                install_payload = installation.to_dict()
                status = installation.status
                if installation.changed:
                    warnings.append(
                        f"Installed pinned Luna Forge {status.source_version} into project-local ignored paths"
                    )
            else:
                status = self.luna_forge.inspect(self.paths.repo)
            if not status.source_valid:
                errors.append("Pinned Luna Forge source failed integrity validation")
            if status.conflict:
                errors.append("Project Luna Forge installation conflicts with the pinned upstream source")
            if not status.installed:
                errors.append(
                    "Luna Forge is not installed exactly; run `codex-armada forge install` or enable [luna_forge].auto_install"
                )
            errors.extend(item for item in status.errors if item not in errors)
            warnings.extend(item for item in status.warnings if item not in warnings and status.installed)
        except LunaForgeError as exc:
            status = self.luna_forge.inspect(self.paths.repo)
            errors.append(f"Luna Forge preflight failed: {exc}")
        return {"status": status.to_dict(), "install": install_payload}

    def _active_model_routes(self) -> list[tuple[str, str, str]]:
        profile = self.config.profile
        pairs: set[tuple[str, str, str]] = set()
        for risk in RiskLevel:
            alias = profile.workers[risk]
            effort = profile.efforts[risk]
            if self.luna_forge.applies_to_alias(alias):
                required = self.config.luna_forge.default_effort
                if _EFFORT_RANK.get(effort, -1) < _EFFORT_RANK.get(required, 3):
                    effort = required
            pairs.add((alias, self.config.model_for_alias(alias), effort))
        pairs.add((self._alias_for_model(self.config.planner_model), self.config.planner_model, self.config.planner_effort))
        pairs.add((self._alias_for_model(self.config.reviewer_model), self.config.reviewer_model, self.config.reviewer_effort))
        return sorted(pairs, key=lambda item: (item[0], item[2], item[1]))

    def _alias_for_model(self, model: str) -> str:
        for alias, configured in self.config.models.items():
            if configured == model:
                return alias
        return model.replace("/", "-")

    def _probe_models(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        with tempfile.TemporaryDirectory(prefix="codex-armada-model-probe-") as temporary:
            repo = Path(temporary)
            initialized = run_process(["git", "init", "-q"], cwd=repo, timeout=30)
            if not initialized.succeeded:
                raise CapabilityError(initialized.stderr.strip() or "Could not initialize model-probe repository")

            forge_baseline: LunaForgeStatus | None = None
            if self.config.luna_forge.enabled:
                forge_baseline = self.luna_forge.ensure_project_install(repo).status

            for alias, model, effort in self._active_model_routes():
                key = f"{alias}:{effort}"
                use_forge = self.luna_forge.applies_to_alias(alias)
                artifact = self.paths.project_root / "model-probes" / alias / effort
                execution = self.codex.run(
                    repo=repo,
                    prompt=self.prompts.model_probe(use_luna_forge=use_forge),
                    model=model,
                    effort=effort,
                    sandbox="read-only",
                    schema_path=resource_path("schemas", "canary.schema.json"),
                    artifact_dir=artifact,
                    label="probe",
                    timeout=min(self.config.command_timeout_seconds, 600),
                    skip_git_repo_check=True,
                )
                forge_error: str | None = None
                if forge_baseline is not None:
                    try:
                        after = self.luna_forge.require_unchanged(
                            repo, forge_baseline, actor=f"model probe {key}"
                        )
                        atomic_write_json(artifact / "luna-forge-after.json", after.to_dict())
                    except LunaForgeError as exc:
                        forge_error = str(exc)
                results[key] = {
                    "alias": alias,
                    "model": model,
                    "effort": effort,
                    "worker_protocol": "luna-forge" if use_forge else "standard",
                    "succeeded": execution.succeeded and not execution.attestation.mismatch and forge_error is None,
                    "return_code": execution.return_code,
                    "attestation": execution.attestation.to_dict(),
                    "luna_forge_error": forge_error,
                }
        return results
