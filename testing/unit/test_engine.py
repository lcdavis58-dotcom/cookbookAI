"""
Tests for books/engine.py: where recipes start in a book's layout, and
the extra titles a recipe can be found by. Layouts here are made up,
not book text.

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
"""

import re
import types
import unittest

from books.engine import Profile, find_recipe_starts_by_size
from books.line_styles import metric_slash


def line(text, size=15.0, bold=False, page=1):
    return {"text": text, "size": size, "bold": bold, "italic": False, "page": page, "gap": None}


def settings(**extra):
    base = {"TITLE_MIN_SIZE": 27, "YIELD_RE": re.compile(r"^Makes\b"), "parse_ingredient_line": metric_slash}
    return types.SimpleNamespace(**{**base, **extra})


def starts(layout, **extra):
    found, _, _ = find_recipe_starts_by_size([r["text"] for r in layout], layout, settings(**extra))
    return [layout[i]["text"] for i in found]


BOOK = [
    line("Brown Butter Blondies", 30), line("Makes 16 blondies"), line("113 g / ½ cup butter", 11.2),
    line("Salted Caramel Sauce", 30), line("298 g / 1½ cups granulated sugar", 11.2),
    line("A Few Words on Caramel", 30), line("Caramel is sugar cooked until it browns."),
    line("CONTENTS", 30), line("1 COOKIES & BARS"),
]


class RecipeStartsTest(unittest.TestCase):
    def test_a_title_needs_a_yield_line(self):
        self.assertEqual(starts(BOOK), ["Brown Butter Blondies"])

    def test_title_then_ingredients(self):
        # The Fearless Baker's sauces have no yield line.
        self.assertEqual(starts(BOOK, TITLE_THEN_INGREDIENTS=True), ["Brown Butter Blondies", "Salted Caramel Sauce"])

    def test_title_then_ingredients_for_a_module_passed_as_is(self):
        # Cooking For Two passes its module, which names a style but has
        # no parse_ingredient_line (this crashed the 1.1.1 re-ingest).
        layout = BOOK[:5]
        found, _, _ = find_recipe_starts_by_size(
            [r["text"] for r in layout], layout,
            types.SimpleNamespace(TITLE_MIN_SIZE=27, YIELD_RE=re.compile(r"^Makes\b"),
                                  INGREDIENT_STYLE="metric_slash", TITLE_THEN_INGREDIENTS=True))
        self.assertEqual(len(found), 2)

    def test_component_title_inside_a_recipe(self):
        layout = [line("Caesar Salad", 30), line("Makes 4 servings"), line("1 head romaine", 11.3),
                  line("Caesar Salad Dressing", 15.0, bold=True), line("Makes about 1½ cups", 11.3, bold=True),
                  line("Garlic Croutons", 11.3, bold=True), line("These keep for a week.", 11.3),
                  # The end of a bold sentence isn't a title.
                  line("out so nicely?", 11.3, bold=True), line("Makes 8 servings", 11.3)]
        self.assertEqual(starts(layout), ["Caesar Salad"])
        self.assertEqual(starts(layout, COMPONENT_TITLE_MIN_SIZE=11.3), ["Caesar Salad", "Caesar Salad Dressing"])


class TitleAliasesTest(unittest.TestCase):
    def profile(self, aliases=None):
        module = types.ModuleType("test_book")
        module.INGREDIENT_STYLE = "metric_slash"
        if aliases:
            module.TITLE_ALIASES = aliases
        return Profile(module)

    def test_listed_aliases(self):
        self.assertEqual(self.profile({"Brioche Rolls": ["Brioche Dough"]}).title_aliases("BRIOCHE  ROLLS"),
                         ["Brioche Dough"])

    def test_ways_tail(self):
        # "1 recipe Béchamel" is HTCEV's "Béchamel Sauce, 11 Ways".
        self.assertEqual(self.profile().title_aliases("Béchamel Sauce, 11 Ways"), ["Béchamel Sauce"])
        self.assertEqual(self.profile().title_aliases("Braised Tempeh, Three Ways"), ["Braised Tempeh"])
        self.assertEqual(self.profile().title_aliases("Ways to Use Leftovers"), [])


if __name__ == "__main__":
    unittest.main()
