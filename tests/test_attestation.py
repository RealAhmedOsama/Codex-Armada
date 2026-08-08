from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_armada.attestation import build_attestation


class AttestationTests(unittest.TestCase):
    def test_verified_event_attestation(self) -> None:
        events = [{
            "type": "turn.completed",
            "model": "gpt-5.6-terra",
            "effort": "high",
            "sandbox_mode": "workspace-write",
        }]
        result = build_attestation(
            events=events,
            requested_model="gpt-5.6-terra",
            requested_effort="high",
            requested_sandbox="workspace-write",
            thread_id=None,
        )
        self.assertTrue(result.verified)
        self.assertIsNone(result.mismatch)

    def test_model_mismatch_fails(self) -> None:
        events = [{
            "type": "turn.completed",
            "model": "gpt-5.6-sol",
            "effort": "high",
            "sandbox_mode": "workspace-write",
        }]
        result = build_attestation(
            events=events,
            requested_model="gpt-5.6-terra",
            requested_effort="high",
            requested_sandbox="workspace-write",
            thread_id=None,
        )
        self.assertFalse(result.verified)
        self.assertIn("model", result.mismatch or "")

    def test_current_exec_events_use_exact_rollout_for_runtime_attestation(self) -> None:
        thread_id = "11111111-1111-4111-8111-111111111111"
        events = [
            {"type": "thread.started", "thread_id": thread_id},
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 20,
                    "output_tokens": 30,
                    "reasoning_output_tokens": 10,
                },
            },
        ]
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary)
            rollout_dir = codex_home / "sessions" / "2026" / "08" / "05"
            rollout_dir.mkdir(parents=True)
            rollout = rollout_dir / f"rollout-2026-08-05T00-00-00-{thread_id}.jsonl"
            rollout.write_text(
                "\n".join(
                    json.dumps(item)
                    for item in (
                        {"type": "session_meta", "payload": {"id": thread_id}},
                        {
                            "type": "turn_context",
                            "payload": {
                                "model": "gpt-5.6-luna",
                                "effort": "high",
                                "sandbox_policy": {"type": "workspace-write"},
                                "permission_profile": {"type": "restricted"},
                            },
                        },
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                result = build_attestation(
                    events=events,
                    requested_model="gpt-5.6-luna",
                    requested_effort="high",
                    requested_sandbox="workspace-write",
                    thread_id=thread_id,
                )
        self.assertTrue(result.verified)
        self.assertEqual("rollout", result.source)
        self.assertEqual("restricted", result.permission_profile)


    def test_rollout_fills_missing_sandbox_without_overwriting_event_route(self) -> None:
        thread_id = "33333333-3333-4333-8333-333333333333"
        events = [
            {"type": "thread.started", "thread_id": thread_id},
            {"type": "turn.completed", "model": "gpt-5.6-terra", "effort": "high"},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary)
            rollout_dir = codex_home / "sessions" / "2026" / "08" / "05"
            rollout_dir.mkdir(parents=True)
            (rollout_dir / f"rollout-2026-08-05T00-00-00-{thread_id}.jsonl").write_text(
                json.dumps(
                    {
                        "type": "turn_context",
                        "payload": {
                            "model": "gpt-5.6-terra",
                            "effort": "high",
                            "sandbox_policy": {"type": "workspace-write"},
                            "permission_profile": {"type": "restricted"},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                result = build_attestation(
                    events=events,
                    requested_model="gpt-5.6-terra",
                    requested_effort="high",
                    requested_sandbox="workspace-write",
                    thread_id=thread_id,
                )
        self.assertTrue(result.verified)
        self.assertEqual("events+rollout", result.source)
        self.assertEqual("workspace-write", result.observed_sandbox)
        self.assertEqual("restricted", result.permission_profile)

    def test_conflicting_event_and_rollout_routes_fail_closed(self) -> None:
        thread_id = "44444444-4444-4444-8444-444444444444"
        events = [
            {"type": "thread.started", "thread_id": thread_id},
            {"type": "turn.completed", "model": "gpt-5.6-terra", "effort": "high"},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary)
            rollout_dir = codex_home / "sessions" / "2026" / "08" / "05"
            rollout_dir.mkdir(parents=True)
            (rollout_dir / f"rollout-2026-08-05T00-00-00-{thread_id}.jsonl").write_text(
                json.dumps(
                    {
                        "type": "turn_context",
                        "payload": {
                            "model": "gpt-5.6-luna",
                            "effort": "high",
                            "sandbox_policy": {"type": "workspace-write"},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                result = build_attestation(
                    events=events,
                    requested_model="gpt-5.6-terra",
                    requested_effort="high",
                    requested_sandbox="workspace-write",
                    thread_id=thread_id,
                )
        self.assertFalse(result.verified)
        self.assertEqual("gpt-5.6-terra", result.observed_model)
        self.assertIn("runtime evidence conflict for model", result.mismatch or "")

    def test_ambiguous_rollout_files_fail_closed(self) -> None:
        thread_id = "22222222-2222-4222-8222-222222222222"
        events = [{"type": "thread.started", "thread_id": thread_id}]
        with tempfile.TemporaryDirectory() as temporary:
            codex_home = Path(temporary)
            for day in ("05", "06"):
                directory = codex_home / "sessions" / "2026" / "08" / day
                directory.mkdir(parents=True)
                (directory / f"rollout-2026-08-{day}T00-00-00-{thread_id}.jsonl").write_text(
                    json.dumps(
                        {
                            "type": "turn_context",
                            "payload": {"model": "gpt-5.6-luna", "effort": "high"},
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                result = build_attestation(
                    events=events,
                    requested_model="gpt-5.6-luna",
                    requested_effort="high",
                    requested_sandbox="workspace-write",
                    thread_id=thread_id,
                )
        self.assertFalse(result.verified)
        self.assertEqual("requested-only", result.source)


if __name__ == "__main__":
    unittest.main()
