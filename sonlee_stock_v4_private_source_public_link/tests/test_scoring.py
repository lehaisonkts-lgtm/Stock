import unittest

import pandas as pd

from src.config import ScreeningConfig
from src.scoring import evaluate_candidate, score_dataframe


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.config = ScreeningConfig()
        self.good = {
            "ticker": "TEST",
            "theme_score": 9,
            "decline_flag": False,
            "state_control_pct": 0.68,
            "roe_3y_median": 0.20,
            "officer_ownership_pct": 0.08,
            "core_focus_score": 9,
            "governance_score": 8,
            "hidden_asset_score": 8,
            "revenue_growth_yoy": 0.18,
            "profit_growth_yoy": 0.22,
            "annual_margin": 0.42,
            "industry_margin_benchmark": 0.32,
            "dividend_years_paid": 5,
            "dividend_yield": 0.05,
        }

    def test_good_candidate_passes(self):
        result = evaluate_candidate(self.good, self.config)
        self.assertTrue(result["pass_hard_filter"])
        self.assertGreater(result["total_score"], 60)

    def test_state_must_be_strictly_above_50(self):
        row = dict(self.good)
        row["state_control_pct"] = 0.50
        result = evaluate_candidate(row, self.config)
        self.assertFalse(result["C2_nha_nuoc_chi_phoi"])
        self.assertFalse(result["pass_hard_filter"])

    def test_margin_must_beat_industry(self):
        row = dict(self.good)
        row["annual_margin"] = 0.31
        row["industry_margin_benchmark"] = 0.35
        result = evaluate_candidate(row, self.config)
        self.assertFalse(result["C5_tang_truong_bien_loi_nhuan"])

    def test_dataframe_sorting(self):
        weak = dict(self.good)
        weak["ticker"] = "WEAK"
        weak["state_control_pct"] = 0.40
        df = score_dataframe(pd.DataFrame([weak, self.good]), self.config)
        self.assertEqual(df.iloc[0]["ticker"], "TEST")
        self.assertTrue(bool(df.iloc[0]["pass_hard_filter"]))


if __name__ == "__main__":
    unittest.main()
