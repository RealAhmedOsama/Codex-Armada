from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_armada.config import load_config
from codex_armada.domain import RiskLevel, TaskKind, TaskPlan
from codex_armada.errors import ConfigurationError
from codex_armada.routing import Router


class ConfigRoutingTests(unittest.TestCase):
    def test_balanced_routes_low_to_luna_with_pinned_forge_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(Path(temporary))
            route = Router(config).route(
                TaskPlan("docs", "Docs", "Update docs", TaskKind.DOCUMENTATION, ["docs/**"], risk=RiskLevel.LOW)
            )
            self.assertEqual("luna", route.worker_alias)
            self.assertEqual("luna-forge", route.worker_protocol)
            self.assertEqual("2.2.1", route.worker_skill_version)
            self.assertEqual("https://github.com/RealAhmedOsama/Luna-Forge.git", route.worker_skill_repository)
            self.assertEqual("ff37273ba761195ef5ab338d2e90ef3408ce8d8c", route.worker_skill_commit)
            self.assertEqual("high", route.worker_effort)

    def test_balanced_routes_high_security_work_to_terra_and_sol_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(Path(temporary))
            task = TaskPlan(
                "auth", "Authorization", "Fix authorization", TaskKind.SECURITY, ["src/Auth/**"], risk=RiskLevel.MEDIUM
            )
            route = Router(config).route(task)
            self.assertEqual(RiskLevel.HIGH, task.risk)
            self.assertEqual("terra", route.worker_alias)
            self.assertTrue(route.final_review)
            self.assertFalse(route.approval_required)

    def test_generic_migration_rule_is_critical_and_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(Path(temporary))
            task = TaskPlan(
                "migration",
                "Add migration",
                "Create a database migration",
                TaskKind.MIGRATION,
                ["src/Data/Migrations/**"],
                risk=RiskLevel.MEDIUM,
            )
            route = Router(config).route(task)
            self.assertEqual(RiskLevel.CRITICAL, task.risk)
            self.assertEqual("sol", route.worker_alias)
            self.assertTrue(route.plan_review)
            self.assertTrue(route.final_review)
            self.assertTrue(route.approval_required)

    def test_unsupported_configuration_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            overlay = repo / "legacy.toml"
            overlay.write_text("version = 0\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_config(repo, config_path=overlay)


    def test_negative_budget_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            overlay = repo / "bad-budget.toml"
            overlay.write_text("version = 1\ndefault_budget_credits = -1\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_config(repo, config_path=overlay)

    def test_negative_credit_rate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            overlay = repo / "bad-rate.toml"
            overlay.write_text(
                'version = 1\n[credit_rates."gpt-5.6-luna"]\ninput_per_million = -1\n',
                encoding="utf-8",
            )
            with self.assertRaises(ConfigurationError):
                load_config(repo, config_path=overlay)

    def test_luna_forge_requires_full_lowercase_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            overlay = repo / "bad.toml"
            overlay.write_text('[luna_forge]\nexpected_commit = "abc"\n', encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                load_config(repo, config_path=overlay)

    def test_luna_forge_ref_must_equal_the_pinned_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            overlay = root / "invalid-ref.toml"
            overlay.write_text(
                "\n".join(
                    [
                        "version = 1",
                        "[luna_forge]",
                        'ref = "main"',
                    ]
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigurationError):
                load_config(repo, config_path=overlay)


if __name__ == "__main__":
    unittest.main()
