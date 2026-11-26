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
from testing.local.needs import needs_database, needs_index, needs_search
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
        self.assertEqual(len(result.missing_some), 34)
        self.assertIn("Apple Galette", titles(result.missing_some))

    def test_typo_is_corrected(self):
        result = match.run("cinammon, heavy cream")
        self.assertTrue(result.corrections)
        self.assertEqual(len(result.missing_some), 34)


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


@needs_database
@needs_search
class FindTheRightRecipeTest(unittest.TestCase):
    """1.1.3, from real chats (2026-11-06 and 2026-11-07); no model."""

    def test_butter_cream_from_a_book(self):
        result = ask.run("show me my butter cream recipe from dessert person")
        self.assertEqual((result.kind, result.recipe.title), ("recipe", "Silkiest Chocolate Buttercream"))

    def test_found_through_a_variation_says_so(self):
        result = ask.run("show me my brown butter cream cheese frosting")
        self.assertEqual((result.kind, result.recipe.title), ("recipe", "Classic Cream Cheese Frosting"))
        self.assertTrue(ask.variation_note(result).startswith("Brown Butter Cream Cheese Frosting is a variation"))

    def test_the_extra_thick_one(self):
        state = ChatState.new()
        turn.respond(state, "show me classic whipped cream")
        shown = turn.respond(state, "what about the extra-thick one")
        self.assertEqual(shown.result.recipe.title, "Extra-Thick and Creamy Whipped Cream")
        self.assertEqual(state.focus.recipe.title, "Extra-Thick and Creamy Whipped Cream")

    def test_the_one_from_another_book(self):
        state = ChatState.new()
        turn.respond(state, "show me the chocolate chip cookies from ratio")
        shown = turn.respond(state, "show me the one from dessert person")
        self.assertEqual((shown.result.recipe.title, shown.result.recipe.book),
                         ("Chocolate Chip Cookies", "Dessert Person"))


@needs_index
class MoreAndOrderTest(unittest.TestCase):
    def test_rarer_ingredients_break_a_tie(self):
        # A whipped cream once came first for these; the user moved the
        # fix into 1.1.3.
        result = match.run("pumpkin, cream cheese, heavy cream")
        self.assertIn("Pumpkin", titles(result.missing_some)[0])

    def test_more_shows_the_rest(self):
        state = ChatState.new()
        turn.respond(state, "cinnamon, heavy cream")
        self.assertEqual(len(state.focus.numbered.items), 15)
        more = turn.respond(state, "more")
        self.assertIn("  16. ", more.text)
        self.assertEqual(len(state.focus.numbered.items), 30)


@needs_index
class DishAndFilterTest(unittest.TestCase):
    """1.2.0: dish labels, filtering by an ingredient, narrowing."""

    @classmethod
    def setUpClass(cls):
        cls.index = load_index()

    def test_nearly_every_recipe_has_a_dish_type(self):
        # Fails on an index built before 1.2.0, or with the model down
        # for most of the build (tools/build_recipe_index.py).
        labeled = sum(1 for e in self.index if e.get("dishes"))
        self.assertGreater(labeled, 0.95 * len(self.index))

    def test_titles_that_name_a_type_have_it(self):
        by_title = {e["title"]: e for e in self.index}
        for title, dish in (("Brown Butter Chocolate Chip Cookies", "cookie"), ("Pumpkin Pie", "pie"),
                            ("Classic Guacamole", "dip")):
            with self.subTest(title=title):
                self.assertIn(dish, by_title[title]["dishes"])

    def test_pumpkin_pies_and_half_and_half(self):
        state = ChatState.new()
        turn.respond(state, "what pumpkin pie recipes do i have")
        uses = turn.respond(state, "do any of these use half and half")
        self.assertEqual(len(uses.result.choices), 2)
        without = turn.respond(ChatState.new(), "a pumpkin pie without half and half")
        self.assertEqual(len(without.result.choices), 5)

    def test_a_dish_type_finds_untitled_recipes(self):
        found = {c.title for c in ask.list_recipes("cookie", "what cookie recipes do i have").choices}
        self.assertIn("Snickerdoodles", found)
        self.assertGreater(len(found), 150)

    def test_long_lists_ask_to_narrow(self):
        state = ChatState.new()
        reply = turn.respond(state, "show me a cookie recipe")
        self.assertIn("Want to narrow it down?", reply.text)
        narrowed = turn.respond(state, "a chocolate chip one")
        self.assertLessEqual(len(narrowed.result.choices) + len(narrowed.result.rest), 30)
        self.assertIn("Chocolate Chip Cookies", {c.title for c in narrowed.result.choices + narrowed.result.rest})


if __name__ == "__main__":
    unittest.main()
