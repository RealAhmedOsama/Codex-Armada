from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .budget import BudgetGovernor
from .codex import CodexExecution, CodexRunner
from .config import AppConfig
from .costs import CostCalculator
from .doctor import CapabilitySet
from .domain import (
    ExecutionPlan,
    PlanVerdict,
    RunRecord,
    RunStatus,
    TaskRecord,
)
from .errors import PlanningError
from .git import GitRepository
from .luna_forge import LunaForgeManager, LunaForgeStatus
from .prompts import PromptBuilder
from .resources import resource_path
from .routing import Router
from .state import StateStore
from .util import atomic_write_json
from .validation import PlanValidator


class Planner:
    def __init__(
        self,
        *,
        config: AppConfig,
        capabilities: CapabilitySet,
        state: StateStore,
    ) -> None:
        self.config = config
        self.capabilities = capabilities
        self.state = state
        self.codex = CodexRunner(config)
        self.costs = CostCalculator(config)
        self.prompts = PromptBuilder()
        self.validator = PlanValidator(config)
        self.router = Router(config)
        self.luna_forge = LunaForgeManager(config)

    def create(
        self,
        *,
        goal: str,
        repo: Path,
        budget_credits: float | None = None,
        plan_file: Path | None = None,
    ) -> RunRecord:
        git = GitRepository(repo)
        self._prepare_luna_forge(git.repo)
        if self.config.require_clean_tree:
            git.require_clean()
        budget = budget_credits if budget_credits is not None else self.config.default_budget_credits
        record = RunRecord(
            run_id=self.state.create_run_id(goal),
            goal=goal,
            repo=str(git.repo),
            profile=self.config.profile_name,
            status=RunStatus.PLANNING,
            base_commit=git.head(),
            current_commit=git.head(),
            branch=git.branch(),
            config_digest=self.config.digest,
            capability_digest=self.capabilities.digest,
            budget_credits=budget,
            commit_enabled=self.config.commit_per_task,
        )
        self.state.save(record)
        governor = BudgetGovernor(budget)
        try:
            if plan_file:
                plan = self._load_plan_file(plan_file)
            else:
                plan = self._generate_plan(record, git, governor, feedback=None, label="planner-01")
            self.validator.require_valid(plan)
            routes = [self.router.route(task) for task in plan.tasks]
            if any(route.plan_review for route in routes):
                verdict, findings = self._review_plan(record, plan, git, governor, label="plan-review-01")
                if verdict == PlanVerdict.CHANGE:
                    plan = self._generate_plan(record, git, governor, feedback=findings, label="planner-02")
                    self.validator.require_valid(plan)
                    routes = [self.router.route(task) for task in plan.tasks]
                    verdict, findings = self._review_plan(record, plan, git, governor, label="plan-review-02")
                if verdict == PlanVerdict.STOP:
                    raise PlanningError("Fresh plan reviewer stopped the plan: " + " | ".join(findings))
                if verdict != PlanVerdict.PROCEED:
                    raise PlanningError("Plan still requires changes after one correction: " + " | ".join(findings))

            record.plan = plan
            record.tasks = [TaskRecord(plan=task, route=route) for task, route in zip(plan.tasks, routes, strict=True)]
            record.estimated_credits = round(
                record.actual_credits + sum(route.estimated_credits for route in routes), 6
            )
            record.status = RunStatus.PLANNED
            self.state.save(record)
            atomic_write_json(self.state.artifact_dir(record.run_id) / "plan.json", plan.to_dict())
            return record
        except Exception as exc:
            record.status = RunStatus.FAILED
            record.error = str(exc)
            self.state.save(record)
            raise

    def _generate_plan(
        self,
        record: RunRecord,
        git: GitRepository,
        governor: BudgetGovernor,
        *,
        feedback: list[str] | None,
        label: str,
    ) -> ExecutionPlan:
        governor.ensure_capacity(
            actual=record.actual_credits,
            expected_next=self.costs.typical(self.config.planner_model),
            label=label,
        )
        before = git.snapshot()
        artifact = self.state.artifact_dir(record.run_id, "planning", label)
        forge_before = self._prepare_luna_forge(git.repo)
        if forge_before is not None:
            atomic_write_json(artifact / "luna-forge-before.json", forge_before.to_dict())
        execution = self.codex.run(
            repo=git.repo,
            prompt=self.prompts.planner(
                goal=record.goal,
                repository=git.repo,
                profile=record.profile,
                feedback=feedback,
            ),
            model=self.config.planner_model,
            effort=self.config.planner_effort,
            sandbox="read-only",
            schema_path=resource_path("schemas", "plan.schema.json"),
            artifact_dir=artifact,
            label=label,
        )
        after = git.snapshot()
        if before != after:
            raise PlanningError("Read-only planner changed repository state")
        if forge_before is not None:
            try:
                forge_after = self.luna_forge.require_unchanged(
                    git.repo, forge_before, actor=f"read-only planner {label}"
                )
                atomic_write_json(artifact / "luna-forge-after.json", forge_after.to_dict())
            except Exception as exc:
                raise PlanningError(f"Read-only planner changed the pinned Luna Forge runtime: {exc}") from exc
        self._record_execution(record, execution, self.config.planner_model, artifact / "cost.json")
        if not execution.succeeded:
            detail = execution.stderr_path.read_text(encoding="utf-8", errors="replace")[-3000:]
            raise PlanningError(f"Planner failed or returned invalid structured output: {detail}")
        if execution.attestation.mismatch:
            raise PlanningError(f"Planner runtime mismatch: {execution.attestation.mismatch}")
        try:
            return ExecutionPlan.from_dict(execution.final_response or {})
        except (KeyError, TypeError, ValueError) as exc:
            raise PlanningError(f"Planner output cannot be parsed: {exc}") from exc

    def _review_plan(
        self,
        record: RunRecord,
        plan: ExecutionPlan,
        git: GitRepository,
        governor: BudgetGovernor,
        *,
        label: str,
    ) -> tuple[PlanVerdict, list[str]]:
        governor.ensure_capacity(
            actual=record.actual_credits,
            expected_next=self.costs.typical(self.config.reviewer_model),
            label=label,
        )
        before = git.snapshot()
        artifact = self.state.artifact_dir(record.run_id, "planning", label)
        forge_before = self._prepare_luna_forge(git.repo)
        if forge_before is not None:
            atomic_write_json(artifact / "luna-forge-before.json", forge_before.to_dict())
        execution = self.codex.run(
            repo=git.repo,
            prompt=self.prompts.plan_reviewer(goal=record.goal, plan=plan),
            model=self.config.reviewer_model,
            effort=self.config.reviewer_effort,
            sandbox="read-only",
            schema_path=resource_path("schemas", "plan-review.schema.json"),
            artifact_dir=artifact,
            label=label,
        )
        after = git.snapshot()
        if before != after:
            raise PlanningError("Read-only plan reviewer changed repository state")
        if forge_before is not None:
            try:
                forge_after = self.luna_forge.require_unchanged(
                    git.repo, forge_before, actor=f"read-only plan reviewer {label}"
                )
                atomic_write_json(artifact / "luna-forge-after.json", forge_after.to_dict())
            except Exception as exc:
                raise PlanningError(f"Read-only plan reviewer changed the pinned Luna Forge runtime: {exc}") from exc
        self._record_execution(record, execution, self.config.reviewer_model, artifact / "cost.json")
        if not execution.succeeded:
            raise PlanningError("Plan reviewer failed or returned invalid structured output")
        if execution.attestation.mismatch:
            raise PlanningError(f"Plan reviewer runtime mismatch: {execution.attestation.mismatch}")
        response = execution.final_response or {}
        try:
            verdict = PlanVerdict(str(response.get("verdict")))
        except ValueError as exc:
            raise PlanningError("Plan reviewer returned an invalid verdict") from exc
        findings = [str(item) for item in response.get("findings", [])]
        reason = str(response.get("reason", "")).strip()
        largest = str(response.get("largest_risk", "")).strip()
        if reason:
            findings.insert(0, reason)
        if largest:
            findings.append(f"Largest risk: {largest}")
        atomic_write_json(artifact / "review.json", response)
        return verdict, findings

    def _prepare_luna_forge(self, repo: Path) -> LunaForgeStatus | None:
        if not self.config.luna_forge.enabled:
            return None
        if self.config.luna_forge.auto_install:
            return self.luna_forge.ensure_project_install(repo).status
        return self.luna_forge.require_installed(repo)

    def _record_execution(
        self,
        record: RunRecord,
        execution: CodexExecution,
        model: str,
        path: Path,
    ) -> None:
        calculation = self.costs.calculate(model, execution.usage)
        record.actual_credits += calculation.credits
        record.usage.add(execution.usage)
        atomic_write_json(
            path,
            {
                "credits": calculation.credits,
                "source": calculation.source,
                "usage": execution.usage.to_dict(),
                "attestation": execution.attestation.to_dict(),
            },
        )
        self.state.save(record)
        if record.budget_credits is not None and record.actual_credits > record.budget_credits:
            raise PlanningError(
                f"Observed planning credits exceeded budget: {record.actual_credits:.3f} > {record.budget_credits:.3f}"
            )

    @staticmethod
    def _load_plan_file(path: Path) -> ExecutionPlan:
        if not path.is_file():
            raise PlanningError(f"Plan file not found: {path}")
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise TypeError("root must be an object")
            return ExecutionPlan.from_dict(data)
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            raise PlanningError(f"Invalid plan file {path}: {exc}") from exc
