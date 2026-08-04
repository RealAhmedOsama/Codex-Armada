from __future__ import annotations

import re
from collections import defaultdict, deque

from .config import AppConfig
from .domain import ExecutionPlan, TaskKind
from .errors import PlanningError
from .git import find_pattern_matches, path_matches
from .routing import Router
from .util import normalize_git_path

_TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_BROAD_PATTERNS = {"", ".", "*", "**", "./**", "**/*", "/"}


class PlanValidator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.router = Router(config)

    def validate_and_route(self, plan: ExecutionPlan) -> list[str]:
        errors: list[str] = []
        if not plan.goal:
            errors.append("Plan goal is empty")
        if not plan.tasks:
            errors.append("Plan contains no tasks")
            return errors
        ids = [task.id for task in plan.tasks]
        if len(ids) != len(set(ids)):
            errors.append("Task IDs must be unique")
        for task in plan.tasks:
            if not _TASK_ID.fullmatch(task.id):
                errors.append(f"Invalid task ID: {task.id}")
            if not task.title or not task.objective:
                errors.append(f"Task {task.id} needs a title and objective")
            unsafe_owned = [path for path in task.owned_paths if _unsafe_repo_pattern(path)]
            unsafe_excluded = [path for path in task.excluded_paths if _unsafe_repo_pattern(path)]
            if unsafe_owned:
                errors.append(f"Task {task.id} has unsafe owned paths: {unsafe_owned}")
            if unsafe_excluded:
                errors.append(f"Task {task.id} has unsafe excluded paths: {unsafe_excluded}")
            task.owned_paths = [normalize_git_path(path) for path in task.owned_paths]
            task.excluded_paths = [normalize_git_path(path) for path in task.excluded_paths]
            if task.kind != TaskKind.RECON and not task.owned_paths:
                errors.append(f"Task {task.id} has no owned paths")
            if any(path in _BROAD_PATTERNS for path in task.owned_paths):
                errors.append(f"Task {task.id} owns an unsafe broad path")
            protected = find_pattern_matches(task.owned_paths, self.config.protected_paths)
            if protected:
                errors.append(f"Task {task.id} attempts to own protected paths: {protected}")
            unknown_dependencies = sorted(set(task.depends_on) - set(ids))
            if unknown_dependencies:
                errors.append(f"Task {task.id} has unknown dependencies: {unknown_dependencies}")
            if task.id in task.depends_on:
                errors.append(f"Task {task.id} depends on itself")
            for verification in task.verification:
                if not verification.command:
                    errors.append(f"Task {task.id} contains an empty verification command")
            self.router.route(task)
        errors.extend(_ownership_overlaps(plan))
        errors.extend(_cycle_errors(plan))
        return errors

    def require_valid(self, plan: ExecutionPlan) -> None:
        errors = self.validate_and_route(plan)
        if errors:
            raise PlanningError("Invalid execution plan:\n- " + "\n- ".join(errors))


def topological_order(plan: ExecutionPlan) -> list[str]:
    dependencies = {task.id: set(task.depends_on) for task in plan.tasks}
    dependents: dict[str, set[str]] = defaultdict(set)
    for task_id, items in dependencies.items():
        for dependency in items:
            dependents[dependency].add(task_id)
    queue = deque(sorted(task_id for task_id, items in dependencies.items() if not items))
    result: list[str] = []
    while queue:
        task_id = queue.popleft()
        result.append(task_id)
        for child in sorted(dependents[task_id]):
            dependencies[child].discard(task_id)
            if not dependencies[child]:
                queue.append(child)
    if len(result) != len(plan.tasks):
        raise PlanningError("Task dependency graph contains a cycle")
    return result


def _ownership_overlaps(plan: ExecutionPlan) -> list[str]:
    errors: list[str] = []
    for index, left in enumerate(plan.tasks):
        for right in plan.tasks[index + 1 :]:
            if left.id in right.depends_on or right.id in left.depends_on:
                continue
            for left_pattern in left.owned_paths:
                for right_pattern in right.owned_paths:
                    if (
                        left_pattern == right_pattern
                        or path_matches(left_pattern, right_pattern)
                        or path_matches(right_pattern, left_pattern)
                    ):
                        errors.append(
                            f"Independent tasks {left.id} and {right.id} have overlapping ownership: "
                            f"{left_pattern} <> {right_pattern}"
                        )
    return errors


def _cycle_errors(plan: ExecutionPlan) -> list[str]:
    try:
        topological_order(plan)
        return []
    except PlanningError as exc:
        return [str(exc)]


def _unsafe_repo_pattern(value: str) -> bool:
    candidate = str(value).strip().replace("\\", "/")
    if not candidate or "\x00" in candidate:
        return True
    if candidate.startswith(("/", "//", "~/")):
        return True
    if re.match(r"^[A-Za-z]:[/\\]", candidate):
        return True
    return any(part == ".." for part in candidate.split("/"))
