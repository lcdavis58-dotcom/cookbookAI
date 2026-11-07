"""
Tests for ingredient typo correction (match_utils/typos.py) and the word
counts saved with the recipe index.

Run from app/:
    python3 -m unittest discover testing
"""

import unittest

from match_utils.recipe_index import ingredient_words
from match_utils.typos import TypoFixer, describe

WORDS = {"cinnamon": 40, "pineapple": 6, "brown": 30, "sugar": 90, "lime": 12, "juice": 25,
         "butter": 80, "batter": 2, "gruyère": 3, "crème": 9, "fraîche": 9, "pecan": 10, "pasta": 15,
         "paste": 8, "cardamom": 7}


def fix(*names):
    return TypoFixer(WORDS, extra_words=["kosher salt"]).fix(list(names))


class Correcting(unittest.TestCase):
    def test_word_in_a_name(self):
        names, corrections = fix("brown suger", "cinamon")
        self.assertEqual(names, ["brown sugar", "cinnamon"])
        self.assertEqual([(c.typed, c.word) for c in corrections], [("suger", "sugar"), ("cinamon", "cinnamon")])

    def test_swapped_letters(self):
        self.assertEqual(fix("pinplex")[0], ["pinplex"])        # too far off
        self.assertEqual(fix("pinapple")[0], ["pineapple"])
        self.assertEqual(fix("cardamon")[0], ["cardamom"])

    def test_known_words_untouched(self):
        names, corrections = fix("paste", "pasta", "batter", "pecans", "kosher salt")
        self.assertEqual(names, ["paste", "pasta", "batter", "pecans", "kosher salt"])
        self.assertEqual(corrections, [])

    def test_short_and_unknown_words_untouched(self):
        self.assertEqual(fix("yuzu", "farro", "lime")[0], ["yuzu", "farro", "lime"])

    def test_accents_without_a_note(self):
        names, corrections = fix("gruyere", "creme fraiche")
        self.assertEqual(names, ["gruyère", "crème fraîche"])
        self.assertEqual(corrections, [])

    def test_ties_name_the_other(self):
        fixer = TypoFixer({"pears": 5, "peaks": 1})
        names, corrections = fixer.fix(["peqrs"])
        self.assertEqual(names, ["pears"])
        self.assertEqual(corrections[0].others, [])
        _, corrections = TypoFixer({"bacon": 9, "bason": 2}).fix(["bakon"])
        self.assertEqual((corrections[0].word, corrections[0].others), ("bacon", ["bason"]))

    def test_duplicate_after_correction_dropped(self):
        self.assertEqual(fix("cinnamon", "cinamon")[0], ["cinnamon"])


class Note(unittest.TestCase):
    def test_one(self):
        _, corrections = fix("cinamon")
        self.assertEqual(describe(corrections),
                         'Note: "cinamon" looks like a typo, so I searched for "cinnamon" instead.')

    def test_several(self):
        _, corrections = fix("cinamon", "brown suger")
        self.assertEqual(describe(corrections),
                         'Note: these look like typos, so I searched for the corrected names instead: '
                         '"cinamon" -> "cinnamon", "suger" -> "sugar".')


class Counting(unittest.TestCase):
    def test_ingredient_words(self):
        entries = [{"ingredients": [{"options": ["light brown sugar", "honey"]}], "optional": []},
                   {"ingredients": [{"options": ["brown sugar"]}], "optional": [{"options": ["2% milk"]}]}]
        self.assertEqual(ingredient_words(entries), {"brown": 2, "honey": 1, "light": 1, "milk": 1, "sugar": 2})


if __name__ == "__main__":
    unittest.main()
