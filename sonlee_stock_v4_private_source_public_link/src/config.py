from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScreeningConfig:
    # User's hard gates
    state_control_min: float = 0.50  # strict rule is > 50%, not >=
    tailwind_min_score: float = 7.0
    hidden_asset_min_score: float = 5.0
    quarterly_growth_min: float = 0.10
    annual_margin_min: float = 0.30
    growth_metric: str = "profit"  # profit | revenue | both
    margin_kind: str = "gross"  # gross | net
    require_industry_outperformance: bool = True
    require_hidden_asset_gate: bool = True

    # Scoring weights add to 100
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "tailwind": 20.0,
            "state_control": 15.0,
            "management": 20.0,
            "hidden_assets": 15.0,
            "growth_profitability": 20.0,
            "dividend": 10.0,
        }
    )

    dividend_lookback_years: int = 5

    def validate(self) -> None:
        total = sum(self.weights.values())
        if abs(total - 100.0) > 1e-6:
            raise ValueError(f"Weights must sum to 100, got {total}")
        if self.growth_metric not in {"profit", "revenue", "both"}:
            raise ValueError("growth_metric must be profit, revenue or both")
        if self.margin_kind not in {"gross", "net"}:
            raise ValueError("margin_kind must be gross or net")
