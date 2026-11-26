"""
Known gaps that plain code gets wrong (no model involved), written as
the test that will pass once each is fixed. Each is skipped with the
version it's planned for; remove the skip in the change that fixes it.
Details are in BOOK_FORMATS.md Follow-ups. Gaps that depend on the model
are in testing/local/test_model.py instead.

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
"""

import sys
import types
import unittest

for _name in ("chromadb", "ollama"):
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = types.ModuleType(_name)

from actions import match  # noqa: E402
from books.line_styles import metric_slash  # noqa: E402
from chat.router import route  # noqa: E402
from chat.state import ChatState, RecipeRef  # noqa: E402
from query_utils.title_lookup import candidates_from_index  # noqa: E402
from scale_utils.recipe_scaling import resolve_scale_factor, scale_ingredients  # noqa: E402


class KnownGapsTest(unittest.TestCase):
    @unittest.skip("known gap, planned for 1.2.1: the egg note says it rounded on every egg line (flag wg7cv)")
    def test_eggs_that_scale_to_a_whole_count_have_no_rounding_note(self):
        eggs = {"name": "large eggs, room temperature", "metric_amount": None, "metric_unit": None,
                "imperial_amount": 2, "imperial_unit": None}
        scaled = scale_ingredients([eggs], 2.0)[0]
        self.assertEqual(scaled["scaled_imperial"], 4)
        self.assertEqual(scaled["flags"], [])

    @unittest.skip("known gap, planned for 1.2.1: the question after the comma is read as an ingredient "
                   "(flag 1tj6n)")
    def test_what_can_i_make_isnt_an_ingredient(self):
        r = route(ChatState.new(), "i have shrimp and pasta, what can i make", candidates=[])
        self.assertEqual((r.action, r.request), ("match", "shrimp, pasta"))

    @unittest.skip("known gap, planned for 1.2.1: the same kind in another word order is listed twice "
                   "(flag 1ncny)")
    def test_one_kind_in_two_word_orders_is_one_note(self):
        notes = ["assuming your buttermilk is cultured low-fat buttermilk",
                 "assuming your buttermilk is low-fat cultured buttermilk"]
        self.assertEqual(len(match._combined(notes)), 1)

    def test_eggs_she_has_against_a_weighed_count(self):
        # "100 g / 2 large eggs" with "I only have 1 egg" gives 1 / 100.
        eggs = [metric_slash("100 g / 2 large eggs")]
        intent = {"basis": "ingredient_constraint", "reference_ingredient": "large eggs",
                  "target_ingredient_amount": 1}
        factor, explanation = resolve_scale_factor(intent, eggs)
        self.assertEqual(factor, 0.5, explanation)

    def test_sentence_with_a_comma_isnt_an_ingredient_list(self):
        candidates = candidates_from_index([{"recipe_id": "r1", "book": "Dessert Person", "title": "Lemon Curd",
                                             "page": 0, "page_confirmed": False}])
        state = ChatState.new()
        state.focus.recipe = RecipeRef.from_candidate(candidates[0])
        r = route(state, "make this one bigger, enough for a crowd of 20", candidates=candidates)
        self.assertEqual(r.action, "scale", r.label)


if __name__ == "__main__":
    unittest.main()
