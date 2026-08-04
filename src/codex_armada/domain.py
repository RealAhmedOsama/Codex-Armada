from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .util import utc_now


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.CRITICAL: 3,
        }[self]

    @classmethod
    def highest(cls, *values: "RiskLevel") -> "RiskLevel":
        return max(values, key=lambda value: value.rank)


class TaskKind(StrEnum):
    RECON = "recon"
    DOCUMENTATION = "documentation"
    TEST = "test"
    IMPLEMENTATION = "implementation"
    REFACTOR = "refactor"
    BUGFIX = "bugfix"
    MIGRATION = "migration"
    SECURITY = "security"
    OPERATIONS = "operations"


class RunStatus(StrEnum):
    DRAFT = "draft"
    PLANNING = "planning"
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting-approval"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting-approval"
    RUNNING = "running"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


class ReviewVerdict(StrEnum):
    SHIP = "ship"
    FIX_FIRST = "fix-first"
    RETHINK = "rethink"


class PlanVerdict(StrEnum):
    PROCEED = "proceed"
    CHANGE = "change"
    STOP = "stop"


@dataclass(slots=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, other: "TokenUsage") -> None:
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.output_tokens += other.output_tokens
        self.reasoning_output_tokens += other.reasoning_output_tokens

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TokenUsage":
        data = data or {}
        return cls(
            input_tokens=int(data.get("input_tokens", 0) or 0),
            cached_input_tokens=int(data.get("cached_input_tokens", 0) or 0),
            output_tokens=int(data.get("output_tokens", 0) or 0),
            reasoning_output_tokens=int(data.get("reasoning_output_tokens", 0) or 0),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(slots=True)
class RuntimeAttestation:
    requested_model: str
    requested_effort: str
    requested_sandbox: str
    observed_model: str | None = None
    observed_effort: str | None = None
    observed_sandbox: str | None = None
    permission_profile: str | None = None
    thread_id: str | None = None
    source: str = "requested-only"
    verified: bool = False
    mismatch: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeAttestation":
        return cls(
            requested_model=str(data.get("requested_model", "")),
            requested_effort=str(data.get("requested_effort", "")),
            requested_sandbox=str(data.get("requested_sandbox", "")),
            observed_model=data.get("observed_model"),
            observed_effort=data.get("observed_effort"),
            observed_sandbox=data.get("observed_sandbox"),
            permission_profile=data.get("permission_profile"),
            thread_id=data.get("thread_id"),
            source=str(data.get("source", "requested-only")),
            verified=bool(data.get("verified", False)),
            mismatch=data.get("mismatch"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_model": self.requested_model,
            "requested_effort": self.requested_effort,
            "requested_sandbox": self.requested_sandbox,
            "observed_model": self.observed_model,
            "observed_effort": self.observed_effort,
            "observed_sandbox": self.observed_sandbox,
            "permission_profile": self.permission_profile,
            "thread_id": self.thread_id,
            "source": self.source,
            "verified": self.verified,
            "mismatch": self.mismatch,
        }


@dataclass(slots=True)
class VerificationSpec:
    command: str
    success: str = "exit code 0"
    timeout_seconds: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VerificationSpec":
        return cls(
            command=str(data.get("command", "")).strip(),
            success=str(data.get("success", "exit code 0")).strip(),
            timeout_seconds=int(data["timeout_seconds"]) if data.get("timeout_seconds") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "success": self.success,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(slots=True)
class TaskPlan:
    id: str
    title: str
    objective: str
    kind: TaskKind
    owned_paths: list[str]
    excluded_paths: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    verification: list[VerificationSpec] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    risk: RiskLevel = RiskLevel.MEDIUM
    tags: list[str] = field(default_factory=list)
    allow_deletions: bool = False
    allow_production_changes: bool = False
    commit_message: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskPlan":
        return cls(
            id=str(data.get("id", "")).strip(),
            title=str(data.get("title", "")).strip(),
            objective=str(data.get("objective", "")).strip(),
            kind=TaskKind(str(data.get("kind", TaskKind.IMPLEMENTATION.value))),
            owned_paths=_str_list(data.get("owned_paths")),
            excluded_paths=_str_list(data.get("excluded_paths")),
            interfaces=_str_list(data.get("interfaces")),
            constraints=_str_list(data.get("constraints")),
            verification=[VerificationSpec.from_dict(item) for item in data.get("verification", [])],
            depends_on=_str_list(data.get("depends_on")),
            risk=RiskLevel(str(data.get("risk", RiskLevel.MEDIUM.value))),
            tags=_str_list(data.get("tags")),
            allow_deletions=bool(data.get("allow_deletions", False)),
            allow_production_changes=bool(data.get("allow_production_changes", False)),
            commit_message=str(data["commit_message"]).strip() if data.get("commit_message") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "objective": self.objective,
            "kind": self.kind.value,
            "owned_paths": self.owned_paths,
            "excluded_paths": self.excluded_paths,
            "interfaces": self.interfaces,
            "constraints": self.constraints,
            "verification": [item.to_dict() for item in self.verification],
            "depends_on": self.depends_on,
            "risk": self.risk.value,
            "tags": self.tags,
            "allow_deletions": self.allow_deletions,
            "allow_production_changes": self.allow_production_changes,
            "commit_message": self.commit_message,
        }


@dataclass(slots=True)
class ExecutionPlan:
    goal: str
    summary: str
    assumptions: list[str]
    tasks: list[TaskPlan]
    acceptance_criteria: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionPlan":
        return cls(
            goal=str(data.get("goal", "")).strip(),
            summary=str(data.get("summary", "")).strip(),
            assumptions=_str_list(data.get("assumptions")),
            tasks=[TaskPlan.from_dict(item) for item in data.get("tasks", [])],
            acceptance_criteria=_str_list(data.get("acceptance_criteria")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "summary": self.summary,
            "assumptions": self.assumptions,
            "tasks": [item.to_dict() for item in self.tasks],
            "acceptance_criteria": self.acceptance_criteria,
        }


@dataclass(slots=True)
class RouteDecision:
    worker_alias: str
    worker_model: str
    worker_effort: str
    sandbox: str
    final_review: bool
    plan_review: bool
    approval_required: bool
    estimated_credits: float
    worker_protocol: str = "standard"
    worker_skill: str | None = None
    worker_skill_version: str | None = None
    worker_skill_repository: str | None = None
    worker_skill_ref: str | None = None
    worker_skill_commit: str | None = None
    execution_transport: str = "codex-exec"
    reasons: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RouteDecision":
        return cls(
            worker_alias=str(data.get("worker_alias", "")),
            worker_model=str(data.get("worker_model", "")),
            worker_effort=str(data.get("worker_effort", "medium")),
            sandbox=str(data.get("sandbox", "workspace-write")),
            final_review=bool(data.get("final_review", False)),
            plan_review=bool(data.get("plan_review", False)),
            approval_required=bool(data.get("approval_required", False)),
            estimated_credits=float(data.get("estimated_credits", 0.0)),
            worker_protocol=str(data.get("worker_protocol", "standard")),
            worker_skill=data.get("worker_skill"),
            worker_skill_version=data.get("worker_skill_version"),
            worker_skill_repository=data.get("worker_skill_repository"),
            worker_skill_ref=data.get("worker_skill_ref"),
            worker_skill_commit=data.get("worker_skill_commit"),
            execution_transport=str(data.get("execution_transport", "codex-exec")),
            reasons=_str_list(data.get("reasons")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_alias": self.worker_alias,
            "worker_model": self.worker_model,
            "worker_effort": self.worker_effort,
            "sandbox": self.sandbox,
            "final_review": self.final_review,
            "plan_review": self.plan_review,
            "approval_required": self.approval_required,
            "estimated_credits": self.estimated_credits,
            "worker_protocol": self.worker_protocol,
            "worker_skill": self.worker_skill,
            "worker_skill_version": self.worker_skill_version,
            "worker_skill_repository": self.worker_skill_repository,
            "worker_skill_ref": self.worker_skill_ref,
            "worker_skill_commit": self.worker_skill_commit,
            "execution_transport": self.execution_transport,
            "reasons": self.reasons,
        }


@dataclass(slots=True)
class CommandResult:
    command: str
    exit_code: int
    duration_seconds: float
    passed: bool
    stdout_path: str | None = None
    stderr_path: str | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommandResult":
        return cls(
            command=str(data.get("command", "")),
            exit_code=int(data.get("exit_code", -1)),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            passed=bool(data.get("passed", False)),
            stdout_path=data.get("stdout_path"),
            stderr_path=data.get("stderr_path"),
            error=data.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "duration_seconds": self.duration_seconds,
            "passed": self.passed,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "error": self.error,
        }


@dataclass(slots=True)
class TaskRecord:
    plan: TaskPlan
    route: RouteDecision
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    corrections: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    worktree_path: str | None = None
    source_commit_sha: str | None = None
    applied_commit_sha: str | None = None
    changed_files: list[str] = field(default_factory=list)
    scope_violations: list[str] = field(default_factory=list)
    protected_path_violations: list[str] = field(default_factory=list)
    symlink_violations: list[str] = field(default_factory=list)
    deletions: list[str] = field(default_factory=list)
    worker_result: dict[str, Any] | None = None
    review_result: dict[str, Any] | None = None
    verification_results: list[CommandResult] = field(default_factory=list)
    runtime_attestations: list[RuntimeAttestation] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    credits: float = 0.0
    credits_source: str = "estimated"
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskRecord":
        return cls(
            plan=TaskPlan.from_dict(data["plan"]),
            route=RouteDecision.from_dict(data["route"]),
            status=TaskStatus(str(data.get("status", TaskStatus.PENDING.value))),
            attempts=int(data.get("attempts", 0)),
            corrections=int(data.get("corrections", 0)),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            worktree_path=data.get("worktree_path"),
            source_commit_sha=data.get("source_commit_sha"),
            applied_commit_sha=data.get("applied_commit_sha"),
            changed_files=_str_list(data.get("changed_files")),
            scope_violations=_str_list(data.get("scope_violations")),
            protected_path_violations=_str_list(data.get("protected_path_violations")),
            symlink_violations=_str_list(data.get("symlink_violations")),
            deletions=_str_list(data.get("deletions")),
            worker_result=data.get("worker_result"),
            review_result=data.get("review_result"),
            verification_results=[CommandResult.from_dict(item) for item in data.get("verification_results", [])],
            runtime_attestations=[RuntimeAttestation.from_dict(item) for item in data.get("runtime_attestations", [])],
            usage=TokenUsage.from_dict(data.get("usage")),
            credits=float(data.get("credits", 0.0)),
            credits_source=str(data.get("credits_source", "estimated")),
            error=data.get("error"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "route": self.route.to_dict(),
            "status": self.status.value,
            "attempts": self.attempts,
            "corrections": self.corrections,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "worktree_path": self.worktree_path,
            "source_commit_sha": self.source_commit_sha,
            "applied_commit_sha": self.applied_commit_sha,
            "changed_files": self.changed_files,
            "scope_violations": self.scope_violations,
            "protected_path_violations": self.protected_path_violations,
            "symlink_violations": self.symlink_violations,
            "deletions": self.deletions,
            "worker_result": self.worker_result,
            "review_result": self.review_result,
            "verification_results": [item.to_dict() for item in self.verification_results],
            "runtime_attestations": [item.to_dict() for item in self.runtime_attestations],
            "usage": self.usage.to_dict(),
            "credits": self.credits,
            "credits_source": self.credits_source,
            "error": self.error,
        }


@dataclass(slots=True)
class RunRecord:
    run_id: str
    goal: str
    repo: str
    profile: str
    status: RunStatus = RunStatus.DRAFT
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    base_commit: str | None = None
    current_commit: str | None = None
    branch: str | None = None
    config_digest: str | None = None
    capability_digest: str | None = None
    plan: ExecutionPlan | None = None
    tasks: list[TaskRecord] = field(default_factory=list)
    budget_credits: float | None = None
    commit_enabled: bool = True
    estimated_credits: float = 0.0
    actual_credits: float = 0.0
    usage: TokenUsage = field(default_factory=TokenUsage)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        return cls(
            run_id=str(data["run_id"]),
            goal=str(data.get("goal", "")),
            repo=str(data.get("repo", "")),
            profile=str(data.get("profile", "balanced")),
            status=RunStatus(str(data.get("status", RunStatus.DRAFT.value))),
            created_at=str(data.get("created_at", utc_now())),
            updated_at=str(data.get("updated_at", utc_now())),
            base_commit=data.get("base_commit"),
            current_commit=data.get("current_commit"),
            branch=data.get("branch"),
            config_digest=data.get("config_digest"),
            capability_digest=data.get("capability_digest"),
            plan=ExecutionPlan.from_dict(data["plan"]) if data.get("plan") else None,
            tasks=[TaskRecord.from_dict(item) for item in data.get("tasks", [])],
            budget_credits=float(data["budget_credits"]) if data.get("budget_credits") is not None else None,
            commit_enabled=bool(data.get("commit_enabled", True)),
            estimated_credits=float(data.get("estimated_credits", 0.0)),
            actual_credits=float(data.get("actual_credits", 0.0)),
            usage=TokenUsage.from_dict(data.get("usage")),
            notes=_str_list(data.get("notes")),
            error=data.get("error"),
        )

    def touch(self) -> None:
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "repo": self.repo,
            "profile": self.profile,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "base_commit": self.base_commit,
            "current_commit": self.current_commit,
            "branch": self.branch,
            "config_digest": self.config_digest,
            "capability_digest": self.capability_digest,
            "plan": self.plan.to_dict() if self.plan else None,
            "tasks": [item.to_dict() for item in self.tasks],
            "budget_credits": self.budget_credits,
            "commit_enabled": self.commit_enabled,
            "estimated_credits": self.estimated_credits,
            "actual_credits": self.actual_credits,
            "usage": self.usage.to_dict(),
            "notes": self.notes,
            "error": self.error,
        }


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]
