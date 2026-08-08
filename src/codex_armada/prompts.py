from __future__ import annotations

import json
from pathlib import Path

from .domain import ExecutionPlan, RouteDecision, TaskPlan
from .resources import resource_path


class PromptBuilder:
    def planner(self, *, goal: str, repository: Path, profile: str, feedback: list[str] | None = None) -> str:
        return _render(
            "planner.md",
            GOAL=goal,
            REPOSITORY=str(repository),
            PROFILE=profile,
            FEEDBACK="\n".join(f"- {item}" for item in (feedback or [])) or "- None.",
        )

    def worker(
        self,
        *,
        run_id: str,
        task: TaskPlan,
        base_commit: str,
        approved: bool,
        route: RouteDecision | None = None,
    ) -> str:
        task_payload = task.to_dict()
        task_payload["approval_granted"] = approved
        if route and route.worker_protocol == "luna-forge":
            return _render(
                "luna-forge-worker.md",
                **self._forge_task_values(
                    run_id=run_id,
                    task=task,
                    base_commit=base_commit,
                    approved=approved,
                    task_payload=task_payload,
                    route=route,
                ),
            )
        return _render(
            "worker.md",
            RUN_ID=run_id,
            TASK_JSON=json.dumps(task_payload, ensure_ascii=False, indent=2),
            BASE_COMMIT=base_commit,
        )

    def correction(
        self,
        *,
        run_id: str,
        task: TaskPlan,
        base_commit: str,
        approved: bool,
        findings: list[str],
        route: RouteDecision | None = None,
    ) -> str:
        task_payload = task.to_dict()
        task_payload["approval_granted"] = approved
        if route and route.worker_protocol == "luna-forge":
            values = self._forge_task_values(
                run_id=run_id,
                task=task,
                base_commit=base_commit,
                approved=approved,
                task_payload=task_payload,
                route=route,
            )
            values["FINDINGS"] = _bullets(findings, empty="- No concrete finding was supplied; stop as blocked.")
            return _render("luna-forge-correction.md", **values)
        return _render(
            "correction.md",
            RUN_ID=run_id,
            TASK_JSON=json.dumps(task_payload, ensure_ascii=False, indent=2),
            BASE_COMMIT=base_commit,
            FINDINGS="\n".join(f"- {item}" for item in findings),
        )

    def reviewer(
        self,
        *,
        run_id: str,
        task: TaskPlan,
        base_commit: str,
        changed_files: list[str],
        verification: list[dict[str, object]],
    ) -> str:
        return _render(
            "reviewer.md",
            RUN_ID=run_id,
            TASK_JSON=json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
            BASE_COMMIT=base_commit,
            CHANGED_FILES="\n".join(f"- {item}" for item in changed_files) or "- None.",
            VERIFICATION=json.dumps(verification, ensure_ascii=False, indent=2),
        )

    def plan_reviewer(self, *, goal: str, plan: ExecutionPlan) -> str:
        return _render(
            "plan-reviewer.md",
            GOAL=goal,
            PLAN_JSON=json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        )

    def canary(self, *, use_luna_forge: bool = False) -> str:
        name = "luna-forge-canary.md" if use_luna_forge else "canary.md"
        return resource_path("prompts", name).read_text(encoding="utf-8")

    def model_probe(self, *, use_luna_forge: bool = False) -> str:
        if use_luna_forge:
            return resource_path("prompts", "luna-forge-probe.md").read_text(encoding="utf-8")
        return (
            "Read-only model capability probe. Do not modify files. "
            "Return only JSON matching the schema with status `ok` and a short message."
        )

    @staticmethod
    def _forge_task_values(
        *,
        run_id: str,
        task: TaskPlan,
        base_commit: str,
        approved: bool,
        task_payload: dict[str, object],
        route: RouteDecision,
    ) -> dict[str, str]:
        scope = [f"Owned: `{item}`" for item in task.owned_paths]
        scope.extend(f"Excluded: `{item}`" for item in task.excluded_paths)
        interfaces = task.interfaces or ["Preserve existing public and internal interfaces unless the task explicitly says otherwise."]
        acceptance: list[str] = [f"Expected behavior: {task.objective}"]
        acceptance.extend(f"Interface: {item}" for item in interfaces)
        acceptance.extend(
            f"`{item.command}` -> {item.success}" for item in task.verification
        )
        non_goals = ["Any file or behavior outside owned_paths.", "Unrelated cleanup, refactors, or dependency upgrades."]
        non_goals.extend(f"Do not touch excluded path `{item}`." for item in task.excluded_paths)
        risks = [
            f"Risk level: {task.risk.value}.",
            f"File deletion allowed by plan: {task.allow_deletions}; approval granted: {approved}.",
            f"Production change allowed by plan: {task.allow_production_changes}; approval granted: {approved}.",
        ]
        risks.extend(task.constraints)
        validation = [f"`{item.command}`; success: {item.success}" for item in task.verification]
        if not validation:
            validation.append("`git diff --check`; success: exit code 0.")
        return {
            "LUNA_FORGE_VERSION": route.worker_skill_version or "unknown",
            "LUNA_FORGE_REPOSITORY": route.worker_skill_repository or "unknown",
            "LUNA_FORGE_COMMIT": route.worker_skill_commit or "unknown",
            "RUN_ID": run_id,
            "BASE_COMMIT": base_commit,
            "OBJECTIVE": task.objective,
            "AUTHORIZED_SCOPE": _bullets(scope),
            "EXPECTED_BEHAVIOR": _bullets([task.objective, *interfaces]),
            "ACCEPTANCE": _bullets(acceptance),
            "NON_GOALS": _bullets(non_goals),
            "RISK_BOUNDARIES": _bullets(risks),
            "VALIDATION": _bullets(validation),
            "TASK_JSON": json.dumps(task_payload, ensure_ascii=False, indent=2),
        }


def _bullets(values: list[str], *, empty: str = "- None.") -> str:
    rendered = [f"- {value}" for value in values if str(value).strip()]
    return "\n".join(rendered) or empty


def _render(name: str, **values: str) -> str:
    text = resource_path("prompts", name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text
