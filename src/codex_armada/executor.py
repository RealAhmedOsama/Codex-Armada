from __future__ import annotations

from pathlib import Path

from .budget import BudgetGovernor
from .codex import CodexExecution, CodexRunner
from .config import AppConfig
from .costs import CostCalculator
from .doctor import CapabilitySet
from .domain import (
    ReviewVerdict,
    RunRecord,
    RunStatus,
    TaskKind,
    TaskRecord,
    TaskStatus,
)
from .errors import ExecutionError, GitSafetyError, LunaForgeError, StateError, VerificationError
from .git import GitRepository, find_pattern_matches, find_scope_violations
from .luna_forge import LunaForgeManager, LunaForgeStatus
from .prompts import PromptBuilder
from .resources import resource_path
from .state import ProjectLock, StateStore
from .util import atomic_write_json, atomic_write_text, redact, slugify, utc_now
from .validation import topological_order
from .verification import VerificationRunner


class Executor:
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
        self.verifier = VerificationRunner(config)
        self.luna_forge = LunaForgeManager(config)

    def execute(
        self,
        record: RunRecord,
        *,
        approved_tasks: set[str] | None = None,
        approve_all_required: bool = False,
        commit_enabled: bool | None = None,
        keep_worktrees: bool = False,
    ) -> RunRecord:
        approved_tasks = approved_tasks or set()
        commit = self.config.commit_per_task if commit_enabled is None else commit_enabled
        if not record.plan:
            raise StateError("Run has no execution plan")
        record.commit_enabled = commit
        if not commit and len(record.tasks) > 1:
            raise StateError("--no-commit is supported only for a single-task plan; task isolation needs commit boundaries")
        if record.config_digest != self.config.digest:
            raise StateError("Configuration changed after planning; create a fresh plan")
        if record.capability_digest != self.capabilities.digest:
            raise StateError("Codex capability lock changed after planning; create a fresh plan")

        main_git = GitRepository(Path(record.repo))
        if self.config.require_clean_tree:
            main_git.require_clean()
        if main_git.head() != record.current_commit:
            raise StateError(
                f"Repository HEAD changed after planning: expected {record.current_commit}, observed {main_git.head()}"
            )
        governor = BudgetGovernor(record.budget_credits)

        with ProjectLock(self.state.paths.project_lock):
            record.status = RunStatus.RUNNING
            record.error = None
            self.state.save(record)
            by_id = {task.plan.id: task for task in record.tasks}
            for task_id in topological_order(record.plan):
                task = by_id[task_id]
                if task.status == TaskStatus.ACCEPTED:
                    continue
                if task.status in {TaskStatus.RUNNING, TaskStatus.VERIFYING, TaskStatus.REVIEWING}:
                    task.status = TaskStatus.BLOCKED
                    task.error = "Previous process was interrupted while this task was active; inspect its retained worktree"
                    record.status = RunStatus.BLOCKED
                    record.error = task.error
                    self.state.save(record)
                    return record
                missing = [dependency for dependency in task.plan.depends_on if by_id[dependency].status != TaskStatus.ACCEPTED]
                if missing:
                    task.status = TaskStatus.BLOCKED
                    task.error = f"Dependencies are not accepted: {missing}"
                    record.status = RunStatus.BLOCKED
                    record.error = task.error
                    self.state.save(record)
                    return record
                approved = approve_all_required or task.plan.id in approved_tasks
                if task.route.approval_required and not approved:
                    task.status = TaskStatus.AWAITING_APPROVAL
                    task.error = "Explicit approval required"
                    record.status = RunStatus.AWAITING_APPROVAL
                    record.error = f"Task `{task.plan.id}` requires approval"
                    self.state.save(record)
                    return record
                try:
                    self._execute_task(
                        record=record,
                        task=task,
                        main_git=main_git,
                        governor=governor,
                        approved=approved,
                        commit_enabled=commit,
                        keep_worktrees=keep_worktrees,
                    )
                except Exception as exc:
                    task.status = TaskStatus.FAILED
                    task.error = str(exc)
                    task.completed_at = utc_now()
                    record.status = RunStatus.FAILED
                    record.error = f"Task {task.plan.id}: {exc}"
                    self.state.save(record)
                    raise
                if task.status != TaskStatus.ACCEPTED:
                    record.status = RunStatus.BLOCKED
                    record.error = task.error or f"Task {task.plan.id} was not accepted"
                    self.state.save(record)
                    return record

            record.status = RunStatus.COMPLETED
            record.error = None
            record.current_commit = main_git.head()
            self.state.save(record)
            return record

    def _execute_task(
        self,
        *,
        record: RunRecord,
        task: TaskRecord,
        main_git: GitRepository,
        governor: BudgetGovernor,
        approved: bool,
        commit_enabled: bool,
        keep_worktrees: bool,
    ) -> None:
        governor.ensure_capacity(
            actual=record.actual_credits,
            expected_next=task.route.estimated_credits,
            label=f"task {task.plan.id}",
        )
        base_commit = record.current_commit or main_git.head()
        workdir = main_git.repo
        branch_name: str | None = None
        isolated = self.config.use_isolated_worktrees and commit_enabled
        if isolated:
            branch_name = main_git.branch_name_for_task(record.run_id, task.plan.id)
            workdir = self.state.paths.worktrees_root / record.run_id / slugify(task.plan.id)
            main_git.create_worktree(path=workdir, base_commit=base_commit, branch_name=branch_name)
            task.worktree_path = str(workdir)
        task_git = GitRepository(workdir)
        task_artifacts = self.state.artifact_dir(record.run_id, "tasks", task.plan.id)
        forge_baseline: LunaForgeStatus | None = None
        if task.route.worker_protocol == "luna-forge":
            if not self.config.luna_forge.enabled:
                raise ExecutionError("Task was routed through Luna Forge while the integration is disabled")
            if self.config.luna_forge.auto_install:
                install = self.luna_forge.ensure_project_install(workdir)
                atomic_write_json(task_artifacts / "luna-forge-install.json", install.to_dict())
                forge_baseline = install.status
            else:
                forge_baseline = self.luna_forge.require_installed(workdir)
                atomic_write_json(task_artifacts / "luna-forge-install.json", {
                    "changed": False,
                    "dry_run": False,
                    "backed_up": [],
                    "installed": [],
                    "status": forge_baseline.to_dict(),
                })
        task_git.require_clean()
        task.status = TaskStatus.RUNNING
        task.started_at = utc_now()
        task.error = None
        self.state.save(record)

        findings: list[str] = []
        for attempt in range(self.config.max_corrections + 1):
            governor.ensure_capacity(
                actual=record.actual_credits,
                expected_next=self.costs.typical(task.route.worker_model),
                label=f"{('worker' if attempt == 0 else 'correction')} {task.plan.id}",
            )
            task.attempts += 1
            attempt_dir = task_artifacts / f"attempt-{attempt + 1:02d}"
            if attempt == 0:
                prompt = self.prompts.worker(
                    run_id=record.run_id,
                    task=task.plan,
                    base_commit=base_commit,
                    approved=approved,
                    route=task.route,
                )
                label = "worker"
            else:
                prompt = self.prompts.correction(
                    run_id=record.run_id,
                    task=task.plan,
                    base_commit=base_commit,
                    approved=approved,
                    findings=findings,
                    route=task.route,
                )
                label = "correction"
                task.corrections += 1

            execution = self.codex.run(
                repo=workdir,
                prompt=prompt,
                model=task.route.worker_model,
                effort=task.route.worker_effort,
                sandbox=task.route.sandbox,
                schema_path=resource_path("schemas", "worker.schema.json"),
                artifact_dir=attempt_dir,
                label=label,
            )
            self._record_execution(record, task, execution, task.route.worker_model, attempt_dir / "cost.json")
            hard_failure = self._execution_failure(task, execution, expected_sandbox=task.route.sandbox)
            if forge_baseline is not None:
                try:
                    current_forge = self.luna_forge.require_unchanged(
                        workdir, forge_baseline, actor=f"{label} for task {task.plan.id}"
                    )
                    atomic_write_json(attempt_dir / "luna-forge-after.json", current_forge.to_dict())
                except Exception as exc:
                    task.status = TaskStatus.BLOCKED
                    hard_failure = f"Pinned Luna Forge integrity violation: {exc}"
            if hard_failure:
                findings = [hard_failure]
            else:
                task.worker_result = execution.final_response
                findings = self._inspect_and_verify(
                    record=record,
                    task=task,
                    task_git=task_git,
                    workdir=workdir,
                    artifact_dir=attempt_dir,
                    approved=approved,
                )
                if not findings and task.route.final_review:
                    findings = self._review_task(
                        record=record,
                        task=task,
                        task_git=task_git,
                        workdir=workdir,
                        base_commit=base_commit,
                        artifact_dir=attempt_dir / "review",
                        forge_baseline=forge_baseline,
                    )
            if task.status == TaskStatus.BLOCKED:
                task.error = " | ".join(findings) or "Reviewer blocked the task"
                task.completed_at = utc_now()
                self.state.save(record)
                return
            atomic_write_json(attempt_dir / "findings.json", findings)
            self.state.save(record)

            if not findings:
                if task.plan.kind != TaskKind.RECON and not task.changed_files:
                    findings = ["Worker produced no repository changes"]
                else:
                    self._accept_task(
                        record=record,
                        task=task,
                        main_git=main_git,
                        task_git=task_git,
                        workdir=workdir,
                        branch_name=branch_name,
                        isolated=isolated,
                        commit_enabled=commit_enabled,
                        keep_worktrees=keep_worktrees,
                    )
                    return

            safety_failure = bool(
                task.scope_violations
                or task.protected_path_violations
                or task.symlink_violations
                or (task.deletions and not (approved and task.plan.allow_deletions))
            )
            if safety_failure:
                task.status = TaskStatus.BLOCKED
                task.error = "Unsafe change boundary: " + " | ".join(findings)
                task.completed_at = utc_now()
                self.state.save(record)
                return
            if attempt >= self.config.max_corrections:
                task.status = TaskStatus.BLOCKED
                task.error = "Correction budget exhausted: " + " | ".join(findings)
                task.completed_at = utc_now()
                self.state.save(record)
                return

    def _inspect_and_verify(
        self,
        *,
        record: RunRecord,
        task: TaskRecord,
        task_git: GitRepository,
        workdir: Path,
        artifact_dir: Path,
        approved: bool,
    ) -> list[str]:
        changed = task_git.changed_files()
        task.changed_files = changed
        task.deletions = task_git.deleted_files()
        task.scope_violations = find_scope_violations(changed, task.plan.owned_paths, task.plan.excluded_paths)
        task.protected_path_violations = find_pattern_matches(changed, self.config.protected_paths)
        task.symlink_violations = task_git.symlink_files(changed)
        production_changes = find_pattern_matches(changed, self.config.production_paths)
        evidence = task_git.evidence_diff(changed) if changed else ""
        atomic_write_text(artifact_dir / "task.diff", redact(evidence))
        findings: list[str] = []
        if task.plan.kind == TaskKind.RECON and changed:
            findings.append(f"Read-only recon task changed files: {changed}")
        if task.scope_violations:
            findings.append(f"Changed files outside owned scope: {task.scope_violations}")
        if task.protected_path_violations:
            findings.append(f"Protected paths changed: {task.protected_path_violations}")
        if task.symlink_violations:
            findings.append(f"Symbolic links are not accepted: {task.symlink_violations}")
        if task.deletions and not (approved and task.plan.allow_deletions):
            findings.append(f"Unapproved file deletions: {task.deletions}")
        if production_changes and not (approved and task.plan.allow_production_changes):
            findings.append(f"Unapproved production/deployment changes: {production_changes}")
        response = task.worker_result or {}
        status = str(response.get("status", ""))
        if status != "complete":
            findings.append(f"Worker status is `{status or 'missing'}`")
        gaps = response.get("gaps", [])
        if isinstance(gaps, list):
            findings.extend(f"Worker gap: {item}" for item in gaps if str(item).strip())
        if findings:
            return findings

        task.status = TaskStatus.VERIFYING
        self.state.save(record)
        specs = list(task.plan.verification)
        if task.plan.kind != TaskKind.RECON and not specs:
            from .domain import VerificationSpec

            specs = [VerificationSpec(command="git diff --check", success="exit code 0")]
        task.verification_results = []
        for index, spec in enumerate(specs, start=1):
            try:
                result = self.verifier.run(
                    repo=workdir,
                    git=task_git,
                    spec=spec,
                    artifact_dir=artifact_dir / "verification",
                    index=index,
                )
            except VerificationError as exc:
                findings.append(str(exc))
                continue
            task.verification_results.append(result)
            if not result.passed:
                findings.append(
                    f"Verification failed: `{result.command}`: {result.error or f'exit {result.exit_code}'}"
                )
        return findings

    def _review_task(
        self,
        *,
        record: RunRecord,
        task: TaskRecord,
        task_git: GitRepository,
        workdir: Path,
        base_commit: str,
        artifact_dir: Path,
        forge_baseline: LunaForgeStatus | None,
    ) -> list[str]:
        governor = BudgetGovernor(record.budget_credits)
        governor.ensure_capacity(
            actual=record.actual_credits,
            expected_next=self.costs.typical(self.config.reviewer_model),
            label=f"review {task.plan.id}",
        )
        task.status = TaskStatus.REVIEWING
        self.state.save(record)
        before = task_git.snapshot()
        reviewer_forge_before = self.luna_forge.require_installed(workdir) if forge_baseline is not None else None
        execution = self.codex.run(
            repo=workdir,
            prompt=self.prompts.reviewer(
                run_id=record.run_id,
                task=task.plan,
                base_commit=base_commit,
                changed_files=task.changed_files,
                verification=[item.to_dict() for item in task.verification_results],
            ),
            model=self.config.reviewer_model,
            effort=self.config.reviewer_effort,
            sandbox="read-only",
            schema_path=resource_path("schemas", "review.schema.json"),
            artifact_dir=artifact_dir,
            label="reviewer",
        )
        self._record_execution(record, task, execution, self.config.reviewer_model, artifact_dir / "cost.json")
        after = task_git.snapshot()
        if before != after:
            task.status = TaskStatus.BLOCKED
            return ["Read-only reviewer changed repository state"]
        if reviewer_forge_before is not None:
            try:
                reviewer_forge_after = self.luna_forge.require_unchanged(
                    workdir, reviewer_forge_before, actor=f"reviewer for task {task.plan.id}"
                )
                atomic_write_json(artifact_dir / "luna-forge-after.json", reviewer_forge_after.to_dict())
            except Exception as exc:
                task.status = TaskStatus.BLOCKED
                return [f"Read-only reviewer changed the pinned Luna Forge runtime: {exc}"]
        failure = self._execution_failure(task, execution, expected_sandbox="read-only", review=True)
        if failure:
            return [failure]
        task.review_result = execution.final_response
        response = execution.final_response or {}
        try:
            verdict = ReviewVerdict(str(response.get("verdict")))
        except ValueError:
            return ["Reviewer returned an invalid verdict"]
        if verdict == ReviewVerdict.SHIP:
            return []
        if verdict == ReviewVerdict.RETHINK:
            task.status = TaskStatus.BLOCKED
            return [f"Reviewer requires architectural rethink: {response.get('reason', '')}"]
        findings: list[str] = []
        for item in response.get("findings", []):
            if isinstance(item, dict):
                findings.append(
                    f"{item.get('severity', 'unknown')} {item.get('path', '')}: "
                    f"{item.get('description', '')}; required fix: {item.get('required_fix', '')}"
                )
        return findings or [f"Reviewer returned fix-first: {response.get('reason', '')}"]

    def _execution_failure(
        self,
        task: TaskRecord,
        execution: CodexExecution,
        *,
        expected_sandbox: str,
        review: bool = False,
    ) -> str | None:
        role = "Reviewer" if review else "Worker"
        if not execution.succeeded:
            detail = execution.stderr_path.read_text(encoding="utf-8", errors="replace")[-2500:].strip()
            return f"{role} failed or returned invalid structured output: {detail}"
        if execution.attestation.mismatch:
            return f"{role} runtime mismatch: {execution.attestation.mismatch}"
        if task.plan.risk.rank >= self.config.attestation_required_from.rank and not execution.attestation.verified:
            return f"{role} model/effort could not be independently attested"
        if (
            review
            and task.plan.risk.rank >= self.config.attestation_required_from.rank
            and execution.attestation.observed_sandbox != "read-only"
        ):
            return "Critical review lacks observed read-only sandbox evidence"
        if execution.attestation.observed_sandbox and execution.attestation.observed_sandbox != expected_sandbox:
            return (
                f"{role} sandbox mismatch: requested={expected_sandbox} "
                f"observed={execution.attestation.observed_sandbox}"
            )
        return None

    def _accept_task(
        self,
        *,
        record: RunRecord,
        task: TaskRecord,
        main_git: GitRepository,
        task_git: GitRepository,
        workdir: Path,
        branch_name: str | None,
        isolated: bool,
        commit_enabled: bool,
        keep_worktrees: bool,
    ) -> None:
        if task.plan.kind == TaskKind.RECON:
            if task_git.changed_files():
                raise GitSafetyError("Recon task cannot be accepted with repository changes")
        elif commit_enabled:
            message = _commit_message(task)
            source_sha = task_git.commit(task.changed_files, message, cwd=workdir)
            task.source_commit_sha = source_sha
            if isolated:
                applied_sha = main_git.apply_commit(source_sha)
                task.applied_commit_sha = applied_sha
                record.current_commit = applied_sha
            else:
                task.applied_commit_sha = source_sha
                record.current_commit = source_sha
        task.status = TaskStatus.ACCEPTED
        task.completed_at = utc_now()
        task.error = None
        self.state.save(record)
        if isolated and task.worktree_path and not keep_worktrees:
            try:
                if task.route.worker_protocol == "luna-forge":
                    self.luna_forge.remove_exact_project_install(Path(task.worktree_path))
                main_git.remove_worktree(Path(task.worktree_path), branch_name=branch_name, force=False)
                task.worktree_path = None
            except (GitSafetyError, LunaForgeError) as exc:
                # The accepted commit is already applied to the main branch. A cleanup
                # failure must not rewrite that truthful acceptance state.
                task.error = f"Accepted; temporary worktree cleanup failed and was retained: {exc}"
            self.state.save(record)

    def _record_execution(
        self,
        record: RunRecord,
        task: TaskRecord,
        execution: CodexExecution,
        model: str,
        cost_path: Path,
    ) -> None:
        calculation = self.costs.calculate(model, execution.usage)
        task.runtime_attestations.append(execution.attestation)
        task.usage.add(execution.usage)
        task.credits += calculation.credits
        task.credits_source = calculation.source
        record.usage.add(execution.usage)
        record.actual_credits += calculation.credits
        atomic_write_json(
            cost_path,
            {
                "model": model,
                "credits": calculation.credits,
                "source": calculation.source,
                "usage": execution.usage.to_dict(),
                "attestation": execution.attestation.to_dict(),
            },
        )
        self.state.save(record)
        if record.budget_credits is not None and record.actual_credits > record.budget_credits:
            raise ExecutionError(
                f"Observed credits exceeded budget: {record.actual_credits:.3f} > {record.budget_credits:.3f}"
            )


def _commit_message(task: TaskRecord) -> str:
    if task.plan.commit_message:
        message = task.plan.commit_message.strip()
    else:
        commit_type = {
            TaskKind.DOCUMENTATION: "docs",
            TaskKind.TEST: "test",
            TaskKind.BUGFIX: "fix",
            TaskKind.REFACTOR: "refactor",
            TaskKind.MIGRATION: "feat",
            TaskKind.SECURITY: "fix",
            TaskKind.OPERATIONS: "chore",
            TaskKind.IMPLEMENTATION: "feat",
            TaskKind.RECON: "chore",
        }[task.plan.kind]
        scope = slugify(task.plan.tags[0] if task.plan.tags else task.plan.id, max_length=24)
        subject = task.plan.title.strip().rstrip(".")
        message = f"{commit_type}({scope}): {subject}"
    first_line = message.splitlines()[0].strip()
    if len(first_line) > 100:
        first_line = first_line[:97].rstrip() + "..."
    return first_line
