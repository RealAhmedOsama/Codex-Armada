from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from .domain import RunRecord, RunStatus, TaskStatus
from .git import GitRepository


class RunVerifier:
    """Re-check durable run state against the current repository and recorded evidence."""

    def verify(self, record: RunRecord) -> dict[str, object]:
        findings: list[str] = []
        git = GitRepository(Path(record.repo))
        if record.status == RunStatus.COMPLETED:
            incomplete = [task.plan.id for task in record.tasks if task.status != TaskStatus.ACCEPTED]
            if incomplete:
                findings.append(f"Completed run contains unaccepted tasks: {incomplete}")
        if record.current_commit and git.head() != record.current_commit:
            findings.append(f"Repository HEAD differs: state={record.current_commit}, actual={git.head()}")
        if record.commit_enabled:
            if git.status():
                findings.append("Repository working tree is not clean")
        else:
            expected_dirty = sorted({path for task in record.tasks for path in task.changed_files})
            actual_dirty = git.changed_files()
            if actual_dirty != expected_dirty:
                findings.append(f"No-commit working tree differs: expected={expected_dirty}, actual={actual_dirty}")

        for task in record.tasks:
            task_id = task.plan.id
            if task.status != TaskStatus.ACCEPTED:
                continue
            if task.scope_violations:
                findings.append(f"Accepted task {task_id} records scope violations: {task.scope_violations}")
            if task.protected_path_violations:
                findings.append(
                    f"Accepted task {task_id} records protected-path violations: {task.protected_path_violations}"
                )
            if task.symlink_violations:
                findings.append(f"Accepted task {task_id} records symbolic-link violations: {task.symlink_violations}")
            if any(not item.passed for item in task.verification_results):
                findings.append(f"Accepted task {task_id} contains failed verification evidence")
            if task.plan.kind.value != "recon" and not task.verification_results:
                findings.append(f"Accepted task {task_id} has no deterministic verification evidence")
            if any(attestation.mismatch for attestation in task.runtime_attestations):
                findings.append(f"Accepted task {task_id} contains runtime routing mismatch")
            if not task.runtime_attestations:
                findings.append(f"Accepted task {task_id} has no runtime execution evidence")
            if task.route.final_review:
                verdict = (task.review_result or {}).get("verdict")
                if verdict != "ship":
                    findings.append(f"Accepted task {task_id} lacks a final `ship` review verdict")

            if task.plan.kind.value != "recon":
                if record.commit_enabled and not task.applied_commit_sha and not task.source_commit_sha:
                    findings.append(f"Accepted task {task_id} has no commit evidence")
                commit_sha = task.applied_commit_sha or task.source_commit_sha
                if commit_sha and not git.commit_exists(commit_sha):
                    findings.append(f"Accepted task {task_id} commit does not exist: {commit_sha}")

            if task.route.worker_protocol == "luna-forge":
                findings.extend(self._verify_luna_forge_route(task_id, task.route.to_dict()))

        return {
            "run_id": record.run_id,
            "valid": not findings,
            "findings": findings,
            "status": record.status.value,
            "head": git.head(),
            "expected_head": record.current_commit,
        }

    @staticmethod
    def _verify_luna_forge_route(task_id: str, route: dict[str, object]) -> list[str]:
        findings: list[str] = []
        repository = str(route.get("worker_skill_repository") or "")
        ref = str(route.get("worker_skill_ref") or "")
        commit = str(route.get("worker_skill_commit") or "")
        parsed = urlparse(repository)
        if route.get("worker_alias") != "luna" or route.get("worker_model") != "gpt-5.6-luna":
            findings.append(f"Accepted Luna Forge task {task_id} does not record the Luna model route")
        if route.get("worker_skill") != "luna-forge" or not route.get("worker_skill_version"):
            findings.append(f"Accepted Luna Forge task {task_id} lacks skill identity/version evidence")
        if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
            findings.append(f"Accepted Luna Forge task {task_id} lacks an HTTPS GitHub source")
        if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit.lower()):
            findings.append(f"Accepted Luna Forge task {task_id} lacks a full pinned commit SHA")
        if ref != commit:
            findings.append(f"Accepted Luna Forge task {task_id} does not use its exact commit as the fetch ref")
        return findings
