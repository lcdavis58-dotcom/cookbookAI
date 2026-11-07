"""
Tests for the actions package: what each result kind renders as on the
command line, and what scale_recipe returns for a recipe that's already
been found. Recipes here are made up, not book text, and nothing needs
the database or a model.

Run from app/:
    python3 -m unittest discover testing
"""

import sys
import types
import unittest
from unittest import mock

# The actions import the database and model clients; neither is called
# here, so stand-ins are enough where they aren't installed.
for _name in ("chromadb", "ollama"):
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = types.ModuleType(_name)

from actions import ask, match, scale  # noqa: E402
from match_utils.typos import Correction  # noqa: E402
from query_utils.title_lookup import Candidate  # noqa: E402


def candidate(title, book="The Book On Pie", page=None):
    payload = {"page": page or 0, "page_confirmed": page is not None}
    return Candidate(f"{book}-{title}", book, title, [([title.lower()], [])], payload)


BATCHED = """TEST TOPPING
MAKES 1 CUP
SMALL BATCH
100 g / ½ cup heavy cream
10 g / 1 tablespoon granulated sugar
LARGE BATCH
200 g / 1 cup heavy cream
20 g / 2 tablespoons granulated sugar
Whip the cream with the sugar until soft peaks form."""

TWO_CREAMS = """TEST CREAM
MAKES 1 CUP
235 g / 1 cup heavy cream
120 g / ½ cup sour cream
Egg wash
Whip everything together."""


class AskRenderTest(unittest.TestCase):
    def test_recipe(self):
        result = ask.AskResult("recipe", "q", recipe=candidate("Test Pie", page=12), text="TEST PIE\n...")
        self.assertEqual(ask.render(result), "Found this directly in The Book On Pie (p.12), showing the "
                                             "exact text:\n\nTEST PIE\n...\n\n(matched instantly, no generation needed)")

    def test_choices_same_name_suggests_the_book(self):
        result = ask.AskResult("choices", "banana bread", more=3,
                               choices=[candidate("Banana Bread", "Book A"), candidate("Banana Bread", "Book B")])
        text = ask.render(result)
        self.assertIn('I found 5 recipes matching "banana bread"', text)
        self.assertIn("  1. Banana Bread  (Book A, page unknown)", text)
        self.assertIn("  ...and 3 more.", text)
        self.assertIn('python3 query.py "recipe for banana bread from Book A"', text)

    def test_choices_different_names(self):
        result = ask.AskResult("choices", "q", choices=[candidate("Whipped Cream"), candidate("Classic Whipped Cream")])
        self.assertIn('python3 query.py "recipe for whipped cream"\n', ask.render(result))

    def test_answer_lists_sources(self):
        hit = {"book": "Book A", "page": 4, "page_confirmed": True, "distance": 0.31}
        result = ask.AskResult("answer", "q", answer="It's fine.", sources=[hit], generation_time=1.5)
        self.assertEqual(ask.render(result), "It's fine.\n\n(generation took 1.50s)\n--- Retrieved from ---\n"
                                             "  Book A, p.4 (distance 0.310)")

    def test_warning_comes_first(self):
        result = ask.AskResult("nothing", "q", warnings=["[warning] stale"])
        self.assertEqual(ask.render(result), "[warning] stale\n\n"
                                             "I couldn't find anything relevant to that in your cookbooks.")


class ScaleRenderTest(unittest.TestCase):
    def test_not_found(self):
        self.assertIn("in Ratio or Book A.", scale.render(scale.ScaleResult("not_found", reason="not_in_book",
                                                                           books=["Ratio", "Book A"])))
        self.assertIn("anything relevant", scale.render(scale.ScaleResult("not_found", reason="nothing_relevant")))
        self.assertIn("identify a specific recipe", scale.render(scale.ScaleResult("not_found", reason="no_recipe")))

    def test_choices(self):
        choices = [candidate("Classic Lasagna", "Book A"), candidate("Lasagna Bolognese", "Book B")]
        partial = scale.render(scale.ScaleResult("choices", choices=choices, partial=True))
        self.assertTrue(partial.startswith("I couldn't find a recipe by exactly that name."))
        self.assertIn('"... the classic lasagna from Book A"', partial)
        self.assertTrue(partial.endswith("Run again using one of these names."))
        full = scale.render(scale.ScaleResult("choices", choices=choices, more=2))
        self.assertTrue(full.startswith("I found 4 recipes matching your request."))
        self.assertIn("  2. Lasagna Bolognese  (Book B)", full)

    def test_no_factor_keeps_the_heading(self):
        result = scale.ScaleResult("no_factor", title="Test Cream", book="Book A", problem="ambiguous",
                                   ambiguous=["heavy cream", "sour cream"])
        self.assertEqual(scale.render(result), "Scaling 'Test Cream' from Book A...\n\n"
                                               "That ingredient matches more than one item in this recipe: "
                                               "heavy cream, sour cream\nTry being more specific about which one you mean.")

    def test_pick_batch(self):
        result = scale.ScaleResult("pick_batch", title="Test Topping", batches=[("Small", "for one"), ("Large", None)])
        self.assertEqual(scale.render(result), "'Test Topping' has multiple batch sizes and no single default. "
                                               "Which one do you want?\n\n  - Small (for one)\n  - Large")


