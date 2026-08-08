from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from codex_armada.config import load_config
from codex_armada.domain import RiskLevel, TaskKind, TaskPlan
from codex_armada.errors import LunaForgeError
from codex_armada.git import GitRepository
from codex_armada.luna_forge import LunaForgeManager
from codex_armada.prompts import PromptBuilder
from codex_armada.routing import Router
from tests.helpers import create_fake_luna_forge, initialize_repo, run, write_test_config


class LunaForgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.upstream, self.commit = create_fake_luna_forge(self.root / "upstream")
        self.repo = self.root / "repo"
        initialize_repo(self.repo)
        self.config_path = write_test_config(
            self.root / "armada.toml",
            repository=self.upstream,
            commit=self.commit,
            cache_dir=self.root / "cache",
        )
        self.config = load_config(self.repo, config_path=self.config_path)
        self.manager = LunaForgeManager(self.config)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_fetch_install_is_idempotent_and_git_clean(self) -> None:
        path, fetched = self.manager.fetch_source()
        self.assertTrue(fetched)
        self.assertEqual(self.commit, path.name)
        first = self.manager.ensure_project_install(self.repo)
        second = self.manager.ensure_project_install(self.repo)
        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertTrue(second.status.source_valid)
        self.assertTrue(second.status.installed)
        self.assertEqual(self.commit, second.status.resolved_commit)
        self.assertEqual("2.2.1", second.status.source_version)
        self.assertEqual([], GitRepository(self.repo).changed_files())
        self.assertTrue((self.repo / ".agents/skills/luna-forge/SKILL.md").is_file())
        self.assertTrue((self.repo / ".codex/agents/luna-worker.toml").is_file())

    def test_conflict_is_refused_and_force_backs_up_then_repairs(self) -> None:
        self.manager.ensure_project_install(self.repo)
        skill = self.repo / ".agents/skills/luna-forge/SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\nmodified\n", encoding="utf-8")
        with self.assertRaises(LunaForgeError):
            self.manager.ensure_project_install(self.repo)
        result = self.manager.ensure_project_install(self.repo, force=True)
        self.assertTrue(result.changed)
        self.assertTrue(result.backed_up)
        self.assertTrue(result.status.installed)
        self.assertEqual([], GitRepository(self.repo).changed_files())
        backups = list((self.repo / ".luna-forge-backups").rglob("SKILL.md"))
        self.assertEqual(1, len(backups))
        self.assertIn("modified", backups[0].read_text(encoding="utf-8"))

    def test_cached_manifest_tamper_fails_closed(self) -> None:
        checkout, _ = self.manager.fetch_source()
        target = checkout / "skill/luna-forge/SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
        status = self.manager.inspect(self.repo)
        self.assertFalse(status.source_valid)
        self.assertTrue(any("modified" in item.lower() or "integrity" in item.lower() for item in status.warnings))
        with self.assertRaises(LunaForgeError):
            self.manager.ensure_project_install(self.repo)

    def test_wrong_expected_commit_is_rejected(self) -> None:
        bad_path = write_test_config(
            self.root / "bad.toml",
            repository=self.upstream,
            commit="0" * 40,
            cache_dir=self.root / "bad-cache",
        )
        manager = LunaForgeManager(load_config(self.repo, config_path=bad_path))
        with self.assertRaises(LunaForgeError):
            manager.fetch_source()

    def test_require_unchanged_detects_hidden_skill_mutation(self) -> None:
        baseline = self.manager.ensure_project_install(self.repo).status
        skill = self.repo / ".agents/skills/luna-forge/SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\nunauthorized\n", encoding="utf-8")
        with self.assertRaises(LunaForgeError):
            self.manager.require_unchanged(self.repo, baseline, actor="test worker")

    @unittest.skipIf(os.name == "nt", "Symlink creation may require elevated Windows privileges")
    def test_symlinked_destination_parent_is_refused(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        os.symlink(outside, self.repo / ".agents")
        with self.assertRaises(LunaForgeError):
            self.manager.ensure_project_install(self.repo)

    @unittest.skipIf(os.name == "nt", "Symlink creation may require elevated Windows privileges")
    def test_symlinked_cache_checkout_is_refused(self) -> None:
        cache = self.root / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        os.symlink(self.upstream, cache / self.commit, target_is_directory=True)
        with self.assertRaises(LunaForgeError):
            self.manager.fetch_source()

    def test_manifest_rejects_windows_drive_and_parent_components(self) -> None:
        root = self.root / "unsafe-manifest"
        root.mkdir()
        outside = self.root / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        (root / "MANIFEST.sha256").write_text(
            "0" * 64 + "  C:/outside.txt\n",
            encoding="utf-8",
        )
        with self.assertRaises(LunaForgeError):
            self.manager._verify_manifest(root)

    def test_manifest_accepts_tracked_unmanifested_files_as_package_scoped(self) -> None:
        verify_file = self.upstream / "VERIFY-GIT.cmd"
        verify_file.write_text("echo verify git\n", encoding="utf-8")
        run(["git", "add", "VERIFY-GIT.cmd"], cwd=self.upstream, check=True)
        run(["git", "commit", "-q", "-m", "chore: add verify wrapper"], cwd=self.upstream, check=True)
        commit = run(["git", "rev-parse", "HEAD"], cwd=self.upstream).stdout.strip().lower()
        config_path = write_test_config(
            self.root / "tracked-only.toml",
            repository=self.upstream,
            commit=commit,
            cache_dir=self.root / "tracked-cache",
        )
        manager = LunaForgeManager(load_config(self.repo, config_path=config_path))
        _, fetched = manager.fetch_source()
        self.assertTrue(fetched)
        manifest = manager._verify_manifest(self.upstream)
        self.assertEqual("package", manifest["mode"])
        self.assertIn("VERIFY-GIT.cmd", manifest["unmanifested"])
        status = manager.inspect(self.repo)
        self.assertTrue(status.source_valid)

    def test_route_and_prompt_record_upstream_provenance(self) -> None:
        task = TaskPlan(
            "docs",
            "Update docs",
            "Create a bounded documentation change",
            TaskKind.DOCUMENTATION,
            ["docs/**"],
            risk=RiskLevel.LOW,
        )
        route = Router(self.config).route(task)
        self.assertEqual(str(self.upstream), route.worker_skill_repository)
        self.assertEqual(self.commit, route.worker_skill_ref)
        self.assertEqual(self.commit, route.worker_skill_commit)
        prompt = PromptBuilder().worker(
            run_id="run-12345678",
            task=task,
            base_commit="a" * 40,
            approved=False,
            route=route,
        )
        self.assertTrue(prompt.startswith("$luna-forge"))
        self.assertIn(self.commit, prompt)
        self.assertIn(str(self.upstream), prompt)
        self.assertIn("TASK CAPSULE", prompt)


if __name__ == "__main__":
    unittest.main()
