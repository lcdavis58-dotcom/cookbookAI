"""
The real recipe index and database, with no model: searches, listings
and scaling that run on code alone. Also checks the index matches the
PDFs, so a stale index (a parser change without a rebuild) shows up.

Run from app/:
    python3 -m unittest discover -s testing/local -t .
"""

import unittest
from collections import Counter

from actions import ask, match, scale
from chat import turn
from chat.state import ChatState
from match_utils.recipe_index import load_index
from testing.local.needs import needs_database, needs_index
from testing.local.test_pdfs import RECIPES


def titles(results):
    return [r["entry"]["title"] for r in results]


@needs_index
class IndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load_index()

    def test_same_recipe_counts_as_the_pdfs(self):
        # Fails after a parser change until the index is rebuilt
        # (tools/build_recipe_index.py, or a re-ingest).
        counts = Counter(e["book"] for e in self.index)
        self.assertEqual(dict(counts), {book: n for book, (n, _) in RECIPES.items()})

    def test_listing(self):
        for what, expected in (("pumpkin pie", 7), ("chocolate chip cookie", 18), ("whipped cream", 11)):
            with self.subTest(what=what):
                self.assertEqual(len(ask.list_recipes(what, f"show me my {what} recipes").choices), expected)

    def test_what_can_i_make(self):
        result = match.run("cinnamon, heavy cream")
        self.assertEqual(result.kind, "matches")
        self.assertEqual(len(result.missing_some), 32)
        self.assertIn("Apple Galette", titles(result.missing_some))

    def test_typo_is_corrected(self):
        result = match.run("cinammon, heavy cream")
        self.assertTrue(result.corrections)
        self.assertEqual(len(result.missing_some), 32)


@needs_database
class ScaleRealRecipeTest(unittest.TestCase):
    def test_double_by_name(self):
        result = scale.run("double the classic whipped cream")
        self.assertEqual((result.kind, result.title, result.book, result.factor),
                         ("scaled", "Classic Whipped Cream", "The Book On Pie", 2.0))

    def test_replay_of_a_real_chat(self):
        # Chat 2026-11-12-2136-xwhp, which needs no model.
        state = ChatState.new()
        listing = turn.respond(state, "show me my chocolate chip cookie recipes")
        self.assertEqual(len(listing.result.choices), 18)
        shown = turn.respond(state, "12")
        self.assertEqual(shown.result.recipe.title, "Favorite Thin and Crispy")
        self.assertEqual(turn.respond(state, "triple it").result.factor, 3.0)
        self.assertEqual(turn.respond(state, "cut in in half").result.factor, 1.5)


if __name__ == "__main__":
    unittest.main()
