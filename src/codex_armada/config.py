from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .domain import RiskLevel
from .errors import ConfigurationError
from .util import digest_object, unique

SUPPORTED_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}


@dataclass(slots=True)
class ProfileConfig:
    name: str
    workers: dict[RiskLevel, str]
    efforts: dict[RiskLevel, str]
    final_review_from: RiskLevel
    plan_review_from: RiskLevel
    approval_from: RiskLevel


@dataclass(slots=True)
class CreditRate:
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float
    typical_task_credits: float


@dataclass(slots=True)
class RiskRule:
    pattern: str
    risk: RiskLevel
    reason: str


@dataclass(slots=True)
class LunaForgeConfig:
    enabled: bool
    repository: str
    ref: str
    expected_commit: str
    required_version: str
    auto_fetch: bool
    auto_install: bool
    install_scope: str
    strict_integrity: bool
    allow_non_github_source: bool
    cache_dir: str | None
    skill_name: str
    agent_name: str
    default_effort: str
    invoke_for_aliases: list[str]


@dataclass(slots=True)
class AppConfig:
    profile_name: str
    language: str
    report_language: str
    codex_binary: str
    commit_per_task: bool
    use_isolated_worktrees: bool
    require_clean_tree: bool
    keep_failed_worktrees: bool
    store_prompts: bool
    ignore_user_config: bool
    max_corrections: int
    command_timeout_seconds: int
    verification_timeout_seconds: int
    attestation_required_from: RiskLevel
    default_budget_credits: float | None
    planner_model: str
    planner_effort: str
    reviewer_model: str
    reviewer_effort: str
    models: dict[str, str]
    profiles: dict[str, ProfileConfig]
    credit_rates: dict[str, CreditRate]
    luna_forge: LunaForgeConfig
    protected_paths: list[str] = field(default_factory=list)
    production_paths: list[str] = field(default_factory=list)
    allowed_verification_tools: list[str] = field(default_factory=list)
    risk_rules: list[RiskRule] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def profile(self) -> ProfileConfig:
        try:
            return self.profiles[self.profile_name]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown profile: {self.profile_name}") from exc

    @property
    def digest(self) -> str:
        return digest_object(self.raw)

    def model_for_alias(self, alias: str) -> str:
        try:
            return self.models[alias]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown model alias `{alias}`") from exc


def package_root() -> Path:
    return Path(__file__).resolve().parent


def default_config_path() -> Path:
    return package_root() / "resources" / "default_config.toml"


def default_config_text() -> str:
    return default_config_path().read_text(encoding="utf-8")


def load_config(
    repo: Path,
    *,
    profile: str | None = None,
    config_path: Path | None = None,
    codex_binary: str | None = None,
) -> AppConfig:
    base = _read_toml(default_config_path())
    project_path = repo / ".codex-armada.toml"
    if project_path.is_file():
        base = _merge(base, _read_toml(project_path))
    if config_path:
        if not config_path.is_file():
            raise ConfigurationError(f"Configuration file not found: {config_path}")
        base = _merge(base, _read_toml(config_path))
    if profile:
        base["profile"] = profile
    environment_binary = os.environ.get("CODEX_ARMADA_CODEX_BINARY")
    if codex_binary or environment_binary:
        base["codex_binary"] = codex_binary or environment_binary
    return _parse_config(base)


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Invalid TOML in {path}: {exc}") from exc


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    additive_lists = {"risk_rules", "protected_paths", "production_paths"}
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        elif key in additive_lists and isinstance(result.get(key), list) and isinstance(value, list):
            if key == "risk_rules":
                result[key] = [*result[key], *copy.deepcopy(value)]
            else:
                result[key] = unique([str(item) for item in [*result[key], *value]])
        else:
            result[key] = copy.deepcopy(value)
    return result