class ScaleRecipeTest(unittest.TestCase):
    """scale_recipe on made-up recipes, with the database and model
    patched out."""

    def scale(self, text, question, intent=None):
        with mock.patch.object(scale, "candidate_text", return_value=text), \
             mock.patch.object(scale, "determine_scale_intent", return_value=(intent, 0.1)):
            return scale.scale_recipe(candidate("Test"), question)

    def test_direct_multiplier(self):
        result = self.scale(TWO_CREAMS, "double it")
        self.assertEqual(result.kind, "scaled")
        self.assertEqual(result.factor, 2.0)
        self.assertEqual((result.title, result.book, result.batch), ("Test Cream", "The Book On Pie", ""))
        [section] = result.sections
        self.assertIsNone(section.heading)
        self.assertEqual([i["name"] for i in section.ingredients], ["heavy cream", "sour cream", "Egg wash"])
        text = scale.render(result)
        self.assertIn("  heavy cream: 235 g / 1 cup  ->  470 g / 2 cups", text)
        self.assertIn("  Egg wash  (as needed, not scaled)", text)

    def test_batches_without_a_default_are_asked_about(self):
        result = self.scale(BATCHED, "double it")
        self.assertEqual(result.kind, "pick_batch")
        self.assertEqual([name for name, _ in result.batches], ["Small Batch", "Large Batch"])

    def test_ambiguous_ingredient(self):
        intent = {"basis": "ingredient_constraint", "reference_ingredient": "cream", "target_ingredient_amount": 100}
        result = self.scale(TWO_CREAMS, "I only have 100 g of cream", intent)
        self.assertEqual((result.kind, result.problem), ("no_factor", "ambiguous"))
        self.assertEqual(result.ambiguous, ["heavy cream", "sour cream"])
        self.assertEqual(result.intent, intent)

    def test_model_gives_no_intent(self):
        result = self.scale(TWO_CREAMS, "make it nicer")
        self.assertEqual((result.kind, result.problem), ("no_factor", "no_intent"))

    def test_stale_index(self):
        result = self.scale("", "double it")
        self.assertEqual(result.kind, "stale_index")
        self.assertIn("index is out of date", scale.render(result))


class MatchRenderTest(unittest.TestCase):
    def found(self, title, missing=()):
        entry = {"title": title, "book": "Book A", "page": 3, "page_confirmed": True}
        return {"entry": entry, "uses": ["lemon"], "missing": list(missing),
                "staples_used": [], "optional_on_hand": []}

    def test_matches(self):
        result = match.MatchResult("matches", have=["lemon"], corrections=[Correction("lemmon", "lemon")],
                                   assumptions=["assuming x"], ready=[self.found("Curd")],
                                   missing_one=[self.found("Tart", ["flour"])])
        self.assertEqual(match.render(result).splitlines(), [
            'Note: "lemmon" looks like a typo, so I searched for "lemon" instead.',
            "You have: lemon  (plus pantry staples)",
            "  (assuming x)",
            "", "You can make (1):", "  Curd  [Book A, p.3]", "      uses: lemon",
            "", "You can make, with a sub-recipe from scratch (0):", "  (none)",
            "", "Missing one thing (1):", "  Tart  [Book A, p.3]", "      uses: lemon", "      missing: flour",
        ])

    def test_long_sections_are_cut_short(self):
        result = match.MatchResult("matches", have=["lemon"],
                                   ready=[self.found(f"R{i}") for i in range(match.SHOW_PER_SECTION + 2)])
        self.assertIn("  ...and 2 more", match.render(result))

    def test_problems(self):
        self.assertIn("No recipe index yet", match.render(match.MatchResult("no_index")))
        self.assertIn("separated by commas", match.render(match.MatchResult("no_ingredients")))


if __name__ == "__main__":
    unittest.main()
