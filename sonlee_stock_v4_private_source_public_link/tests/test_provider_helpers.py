import unittest

import pandas as pd

from src.data_provider import VnstockProvider


class ProviderHelperTests(unittest.TestCase):
    def test_state_control_from_summary(self):
        provider = object.__new__(VnstockProvider)
        provider.state_registry = pd.DataFrame(columns=["entity", "pattern"])
        summary = pd.DataFrame([{"state_percentage": 74.8}])
        result = provider._detect_state_control(summary, pd.DataFrame())
        self.assertAlmostEqual(result["state_control_pct"], 0.748)

    def test_state_control_from_state_parent(self):
        provider = object.__new__(VnstockProvider)
        provider.state_registry = pd.DataFrame([
            {"entity": "EVN", "pattern": "Tập đoàn Điện lực Việt Nam|EVN"}
        ])
        detailed = pd.DataFrame([
            {"name": "Tập đoàn Điện lực Việt Nam", "rate": 0.51}
        ])
        result = provider._detect_state_control(pd.DataFrame(), detailed)
        self.assertAlmostEqual(result["state_control_pct"], 0.51)

    def test_tailwind_false_flag_is_false(self):
        provider = object.__new__(VnstockProvider)
        provider.tailwind_rules = pd.DataFrame([
            {
                "priority": 1,
                "pattern": "Điện",
                "score": 9,
                "decline_flag": "FALSE",
                "theme": "Điện",
                "rationale": "test",
                "source": "test",
            }
        ])
        result = provider._tailwind_match("Điện", "Công ty A")
        self.assertFalse(result["decline_flag"])
        self.assertEqual(result["theme_score"], 9.0)


if __name__ == "__main__":
    unittest.main()
