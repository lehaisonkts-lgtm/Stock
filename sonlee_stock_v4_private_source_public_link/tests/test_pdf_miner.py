import unittest

from src.pdf_miner import analyze_hidden_assets_pages, hidden_asset_score


class PdfMinerTests(unittest.TestCase):
    def test_flags_land_and_investment(self):
        pages = [
            {
                "page": 12,
                "text": "Quyền sử dụng đất được ghi nhận theo nguyên giá 1.200 tỷ đồng. Công ty có đầu tư vào công ty con theo giá gốc.",
            }
        ]
        findings = analyze_hidden_assets_pages(pages)
        self.assertGreaterEqual(len(findings), 2)
        self.assertGreater(hidden_asset_score(findings), 0)


if __name__ == "__main__":
    unittest.main()
