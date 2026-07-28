import unittest
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class ValuationToolUiContractTest(unittest.TestCase):
    def test_page_order_and_trust_first_controls(self):
        template = (ROOT / "templates" / "valuation_tool.html").read_text(encoding="utf-8")

        hero = template.index('class="hero-band"')
        workspace = template.index("valuation-workspace")
        method = template.index("valuation-method-heading")
        faq = template.index('id="faq"')
        self.assertLess(hero, workspace)
        self.assertLess(workspace, method)
        self.assertLess(method, faq)
        self.assertNotIn('name="tho_cu_m2"', template)
        self.assertIn('name="price_ty"', template)
        self.assertIn('id="comparablesLock"', template)
        self.assertIn('id="dashboardCta"', template)

    def test_javascript_contains_all_funnel_events_and_localized_result_fields(self):
        javascript = (ROOT / "static" / "js" / "valuation_tool.js").read_text(encoding="utf-8")

        for event_name in (
            "valuation_start",
            "valuation_success",
            "valuation_error",
            "valuation_unlock_click",
            "valuation_dashboard_click",
        ):
            self.assertIn(event_name, javascript)
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
