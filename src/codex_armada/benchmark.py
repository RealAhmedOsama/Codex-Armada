from __future__ import annotations

from .config import AppConfig
from .domain import RiskLevel, TaskKind, TaskPlan
from .routing import Router


def routing_benchmark(config: AppConfig) -> dict[str, object]:
    router = Router(config)
    samples = [
        TaskPlan("docs", "Update docs", "Correct product documentation", TaskKind.DOCUMENTATION, ["docs/**"], risk=RiskLevel.LOW),
        TaskPlan("tests", "Add tests", "Add focused regression tests", TaskKind.TEST, ["tests/**"], risk=RiskLevel.LOW),
        TaskPlan("feature", "Build feature", "Implement a bounded application feature", TaskKind.IMPLEMENTATION, ["src/Feature/**"], risk=RiskLevel.MEDIUM),
        TaskPlan("auth", "Fix authorization", "Correct tenant-aware authorization", TaskKind.SECURITY, ["src/Auth/**"], risk=RiskLevel.HIGH),
        TaskPlan("migration", "Apply migration", "Create a production database migration", TaskKind.MIGRATION, ["src/Migrations/**"], risk=RiskLevel.CRITICAL),
    ]
    rows: list[dict[str, object]] = []
    for task in samples:
        route = router.route(task)
        rows.append(
            {
                "task": task.id,
                "risk": task.risk.value,
                "model_alias": route.worker_alias,
                "model": route.worker_model,
                "effort": route.worker_effort,
                "worker_protocol": route.worker_protocol,
                "worker_skill": route.worker_skill,
                "worker_skill_version": route.worker_skill_version,
                "worker_skill_repository": route.worker_skill_repository,
                "worker_skill_ref": route.worker_skill_ref,
                "worker_skill_commit": route.worker_skill_commit,
                "plan_review": route.plan_review,
                "final_review": route.final_review,
                "approval": route.approval_required,
                "estimated_credits": route.estimated_credits,
            }
        )
    return {"profile": config.profile_name, "routes": rows}
