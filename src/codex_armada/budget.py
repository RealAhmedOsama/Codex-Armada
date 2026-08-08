from __future__ import annotations

from .errors import BudgetError


class BudgetGovernor:
    def __init__(self, limit: float | None) -> None:
        self.limit = limit

    def ensure_capacity(self, *, actual: float, expected_next: float, label: str) -> None:
        if self.limit is None:
            return
        projected = actual + max(0.0, expected_next)
        if projected > self.limit:
            raise BudgetError(
                f"Credit budget blocks {label}: actual={actual:.3f}, expected_next={expected_next:.3f}, "
                f"limit={self.limit:.3f}"
            )
