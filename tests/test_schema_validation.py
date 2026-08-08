from __future__ import annotations

import json
import unittest
from pathlib import Path

from codex_armada.schema_validation import validate_json_schema


class SchemaValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas = Path(__file__).resolve().parents[1] / "src" / "codex_armada" / "resources" / "schemas"

    def test_accepts_valid_canary(self) -> None:
        schema = json.loads((self.schemas / "canary.schema.json").read_text(encoding="utf-8"))
        self.assertEqual([], validate_json_schema({"status": "ok", "message": "ready"}, schema))

    def test_rejects_missing_and_additional_properties(self) -> None:
        schema = json.loads((self.schemas / "canary.schema.json").read_text(encoding="utf-8"))
        errors = validate_json_schema({"status": "ok", "extra": True}, schema)
        self.assertTrue(any("missing required property 'message'" in item for item in errors), errors)
        self.assertTrue(any("unexpected property 'extra'" in item for item in errors), errors)

    def test_rejects_nested_invalid_plan(self) -> None:
        schema = json.loads((self.schemas / "plan.schema.json").read_text(encoding="utf-8"))
        invalid = {
            "goal": "x",
            "summary": "x",
            "assumptions": [],
            "acceptance_criteria": ["done"],
            "tasks": [{"id": "Bad ID"}],
        }
        errors = validate_json_schema(invalid, schema)
        self.assertTrue(any("tasks[0]" in item for item in errors), errors)
        self.assertTrue(any("does not match" in item for item in errors), errors)


if __name__ == "__main__":
    unittest.main()
