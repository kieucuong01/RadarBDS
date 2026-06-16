import unittest

from services.market_data import keyword_search_filter


class KeywordSearchFilterTest(unittest.TestCase):
    def test_road_code_search_uses_compact_text(self):
        clauses, params = keyword_search_filter("DX44")

        self.assertEqual(params, ["%dx44%"])
        self.assertEqual(len(clauses), 1)
        self.assertIn("REPLACE(", clauses[0])

    def test_spaced_road_code_search_becomes_single_exact_token(self):
        _clauses, params = keyword_search_filter("DH 3A")

        self.assertEqual(params, ["%dh3a%"])

    def test_my_phuoc_shorthand_maps_to_area_phrase(self):
        _clauses, params = keyword_search_filter("MP3")

        self.assertEqual(params, ["%my phuoc 3%"])

    def test_generic_road_word_does_not_filter(self):
        clauses, params = keyword_search_filter("duong")

        self.assertEqual(clauses, [])
        self.assertEqual(params, [])

    def test_listing_content_search_uses_exact_words_and_money_unit_variants(self):
        clauses, params = keyword_search_filter("\u0110ang vay ng\u00e2n h\u00e0ng 2 t\u1ef7 5")

        self.assertEqual(
            params,
            ["% dang %", "% vay %", "% ngan %", "% hang %", "% 2 %", "% ty %", "% ti %", "% 5 %"],
        )
        self.assertEqual(len(clauses), 7)
        self.assertIn(" OR ", clauses[5])

    def test_listing_content_search_accepts_unaccented_location_words(self):
        _clauses, params = keyword_search_filter("T\u0110C Ph\u00fa M\u1ef9")

        self.assertEqual(params, ["% tdc %", "% phu %", "% my %"])

    def test_dimension_search_matches_common_separator_variants(self):
        clauses, params = keyword_search_filter("5*28")

        self.assertEqual(params, ["%5x28%", "%5*28%", "%5\u00d728%"])
        self.assertEqual(len(clauses), 1)
        self.assertIn(" OR ", clauses[0])

    def test_plain_d_road_code_search_uses_compact_text(self):
        clauses, params = keyword_search_filter("\u0110\u01b0\u1eddng D10")

        self.assertEqual(params, ["%d10%"])
        self.assertEqual(len(clauses), 1)
        self.assertIn("REPLACE(", clauses[0])

    def test_direction_and_urgent_search_use_individual_words(self):
        _direction_clauses, direction_params = keyword_search_filter("T\u00e2y B\u1eafc")
        _urgent_clauses, urgent_params = keyword_search_filter("B\u00e1n g\u1ea5p")

        self.assertEqual(direction_params, ["% tay %", "% bac %"])
        self.assertEqual(urgent_params, ["% ban %", "% gap %"])


if __name__ == "__main__":
    unittest.main()