def _parse_config(data: dict[str, Any]) -> AppConfig:
    try:
        config_version = int(data.get("version", 0))
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("Configuration `version` must be an integer") from exc
    if config_version != 1:
        raise ConfigurationError(f"Unsupported configuration version `{config_version}`; expected `1`")

    profile_name = str(data.get("profile", "balanced"))
    models = {str(key): str(value) for key, value in dict(data.get("models", {})).items()}
    if not {"luna", "terra", "sol"}.issubset(models):
        raise ConfigurationError("[models] must define luna, terra, and sol")

    profiles: dict[str, ProfileConfig] = {}
    for name, raw_profile in dict(data.get("profiles", {})).items():
        workers: dict[RiskLevel, str] = {}
        efforts: dict[RiskLevel, str] = {}
        for risk in RiskLevel:
            worker = str(raw_profile.get(f"{risk.value}_worker", "terra"))
            effort = str(raw_profile.get(f"{risk.value}_effort", "high"))
            if worker not in models:
                raise ConfigurationError(f"Profile `{name}` references unknown worker alias `{worker}`")
            if effort not in SUPPORTED_EFFORTS:
                raise ConfigurationError(f"Profile `{name}` uses unsupported effort `{effort}`")
            workers[risk] = worker
            efforts[risk] = effort
        profiles[str(name)] = ProfileConfig(
            name=str(name),
            workers=workers,
            efforts=efforts,
            final_review_from=RiskLevel(str(raw_profile.get("final_review_from", "high"))),
            plan_review_from=RiskLevel(str(raw_profile.get("plan_review_from", "critical"))),
            approval_from=RiskLevel(str(raw_profile.get("approval_from", "critical"))),
        )
    if profile_name not in profiles:
        raise ConfigurationError(f"Profile `{profile_name}` is not defined")

    rates: dict[str, CreditRate] = {}
    for model, raw_rate in dict(data.get("credit_rates", {})).items():
        rate = CreditRate(
            input_per_million=float(raw_rate.get("input_per_million", 0.0)),
            cached_input_per_million=float(raw_rate.get("cached_input_per_million", 0.0)),
            output_per_million=float(raw_rate.get("output_per_million", 0.0)),
            typical_task_credits=float(raw_rate.get("typical_task_credits", 0.0)),
        )
        if min(
            rate.input_per_million,
            rate.cached_input_per_million,
            rate.output_per_million,
            rate.typical_task_credits,
        ) < 0:
            raise ConfigurationError(f"Credit rates must be non-negative for model `{model}`")
        rates[str(model)] = rate

    active_models = set(models.values()) | {
        str(data.get("planner_model", models["sol"])),
        str(data.get("reviewer_model", models["sol"])),
    }
    missing_rates = sorted(active_models - set(rates))
    if missing_rates:
        raise ConfigurationError(f"[credit_rates] is missing active models: {missing_rates}")

    rules = [
        RiskRule(
            pattern=str(item.get("pattern", "")).strip(),
            risk=RiskLevel(str(item.get("risk", "medium"))),
            reason=str(item.get("reason", "Configured risk rule")).strip(),
        )
        for item in data.get("risk_rules", [])
        if str(item.get("pattern", "")).strip()
    ]

    raw_forge = dict(data.get("luna_forge", {}))
    install_scope = str(raw_forge.get("install_scope", "project")).strip().lower()
    if install_scope != "project":
        raise ConfigurationError("[luna_forge].install_scope currently supports only `project`")
    invoke_for_aliases = [
        str(item).strip() for item in raw_forge.get("invoke_for_aliases", ["luna"]) if str(item).strip()
    ]
    unknown_aliases = sorted(set(invoke_for_aliases) - set(models))
    if unknown_aliases:
        raise ConfigurationError(f"[luna_forge].invoke_for_aliases contains unknown aliases: {unknown_aliases}")
    default_effort = str(raw_forge.get("default_effort", "high")).strip() or "high"
    if default_effort not in SUPPORTED_EFFORTS:
        raise ConfigurationError(f"[luna_forge].default_effort is unsupported: {default_effort}")
    repository = str(raw_forge.get("repository", "")).strip()
    ref = str(raw_forge.get("ref", "")).strip()
    expected_commit = str(raw_forge.get("expected_commit", "")).strip().lower()
    required_version = str(raw_forge.get("required_version", "")).strip()
    if bool(raw_forge.get("enabled", True)):
        if not repository or not ref or not expected_commit or not required_version:
            raise ConfigurationError(
                "Enabled [luna_forge] requires repository, ref, expected_commit, and required_version"
            )
        if len(expected_commit) != 40 or any(ch not in "0123456789abcdef" for ch in expected_commit):
            raise ConfigurationError("[luna_forge].expected_commit must be a full lowercase 40-character SHA")
        if len(ref) != 40 or any(ch not in "0123456789abcdef" for ch in ref.lower()):
            raise ConfigurationError("[luna_forge].ref must be a full 40-character commit SHA")
        if ref.lower() != expected_commit:
            raise ConfigurationError("[luna_forge].ref and expected_commit must identify the same exact commit")
        if models["luna"] != "gpt-5.6-luna":
            raise ConfigurationError("Luna Forge requires [models].luna = `gpt-5.6-luna`")
        if set(invoke_for_aliases) - {"luna"}:
            raise ConfigurationError("Luna Forge can only be attached to the `luna` model alias")

    luna_forge = LunaForgeConfig(
        enabled=bool(raw_forge.get("enabled", True)),
        repository=repository,
        ref=ref,
        expected_commit=expected_commit,
        required_version=required_version,
        auto_fetch=bool(raw_forge.get("auto_fetch", True)),
        auto_install=bool(raw_forge.get("auto_install", True)),
        install_scope=install_scope,
        strict_integrity=bool(raw_forge.get("strict_integrity", True)),
        allow_non_github_source=bool(raw_forge.get("allow_non_github_source", False)),
        cache_dir=str(raw_forge.get("cache_dir", "")).strip() or None,
        skill_name=str(raw_forge.get("skill_name", "luna-forge")).strip() or "luna-forge",
        agent_name=str(raw_forge.get("agent_name", "luna_worker")).strip() or "luna_worker",
        default_effort=default_effort,
        invoke_for_aliases=invoke_for_aliases,
    )

    planner_effort = str(data.get("planner_effort", "high"))
    reviewer_effort = str(data.get("reviewer_effort", "high"))
    if planner_effort not in SUPPORTED_EFFORTS or reviewer_effort not in SUPPORTED_EFFORTS:
        raise ConfigurationError("Planner and reviewer efforts must use a supported reasoning value")

    budget = data.get("default_budget_credits")
    if budget is not None and float(budget) < 0:
        raise ConfigurationError("default_budget_credits must be non-negative or omitted")
    allowed_tools = [str(item).strip() for item in data.get("allowed_verification_tools", []) if str(item).strip()]
    if not allowed_tools:
        raise ConfigurationError("allowed_verification_tools must contain at least one executable")
    return AppConfig(
        profile_name=profile_name,
        language=str(data.get("language", "en")),
        report_language=str(data.get("report_language", "en")),
        codex_binary=str(data.get("codex_binary", "codex")),
        commit_per_task=bool(data.get("commit_per_task", True)),
        use_isolated_worktrees=bool(data.get("use_isolated_worktrees", True)),
        require_clean_tree=bool(data.get("require_clean_tree", True)),
        keep_failed_worktrees=bool(data.get("keep_failed_worktrees", True)),
        store_prompts=bool(data.get("store_prompts", False)),
        ignore_user_config=bool(data.get("ignore_user_config", False)),
        max_corrections=max(0, int(data.get("max_corrections", 1))),
        command_timeout_seconds=max(30, int(data.get("command_timeout_seconds", 3600))),
        verification_timeout_seconds=max(30, int(data.get("verification_timeout_seconds", 1800))),
        attestation_required_from=RiskLevel(str(data.get("attestation_required_from", "critical"))),
        default_budget_credits=float(budget) if budget is not None else None,
        planner_model=str(data.get("planner_model", models["sol"])),
        planner_effort=planner_effort,
        reviewer_model=str(data.get("reviewer_model", models["sol"])),
        reviewer_effort=reviewer_effort,
        models=models,
        profiles=profiles,
        credit_rates=rates,
        luna_forge=luna_forge,
        protected_paths=[str(item) for item in data.get("protected_paths", [])],
        production_paths=[str(item) for item in data.get("production_paths", [])],
        allowed_verification_tools=allowed_tools,
        risk_rules=rules,
        raw=data,
    )
