from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class ReleaseAutomationTests(unittest.TestCase):
    def test_release_workflow_builds_publishable_artifacts_without_legacy_verifier(self) -> None:
        release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
        workflows = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.yml"))
        )

        self.assertNotIn("python -m codex_armada version", release)
        self.assertNotIn("verify_release.py", workflows)
        self.assertIn("python -m pip wheel .", release)
        self.assertIn("scripts/build_release.py", release)
        self.assertIn("gh release create", release)


if __name__ == "__main__":
    unittest.main()
