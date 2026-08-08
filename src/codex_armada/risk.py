from __future__ import annotations

from .config import AppConfig
from .domain import RiskLevel, TaskKind, TaskPlan
from .git import path_matches


class RiskEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def classify(self, task: TaskPlan) -> tuple[RiskLevel, list[str]]:
        risk = task.risk
        reasons = [f"Planner classified task as {task.risk.value}"]
        if task.kind in {TaskKind.MIGRATION, TaskKind.OPERATIONS}:
            risk = RiskLevel.highest(risk, RiskLevel.CRITICAL)
            reasons.append(f"Task kind `{task.kind.value}` is critical")
        elif task.kind == TaskKind.SECURITY:
            risk = RiskLevel.highest(risk, RiskLevel.HIGH)
            reasons.append("Security task")

        for path in [*task.owned_paths, *task.excluded_paths]:
            for rule in self.config.risk_rules:
                if path_matches(path, rule.pattern) or path_matches(rule.pattern, path):
                    if rule.risk.rank > risk.rank:
                        risk = rule.risk
                    reasons.append(f"{rule.reason}: {path}")
            if any(path_matches(path, pattern) or path_matches(pattern, path) for pattern in self.config.production_paths):
                risk = RiskLevel.CRITICAL
                reasons.append(f"Production/deployment path: {path}")

        text = " ".join([task.title, task.objective, *task.tags, *task.constraints]).lower()
        critical_terms = (
            "migration", "production", "deploy", "payment", "billing", "wallet", "credit",
            "secret", "credential", "destructive", "delete table", "drop table", "rotate token",
        )
        high_terms = (
            "authentication", "authorization", "tenant", "tenancy", "security", "encryption",
            "concurrency", "distributed", "public api", "breaking change", "permission",
        )
        if any(term in text for term in critical_terms):
            risk = RiskLevel.CRITICAL
            reasons.append("Critical-risk keyword in task contract")
        elif any(term in text for term in high_terms):
            risk = RiskLevel.highest(risk, RiskLevel.HIGH)
            reasons.append("High-risk keyword in task contract")
        return risk, _unique(reasons)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
