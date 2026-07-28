import unittest
import re
from pathlib import Path

import app as app_module


ROOT = Path(__file__).resolve().parent.parent


class ValuationToolUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app_module.app.test_client()

    def test_rendered_page_has_public_full_width_comparable_grid(self):
        response = self.client.get("/dinh-gia-bds")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        hero = html.index('class="hero-band"')
        workspace = html.index("valuation-workspace")
        method = html.index("valuation-method-heading")
        faq = html.index('id="faq"')
        self.assertLess(hero, workspace)
        self.assertLess(workspace, method)
        self.assertLess(method, faq)
        self.assertNotIn('name="tho_cu_m2"', html)
        self.assertIn('name="price_ty"', html)
        self.assertIn('id="comparablesSection"', html)
        self.assertIn('id="comparableList"', html)
        self.assertNotIn('id="comparablesLock"', html)
        self.assertNotIn('id="unlockComparablesBtn"', html)
        self.assertIn("css/main/cards.css", html)
        self.assertIn("js/valuation_comparable_card.js", html)
        self.assertIn('id="dashboardCta"', html)

    def test_javascript_contains_all_funnel_events_and_localized_result_fields(self):
        javascript = (ROOT / "static" / "js" / "valuation_tool.js").read_text(encoding="utf-8")

        for event_name in (
            "valuation_start",
            "valuation_success",
            "valuation_error",
            "valuation_dashboard_click",
            "valuation_comparable_click",
        ):
            self.assertIn(event_name, javascript)
        self.assertNotIn("valuation_unlock_click", javascript)
        self.assertIn("confidence_label", javascript)
        self.assertIn("basis_count", javascript)
        self.assertIn("data_as_of", javascript)
        self.assertNotIn("estimate.note", javascript)
        self.assertNotIn("estimate.segment_n", javascript)

    def test_css_keeps_hidden_elements_hidden_and_has_no_order_override(self):
        stylesheet = (ROOT / "static" / "css" / "valuation_tool.css").read_text(encoding="utf-8")

        self.assertIn("[hidden]", stylesheet)
        self.assertIn("display: none !important", stylesheet)
        self.assertIsNone(re.search(r"(?m)^\s*order\s*:", stylesheet))


if __name__ == "__main__":
    unittest.main()
