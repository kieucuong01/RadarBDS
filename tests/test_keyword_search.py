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


if __name__ == "__main__":
    unittest.main()
