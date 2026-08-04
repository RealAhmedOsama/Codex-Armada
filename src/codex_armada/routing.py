from __future__ import annotations

from .config import AppConfig
from .domain import RouteDecision, TaskKind, TaskPlan
from .costs import CostCalculator
from .risk import RiskEngine


_EFFORT_RANK = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "xhigh": 4,
    "max": 5,
}


class Router:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.risk = RiskEngine(config)
        self.costs = CostCalculator(config)

    def route(self, task: TaskPlan) -> RouteDecision:
        risk, reasons = self.risk.classify(task)
        task.risk = risk
        profile = self.config.profile
        alias = profile.workers[risk]
        model = self.config.model_for_alias(alias)
        effort = profile.efforts[risk]
        protocol = "standard"
        skill: str | None = None
        skill_version: str | None = None
        skill_repository: str | None = None
        skill_ref: str | None = None
        skill_commit: str | None = None

        forge = self.config.luna_forge
        if forge.enabled and alias in forge.invoke_for_aliases:
            protocol = "luna-forge"
            skill = forge.skill_name
            skill_version = forge.required_version
            skill_repository = forge.repository
            skill_ref = forge.ref
            skill_commit = forge.expected_commit
            if _EFFORT_RANK.get(effort, -1) < _EFFORT_RANK.get(forge.default_effort, 3):
                previous = effort
                effort = forge.default_effort
                reasons.append(
                    f"Luna Forge raises reasoning effort from {previous} to {effort} for its pinned worker contract"
                )
            reasons.append(
                f"Pinned Luna Forge {forge.required_version} skill protocol applies to model alias `{alias}`"
            )

        sandbox = "read-only" if task.kind == TaskKind.RECON else "workspace-write"
        final_review = risk.rank >= profile.final_review_from.rank
        plan_review = risk.rank >= profile.plan_review_from.rank
        approval = risk.rank >= profile.approval_from.rank
        if task.allow_deletions:
            approval = True
            reasons.append("Task requests file deletion")
        if task.allow_production_changes:
            approval = True
            reasons.append("Task requests production/deployment changes")
        reasons.extend(
            [
                f"Profile `{profile.name}` routes {risk.value} work to {alias}/{effort}",
                f"Final review: {'required' if final_review else 'not required'}",
                f"User approval: {'required' if approval else 'not required'}",
            ]
        )
        estimated = self.costs.typical(model)
        if final_review:
            estimated += self.costs.typical(self.config.reviewer_model)
        return RouteDecision(
            worker_alias=alias,
            worker_model=model,
            worker_effort=effort,
            sandbox=sandbox,
            final_review=final_review,
            plan_review=plan_review,
            approval_required=approval,
            estimated_credits=estimated,
            worker_protocol=protocol,
            worker_skill=skill,
            worker_skill_version=skill_version,
            worker_skill_repository=skill_repository,
            worker_skill_ref=skill_ref,
            worker_skill_commit=skill_commit,
            execution_transport="codex-exec",
            reasons=reasons,
        )
