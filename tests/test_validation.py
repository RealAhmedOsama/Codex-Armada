from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_armada.config import load_config
from codex_armada.domain import ExecutionPlan, RiskLevel, TaskKind, TaskPlan
from codex_armada.validation import PlanValidator


class PlanValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.config = load_config(Path(self.temporary.name))
        self.validator = PlanValidator(self.config)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_rejects_cycle(self) -> None:
        plan = ExecutionPlan(
            "goal", "summary", [],
            [
                TaskPlan("a1", "A", "A", TaskKind.IMPLEMENTATION, ["src/A/**"], depends_on=["b1"]),
                TaskPlan("b1", "B", "B", TaskKind.IMPLEMENTATION, ["src/B/**"], depends_on=["a1"]),
            ],
            ["done"],
        )
        errors = self.validator.validate_and_route(plan)
        self.assertTrue(any("cycle" in item.lower() for item in errors))

    def test_rejects_broad_ownership(self) -> None:
        plan = ExecutionPlan(
            "goal", "summary", [],
            [TaskPlan("task", "Task", "Task", TaskKind.IMPLEMENTATION, ["**"], risk=RiskLevel.MEDIUM)],
            ["done"],
        )
        errors = self.validator.validate_and_route(plan)
        self.assertTrue(any("broad" in item.lower() for item in errors))


    def test_rejects_absolute_and_parent_traversal_ownership(self) -> None:
        for owned in (["../outside.txt"], ["/etc/hosts"], ["C:\\Windows\\system.ini"]):
            with self.subTest(owned=owned):
                plan = ExecutionPlan(
                    "goal", "summary", [],
                    [TaskPlan("task", "Task", "Task", TaskKind.IMPLEMENTATION, owned, risk=RiskLevel.MEDIUM)],
                    ["done"],
                )
                errors = self.validator.validate_and_route(plan)
                self.assertTrue(any("unsafe owned paths" in item.lower() for item in errors), msg=errors)

    def test_allows_sequential_shared_ownership(self) -> None:
        plan = ExecutionPlan(
            "goal", "summary", [],
            [
                TaskPlan("a1", "A", "A", TaskKind.IMPLEMENTATION, ["src/Feature/**"]),
                TaskPlan("b1", "B", "B", TaskKind.TEST, ["src/Feature/**"], depends_on=["a1"]),
            ],
            ["done"],
        )
        errors = self.validator.validate_and_route(plan)
        self.assertFalse(any("overlapping" in item.lower() for item in errors))


if __name__ == "__main__":
    unittest.main()
