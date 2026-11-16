"""
Tests for the text repairs made at extraction (ingest_utils/extract.py
_fix_text): ligatures, mis-mapped fraction glyphs, spaced fractions.
Strings here are made up.

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
"""

import unittest

from ingest_utils.extract import _fix_text


class FixTextTest(unittest.TestCase):
    def test_ligatures(self):
        self.assertEqual(_fix_text("Difﬁculty: ﬂour"), "Difficulty: flour")
        self.assertEqual(_fix_text("ɻour and coʃee"), "flour and coffee")

    def test_private_use_ft_ligature(self):
        # Dessert Person's "So and Pillowy Flatbread" couldn't be linked.
        self.assertEqual(_fix_text("So and Pillowy, aer"), "Soft and Pillowy, after")

    def test_fraction_glyphs(self):
        self.assertEqual(_fix_text("ò cup buttermilk, ragù"), "½ cup buttermilk, ragù")

    def test_spaced_fractions_and_sizes(self):
        self.assertEqual(_fix_text("1 1 /2 teaspoons, 1/2 -inch"), "1 1/2 teaspoons, 1/2-inch")


if __name__ == "__main__":
    unittest.main()
