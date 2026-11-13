"""
Tests for ingredient name normalization (match_utils/ingredient_names.py).

Run from app/:
    python3 -m unittest discover testing
"""

import time
import unittest

from match_utils.ingredient_names import normalize


class CommaListTests(unittest.TestCase):
    def test_choice_joins_with_or(self):
        self.assertEqual(normalize("gruyère, manchego, or parmesan"),
                         ("gruyère or manchego or parmesan", {"alternative"}))

    def test_list_joins_with_and(self):
        self.assertEqual(normalize("flaky salt, pepper, and lemon")[0], "flaky salt and pepper and lemon")

    def test_prep_notes_are_not_a_list(self):
        self.assertEqual(normalize("vanilla bean, halved lengthwise, seeds scraped out, "
                                   "or 2 teaspoons vanilla extract")[0], "vanilla bean")

    def test_many_commas_and_spaces_stay_fast(self):
        # Took about 50 seconds before the list pattern was fixed (CodeQL
        # "inefficient regular expression"), and 5x longer per comma
        start = time.perf_counter()
        normalize("a" + ",    x" * 12 + "!")
        self.assertLess(time.perf_counter() - start, 1)


if __name__ == "__main__":
    unittest.main()
