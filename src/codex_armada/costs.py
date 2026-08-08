from __future__ import annotations

from dataclasses import dataclass

from .config import AppConfig
from .domain import TokenUsage


@dataclass(slots=True)
class CostCalculation:
    credits: float
    source: str


class CostCalculator:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def calculate(self, model: str, usage: TokenUsage) -> CostCalculation:
        rate = self.config.credit_rates.get(model)
        if usage.total_tokens == 0 and usage.cached_input_tokens == 0:
            return CostCalculation(
                credits=rate.typical_task_credits if rate else 0.0,
                source="estimated-typical-task",
            )
        if not rate:
            return CostCalculation(credits=0.0, source="unpriced-token-usage")
        uncached_input = max(0, usage.input_tokens - usage.cached_input_tokens)
        credits = (
            uncached_input * rate.input_per_million
            + usage.cached_input_tokens * rate.cached_input_per_million
            + usage.output_tokens * rate.output_per_million
        ) / 1_000_000
        return CostCalculation(credits=round(credits, 6), source="observed-token-usage")

    def typical(self, model: str) -> float:
        rate = self.config.credit_rates.get(model)
        return rate.typical_task_credits if rate else 0.0
