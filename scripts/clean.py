from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for pattern in ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "build", "dist"):
    for path in ROOT.rglob(pattern):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
for path in ROOT.rglob("*.egg-info"):
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
for path in ROOT.rglob("*.py[co]"):
    path.unlink(missing_ok=True)
print("Cleaned generated development artifacts.")
