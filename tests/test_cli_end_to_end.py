from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from codex_armada.git import GitRepository
from tests.helpers import (
    configure_repo_for_fake_forge,
    create_fake_luna_forge,
    initialize_repo,
    run_cli,
    test_environment,
    write_test_config,
)


class CliEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_root = Path(__file__).resolve().parents[1]
        cls.fixture_root = tempfile.TemporaryDirectory()
        cls.upstream, cls.upstream_commit = create_fake_luna_forge(Path(cls.fixture_root.name) / "upstream")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture_root.cleanup()

    def _repo(self, root: Path) -> tuple[Path, dict[str, str]]:
        repo = root / "repo"
        initialize_repo(repo)
        configure_repo_for_fake_forge(
            repo,
            repository=self.upstream,
            commit=self.upstream_commit,
            cache_dir=Path(self.fixture_root.name) / "shared-cache",
        )
        env = test_environment(self.project_root, root / "state", Path(self.fixture_root.name) / "shared-cache-env")
        return repo, env

    @staticmethod
    def _plan(path: Path, *, risk: str = "medium", kind: str = "implementation", owned: str = "generated.txt") -> Path:
        plan = {
            "goal": f"Create {owned}",
            "summary": "One bounded task",
            "assumptions": [],
            "acceptance_criteria": [f"{owned} is created and verified"],
            "tasks": [
                {
                    "id": "create-file",
                    "title": "Create generated fixture",
                    "objective": f"Create {owned}",
                    "kind": kind,
                    "owned_paths": [owned],
                    "excluded_paths": [],
                    "interfaces": [],
                    "constraints": ["Do not modify another file."],
                    "verification": [
                        {"command": "git diff --check", "success": "exit code 0", "timeout_seconds": None}
                    ],
                    "depends_on": [],
                    "risk": risk,
                    "tags": ["fixture"],
                    "allow_deletions": False,
                    "allow_production_changes": False,
                    "commit_message": "feat(fixture): create generated fixture",
                }
            ],
        }
        target = path / f"plan-{risk}-{kind}.json"
        target.write_text(json.dumps(plan), encoding="utf-8")
        return target

    def test_init_uses_external_pinned_source_and_keeps_repository_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            initialize_repo(repo)
            config = write_test_config(
                root / "fixture.toml",
                repository=self.upstream,
                commit=self.upstream_commit,
                cache_dir=Path(self.fixture_root.name) / "shared-cache",
            )
            env = test_environment(self.project_root, root / "state")
            result = run_cli(
                self.project_root,
                env,
                "--repo",
                str(repo),
                "--config",
                str(config),
                "init",
            )
            self.assertEqual(0, result.returncode, msg=result.stdout + result.stderr)
            self.assertTrue((repo / ".codex-armada.toml").is_file())
            self.assertTrue((repo / ".agents/skills/luna-forge/SKILL.md").is_file())
            self.assertTrue((repo / ".codex/agents/luna-worker.toml").is_file())
            self.assertEqual([], GitRepository(repo).changed_files())

    def test_doctor_can_fail_read_only_then_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            read_only = run_cli(self.project_root, env, "--repo", str(repo), "doctor", "--no-auto-install")
            self.assertEqual(2, read_only.returncode, msg=read_only.stdout + read_only.stderr)
            self.assertFalse((repo / ".agents/skills/luna-forge/SKILL.md").exists())
            repaired = run_cli(self.project_root, env, "--repo", str(repo), "doctor", "--repair-luna-forge")
            self.assertEqual(0, repaired.returncode, msg=repaired.stdout + repaired.stderr)
            self.assertTrue((repo / ".agents/skills/luna-forge/SKILL.md").is_file())
            self.assertEqual([], GitRepository(repo).changed_files())

    def test_plan_run_commit_report_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            result = run_cli(self.project_root, env, "--repo", str(repo), "run", "Create generated.txt")
            self.assertEqual(0, result.returncode, msg=result.stdout + result.stderr)
            self.assertTrue((repo / "generated.txt").is_file())
            self.assertEqual([], GitRepository(repo).changed_files())
            status = run_cli(self.project_root, env, "--repo", str(repo), "--json", "status", "--all")
            self.assertEqual(0, status.returncode, msg=status.stdout + status.stderr)
            records = json.loads(status.stdout)
            self.assertEqual("completed", records[0]["status"])
            run_id = records[0]["run_id"]
            verification = run_cli(self.project_root, env, "--repo", str(repo), "verify", run_id)
            self.assertEqual(0, verification.returncode, msg=verification.stdout + verification.stderr)
            report = run_cli(self.project_root, env, "--repo", str(repo), "--json", "report", run_id)
            payload = json.loads(report.stdout)
            self.assertTrue(Path(payload["html"]).is_file())
            self.assertTrue(Path(payload["json"]).is_file())

    def test_low_risk_task_invokes_luna_forge_with_pinned_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            plan = self._plan(root, risk="low", kind="documentation", owned="docs/generated.txt")
            capture = root / "prompts.jsonl"
            env["FAKE_CODEX_CAPTURE_PROMPTS"] = str(capture)
            result = run_cli(
                self.project_root,
                env,
                "--repo",
                str(repo),
                "run",
                "Create documentation fixture",
                "--plan-file",
                str(plan),
            )
            self.assertEqual(0, result.returncode, msg=result.stdout + result.stderr)
            prompts = [json.loads(line) for line in capture.read_text(encoding="utf-8").splitlines()]
            forge_calls = [item for item in prompts if item["prompt"].startswith("$luna-forge")]
            self.assertEqual(1, len(forge_calls), prompts)
            self.assertEqual("gpt-5.6-luna", forge_calls[0]["model"])
            self.assertEqual("high", forge_calls[0]["effort"])
            self.assertIn(self.upstream_commit, forge_calls[0]["prompt"])
            self.assertIn("TASK CAPSULE", forge_calls[0]["prompt"])

    def test_critical_task_waits_for_approval_then_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            plan = self._plan(root, risk="critical", kind="migration", owned="migration.txt")
            first = run_cli(
                self.project_root,
                env,
                "--repo",
                str(repo),
                "run",
                "Create migration fixture",
                "--plan-file",
                str(plan),
            )
            self.assertEqual(3, first.returncode, msg=first.stdout + first.stderr)
            status = run_cli(self.project_root, env, "--repo", str(repo), "--json", "status", "--all")
            run_id = json.loads(status.stdout)[0]["run_id"]
            resumed = run_cli(
                self.project_root,
                env,
                "--repo",
                str(repo),
                "resume",
                run_id,
                "--approve",
                "create-file",
            )
            self.assertEqual(0, resumed.returncode, msg=resumed.stdout + resumed.stderr)
            self.assertTrue((repo / "migration.txt").is_file())

    def test_scope_violation_isolated_from_main(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            env["FAKE_CODEX_SCOPE_VIOLATION"] = "1"
            before = GitRepository(repo).head()
            result = run_cli(self.project_root, env, "--repo", str(repo), "run", "Create generated.txt")
            self.assertEqual(4, result.returncode, msg=result.stdout + result.stderr)
            self.assertEqual(before, GitRepository(repo).head())
            self.assertFalse((repo / "generated.txt").exists())
            self.assertFalse((repo / "outside.txt").exists())

    @unittest.skipIf(os.name == "nt", "Symlink creation may require elevated Windows privileges")
    def test_symlink_change_isolated_from_main(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            env["FAKE_CODEX_SYMLINK"] = "1"
            result = run_cli(self.project_root, env, "--repo", str(repo), "run", "Create generated.txt")
            self.assertEqual(4, result.returncode, msg=result.stdout + result.stderr)
            self.assertFalse((repo / "generated.txt").exists())

    def test_worker_model_mismatch_blocks_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            plan = self._plan(root, risk="medium")
            env["FAKE_CODEX_OBSERVED_MODEL"] = "gpt-5.6-sol"
            before = GitRepository(repo).head()
            result = run_cli(
                self.project_root,
                env,
                "--repo",
                str(repo),
                "run",
                "Create fixture",
                "--plan-file",
                str(plan),
            )
            self.assertEqual(4, result.returncode, msg=result.stdout + result.stderr)
            self.assertEqual(before, GitRepository(repo).head())
            self.assertFalse((repo / "generated.txt").exists())

    def test_invalid_structured_output_is_rejected_locally(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            plan = self._plan(root, risk="medium")
            env["FAKE_CODEX_INVALID_SCHEMA"] = "1"
            result = run_cli(
                self.project_root,
                env,
                "--repo",
                str(repo),
                "run",
                "Create fixture",
                "--plan-file",
                str(plan),
            )
            self.assertEqual(4, result.returncode, msg=result.stdout + result.stderr)
            self.assertFalse((repo / "generated.txt").exists())
            errors = list((root / "state").rglob("*.schema-errors.json"))
            self.assertTrue(errors)

    def test_hidden_luna_forge_mutation_blocks_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            plan = self._plan(root, risk="low", kind="documentation", owned="docs/generated.txt")
            env["FAKE_CODEX_FORGE_MUTATION"] = "1"
            before = GitRepository(repo).head()
            result = run_cli(
                self.project_root,
                env,
                "--repo",
                str(repo),
                "run",
                "Create docs fixture",
                "--plan-file",
                str(plan),
            )
            self.assertEqual(4, result.returncode, msg=result.stdout + result.stderr)
            self.assertEqual(before, GitRepository(repo).head())
            self.assertFalse((repo / "docs/generated.txt").exists())

    def test_read_only_reviewer_mutation_blocks_high_risk_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            plan = self._plan(root, risk="high", kind="security", owned="src/Auth/generated.txt")
            env["FAKE_CODEX_REVIEW_MUTATION"] = "1"
            before = GitRepository(repo).head()
            result = run_cli(
                self.project_root,
                env,
                "--repo",
                str(repo),
                "run",
                "Create security fixture",
                "--plan-file",
                str(plan),
            )
            self.assertEqual(4, result.returncode, msg=result.stdout + result.stderr)
            self.assertEqual(before, GitRepository(repo).head())
            self.assertFalse((repo / "src/Auth/generated.txt").exists())

    def test_project_config_can_disable_task_commits_for_one_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            overlay = repo / ".codex-armada.toml"
            original = overlay.read_text(encoding="utf-8")
            overlay.write_text(
                original.replace(
                    "version = 1\n",
                    "version = 1\ncommit_per_task = false\nuse_isolated_worktrees = false\n",
                    1,
                ),
                encoding="utf-8",
            )
            before = GitRepository(repo).head()
            plan = self._plan(root, risk="medium")
            result = run_cli(
                self.project_root,
                env,
                "--repo",
                str(repo),
                "run",
                "Create fixture",
                "--plan-file",
                str(plan),
            )
            self.assertEqual(0, result.returncode, msg=result.stdout + result.stderr)
            self.assertTrue((repo / "generated.txt").is_file())
            self.assertEqual(before, GitRepository(repo).head())

    def test_canary_uses_explicit_model_and_effort(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            result = run_cli(
                self.project_root,
                env,
                "--repo",
                str(repo),
                "--json",
                "canary",
                "--model",
                "terra",
                "--effort",
                "xhigh",
            )
            self.assertEqual(0, result.returncode, msg=result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("gpt-5.6-terra", payload["model"])
            self.assertEqual("xhigh", payload["effort"])
            self.assertEqual("xhigh", payload["attestation"]["observed_effort"])

    def test_luna_canary_uses_luna_forge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, env = self._repo(root)
            result = run_cli(
                self.project_root,
                env,
                "--repo",
                str(repo),
                "--json",
                "canary",
                "--model",
                "luna",
            )
            self.assertEqual(0, result.returncode, msg=result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("luna-forge", payload["worker_protocol"])
            self.assertEqual("high", payload["effort"])
            self.assertTrue(payload["luna_forge"]["source_valid"])


if __name__ == "__main__":
    unittest.main()
