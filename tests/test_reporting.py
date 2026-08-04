from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_armada.domain import (
    CommandResult,
    RiskLevel,
    RouteDecision,
    RunRecord,
    RunStatus,
    RuntimeAttestation,
    TaskKind,
    TaskPlan,
    TaskRecord,
    TaskStatus,
)
from codex_armada.paths import ProjectPaths
from codex_armada.report import ReportGenerator
from codex_armada.run_verifier import RunVerifier
from codex_armada.state import StateStore
from tests.helpers import initialize_repo, run


class ReportingAndVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        initialize_repo(self.repo)
        self.head = run(["git", "rev-parse", "HEAD"], cwd=self.repo).stdout.strip()
        self.state_root = self.root / "state"
        paths = ProjectPaths(
            repo=self.repo,
            state_root=self.state_root,
            project_root=self.state_root / "project",
            runs_root=self.state_root / "project" / "runs",
            worktrees_root=self.state_root / "project" / "worktrees",
            capabilities_file=self.state_root / "project" / "capabilities.lock.json",
            project_lock=self.state_root / "project" / "project.lock",
        )
        self.state = StateStore(paths)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def record(self, *, title: str = "Update documentation") -> RunRecord:
        plan = TaskPlan(
            id="docs",
            title=title,
            objective="Update one public document",
            kind=TaskKind.DOCUMENTATION,
            owned_paths=["README.md"],
            risk=RiskLevel.LOW,
        )
        route = RouteDecision(
            worker_alias="luna",
            worker_model="gpt-5.6-luna",
            worker_effort="high",
            sandbox="workspace-write",
            final_review=False,
            plan_review=False,
            approval_required=False,
            estimated_credits=3.0,
            worker_protocol="luna-forge",
            worker_skill="luna-forge",
            worker_skill_version="2.2.1",
            worker_skill_repository="https://github.com/RealAhmedOsama/Luna-Forge.git",
            worker_skill_ref="ff37273ba761195ef5ab338d2e90ef3408ce8d8c",
            worker_skill_commit="ff37273ba761195ef5ab338d2e90ef3408ce8d8c",
        )
        task = TaskRecord(
            plan=plan,
            route=route,
            status=TaskStatus.ACCEPTED,
            source_commit_sha=self.head,
            applied_commit_sha=self.head,
            verification_results=[CommandResult("git diff --check", 0, 0.01, True)],
            runtime_attestations=[
                RuntimeAttestation(
                    requested_model="gpt-5.6-luna",
                    requested_effort="high",
                    requested_sandbox="workspace-write",
                    observed_model="gpt-5.6-luna",
                    observed_effort="high",
                    observed_sandbox="workspace-write",
                    source="codex-event",
                    verified=True,
                )
            ],
            credits=1.25,
        )
        return RunRecord(
            run_id="run-report-test",
            goal="Create a public report",
            repo=str(self.repo),
            profile="balanced",
            status=RunStatus.COMPLETED,
            base_commit=self.head,
            current_commit=self.head,
            tasks=[task],
            budget_credits=10.0,
            actual_credits=1.25,
        )

    def test_report_is_english_escaped_and_records_route_provenance(self) -> None:
        record = self.record(title="<script>alert('x')</script>")
        json_path, html_path = ReportGenerator(self.state).generate(record)
        self.assertTrue(json_path.is_file())
        html = html_path.read_text(encoding="utf-8")
        self.assertIn('lang="en"', html)
        self.assertIn("Worker source", html)
        self.assertIn("RealAhmedOsama/Luna-Forge.git@ff37273ba761", html)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;alert", html)

    def test_run_verifier_accepts_complete_pinned_luna_evidence(self) -> None:
        result = RunVerifier().verify(self.record())
        self.assertTrue(result["valid"], result["findings"])
        self.assertEqual([], result["findings"])

    def test_run_verifier_rejects_floating_luna_ref(self) -> None:
        record = self.record()
        record.tasks[0].route.worker_skill_ref = "main"
        result = RunVerifier().verify(record)
        self.assertFalse(result["valid"])
        self.assertTrue(any("exact commit" in item for item in result["findings"]))


if __name__ == "__main__":
    unittest.main()
