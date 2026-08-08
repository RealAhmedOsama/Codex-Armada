from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codex_armada.config import load_config
from codex_armada.costs import CostCalculator
from codex_armada.jsonl import observed_runtime, parse_jsonl_text, thread_id, token_usage


class JsonlCostTests(unittest.TestCase):
    def test_extracts_runtime_usage_and_cost(self) -> None:
        events = parse_jsonl_text(
            '{"type":"thread.started","thread_id":"abc-12345678"}\n'
            '{"type":"turn.completed","model":"gpt-5.6-luna","effort":"high",'
            '"sandbox_mode":"workspace-write","usage":{"input_tokens":1000000,'
            '"cached_input_tokens":500000,"output_tokens":1000000,'
            '"reasoning_output_tokens":250000}}\n'
        )
        self.assertEqual("abc-12345678", thread_id(events))
        self.assertEqual("gpt-5.6-luna", observed_runtime(events)["model"])
        usage = token_usage(events)
        self.assertEqual(250000, usage.reasoning_output_tokens)
        # Current Codex reports reasoning as a detail alongside output tokens;
        # output-token pricing therefore uses output_tokens without double counting.
        self.assertEqual(2000000, usage.total_tokens)
        with tempfile.TemporaryDirectory() as temporary:
            calculation = CostCalculator(load_config(Path(temporary))).calculate("gpt-5.6-luna", usage)
        self.assertAlmostEqual(163.75, calculation.credits)


if __name__ == "__main__":
    unittest.main()
