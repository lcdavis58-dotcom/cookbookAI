"""
Tests for reading a scaling request and applying it
(scale_utils/recipe_scaling.py, scale_utils/scaling_rules.py): the
multipliers, yields and ingredient amounts she says, and amounts that
only come whole. No model or database.

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

from actions.scale import scaled_ingredient_lines  # noqa: E402
from books import profile_for, strategy_for  # noqa: E402
from books.line_styles import metric_slash  # noqa: E402
from scale_utils.ingredients import split_plus  # noqa: E402
from scale_utils.recipe_scaling import (count_numbers, detect_direct_multiplier, detect_stated_yield,  # noqa: E402
                                        resolve_scale_factor, scale_ingredients, stated_unit, with_digits)


def constraint(name, amount):
    return {"basis": "ingredient_constraint", "reference_ingredient": name, "target_ingredient_amount": amount}


def count_line(name, amount, unit=None):
    return {"name": name, "metric_amount": None, "metric_unit": None, "imperial_amount": amount,
            "imperial_unit": unit}


class MultiplierTest(unittest.TestCase):
    def test_multipliers(self):
        for request, expected in (("double it", 2.0), ("halve the half-and-half pie", 0.5),
                                  ("make it half again as much", 1.5), ("half as much", 0.5),
                                  ("scale that by 3", 3.0), ("scale it by 3", 3.0),
                                  ("scale the recipe up by 2.5", 2.5), ("scale by 2", 2.0), ("3x", 3.0)):
            with self.subTest(request=request):
                self.assertEqual(detect_direct_multiplier(request), expected)

    def test_names_with_a_multiplier_word_arent_one(self):
        for request in ("do any of these use half and half", "half-and-half, brown sugar",
                        "can I use double cream", "do I need a double boiler", "scale it down by 3"):
            with self.subTest(request=request):
                self.assertIsNone(detect_direct_multiplier(request))


class StatedYieldTest(unittest.TestCase):
    def test_her_numbers(self):
        for request, expected in (("this usually feeds 5 people, make it feed 8", (5, 8)),
                                  ("it normally serves 4, i want 10", (4, 10)),
                                  ("this feeds 8, I need to feed 12", (8, 12)),
                                  ("this usually feeds 2 people, i need it to feed 9", (2, 9)),
                                  ("it serves 4 in a 9-inch pan, make it for 6", (4, 6))):
            with self.subTest(request=request):
                self.assertEqual(detect_stated_yield(request), expected)

    def test_number_words(self):
        for request, expected in (("it feeds five, make it for eight", (5, 8)),
                                  ("this usually serves six but I need twelve", (6, 12)),
                                  ("it makes a dozen, I need 18", (12, 18)),
                                  ("make this one for 10, it serves 4", (4, 10))):
            with self.subTest(request=request):
                self.assertEqual(detect_stated_yield(request), expected)
        self.assertEqual(with_digits("show me the one from dessert person"), "show me the one from dessert person")

    def test_left_to_the_model(self):
        for request in ("it makes 2 dozen, I need three dozen", "make it for 12 people", "it makes 24, I need 3 dozen", "it serves 4, 4 more are coming",
                        "it makes 2 batches, I want 3 batches"):
            with self.subTest(request=request):
                self.assertIsNone(detect_stated_yield(request))

    def test_count_numbers(self):
        self.assertEqual(count_numbers("a 9-inch pan, 200 g of flour, 3x, for 6 people"), [6.0])

    def test_her_original_over_the_yield_line(self):
        # The model took the yield line's 8 (chat 2026-11-12-2131-sz7k).
        for request, intent, expected in (
                ("this usually feeds 5 people, make it feed 8", {"target_yield": 8, "original_yield": 8}, 1.6),
                ("this usually feeds 2 people, i need it to feed 9", {"target_yield": 9, "original_yield": 8}, 4.5)):
            with self.subTest(request=request):
                factor, explanation = resolve_scale_factor({"basis": "yield", **intent}, [], "SERVES 8", request)
                self.assertEqual(factor, expected, explanation)


class IngredientAmountTest(unittest.TestCase):
    BUTTER = [metric_slash("226 g / 1 cup unsalted butter")]

    def test_a_count_against_a_weighed_count(self):
        eggs = [metric_slash("100 g / 2 large eggs")]
        self.assertEqual(resolve_scale_factor(constraint("large eggs", 1), eggs, "", "I only have 1 egg")[0], 0.5)

    def test_units(self):
        for request, amount, expected in (("I only have 50 g of butter", 50, 50 / 226),
                                          ("I have 1/2 cup butter", 0.5, 0.5),
                                          ("I have 0.113 kg of butter", 0.113, 0.5)):
            with self.subTest(request=request):
                factor, explanation = resolve_scale_factor(constraint("butter", amount), self.BUTTER, "", request)
                self.assertAlmostEqual(factor, expected, places=3, msg=explanation)

    def test_ounces_against_grams(self):
        factor, _ = resolve_scale_factor(constraint("butter", 4), self.BUTTER, "", "I have 4 oz butter")
        self.assertAlmostEqual(factor, 4 * 28.35 / 226, places=3)

    def test_a_unit_the_line_cant_compare(self):
        chocolate = [metric_slash("28 g / 1 oz chocolate")]
        factor, explanation = resolve_scale_factor(constraint("chocolate", 2), chocolate, "", "I have 2 cups chocolate")
        self.assertIsNone(factor)
        self.assertIn("can't compare with 2 cup", explanation)

    def test_stated_unit(self):
        self.assertEqual(stated_unit("I only have 50 grams of butter", 50), "gram")
        self.assertEqual(stated_unit("I have 1/2 cup", 0.5), "cup")
        self.assertIsNone(stated_unit("I only have 1 egg", 1))


class WholeItemsTest(unittest.TestCase):
    def scaled(self, ing, factor):
        return scale_ingredients([ing], factor)[0]

    def test_a_crust_isnt_scaled(self):
        crust = self.scaled(count_line("blind-baked 9-inch piecrust", 1), 1.6)
        self.assertEqual(crust["scaled_imperial"], 1)
        self.assertIn("pan", crust["flags"][-1][1])

    def test_cans_round_to_whole(self):
        for factor, expected, noted in ((1.125, 1, True), (1.6, 2, True), (1.05, 1, False), (0.3, 1, True)):
            with self.subTest(factor=factor):
                can = self.scaled(count_line("(15-ounce/425g) can pumpkin purée", 1), factor)
                self.assertEqual(can["scaled_imperial"], expected)
                self.assertEqual(any(kind == "rounded" for kind, _ in can["flags"]), noted)

    def test_a_pinch_rounds_without_a_note(self):
        salt = self.scaled(count_line("salt", 1, "pinch"), 1.6)
        self.assertEqual((salt["scaled_imperial"], salt["flags"]), (2, []))
        self.assertIn("salt: 1 pinch  ->  ~2 pinches", scaled_ingredient_lines(salt)[0])

    def test_eggs_round_with_the_exact_amount_noted(self):
        for factor, expected, note in ((1.125, 3, "Rounded down to 3; the exact amount is 3.38."),
                                       (1.5, 5, "Rounded up to 5; the exact amount is 4.5,"), (2, 6, None)):
            with self.subTest(factor=factor):
                eggs = self.scaled(count_line("large eggs", 3), factor)
                self.assertEqual(eggs["scaled_imperial"], expected)
                rounded = [n for kind, n in eggs["flags"] if kind == "rounded"]
                if note:
                    self.assertTrue(rounded[0].startswith(note), rounded)
                else:
                    self.assertEqual(rounded, [])

    def test_the_egg_tip_only_when_rounded(self):
        # Flag wg7cv: 2 eggs doubled said it had rounded.
        self.assertEqual(self.scaled(count_line("large eggs, room temperature", 2), 2)["flags"], [])
        rounded = self.scaled(count_line("large eggs", 3), 1.125)["flags"]
        self.assertEqual([kind for kind, _ in rounded], ["rounded"])
        self.assertIn("whisk one egg", rounded[0][1])

    def test_a_weighed_egg_rounds_its_count_and_keeps_its_grams(self):
        eggs = self.scaled(metric_slash("100 g / 2 large eggs"), 1.25)
        self.assertEqual((eggs["scaled_metric"], eggs["scaled_imperial"]), (125, 3))

    def test_a_weighed_crust_is_scaled(self):
        crust = self.scaled({**count_line("pie crust", 1), "metric_amount": 300.0, "metric_unit": "g"}, 1.5)
        self.assertEqual(crust["scaled_metric"], 450)

    def test_other_counts_and_measures_are_unchanged(self):
        self.assertAlmostEqual(self.scaled(count_line("onions", 3), 1.125)["scaled_imperial"], 3.375)
        self.assertAlmostEqual(self.scaled(count_line("crust crumbs", 1, "cup"), 1.5)["scaled_imperial"], 1.5)



class SplitPlusTest(unittest.TestCase):
    """A line naming a second ingredient with its own amount."""
    BOOK = strategy_for("The Complete Cooking For Two Cookbook")

    def split(self, line):
        ing = profile_for(self.BOOK).parse_ingredient_line(line)
        return [(i["name"], i["imperial_amount"], i["imperial_unit"], i.get("plus", False))
                for i in split_plus(ing, self.BOOK)]

    def test_two_ingredients(self):
        self.assertEqual(self.split("1 large egg plus 1 large yolk"),
                         [("large egg", 1, None, False), ("large egg yolk", 1, None, True)])
        self.assertEqual(self.split("¼ teaspoon grated lemon zest plus 1 teaspoon juice"),
                         [("grated lemon zest", 0.25, "teaspoon", False), ("lemon juice", 1, "teaspoon", True)])
        self.assertEqual(self.split("2 teaspoons grated lemon zest and 1 tablespoon juice (from 1 lemon)")[1],
                         ("lemon juice (from 1 lemon)", 1, "tablespoon", True))
        self.assertEqual(self.split("1 sprig fresh thyme, plus ¼ teaspoon minced")[1], ("minced", 0.25, "teaspoon", True))

    def test_left_as_one_line(self):
        for line in ("2 limes, 1 halved and 1 quartered", "⅓cup (1⅔ ounces) plus 8 teaspoons all-purpose flour",
                     "1 cup milk or 1 cup water plus 2 tablespoons milk powder"):
            with self.subTest(line=line):
                self.assertEqual(len(self.split(line)), 1)

    def test_weighed_lines(self):
        ing = metric_slash("170 g / ¾ cup extra virgin olive oil, plus 1 tablespoon")
        self.assertEqual([(i["name"], i["metric_amount"], i["imperial_amount"], i["imperial_unit"])
                          for i in split_plus(ing, strategy_for("Savory Baking"))],
                         [("extra virgin olive oil", 170, 0.75, "cup"), ("extra virgin olive oil", None, 1, "tablespoon")])
        self.assertEqual(self.split("1½ cups medium-spicy or spicy cabbage kimchi, plus 2 tablespoons kimchi liquid")[1],
                         ("kimchi liquid", 2, "tablespoon", True))

    def test_both_are_scaled_and_shown(self):
        ing = profile_for(self.BOOK).parse_ingredient_line("1 large egg plus 1 large yolk")
        lines = [scaled_ingredient_lines(i)[0] for i in scale_ingredients(split_plus(ing, self.BOOK), 2)]
        self.assertEqual(lines, ["  large egg: 1 whole  ->  2 whole", "  plus large egg yolk: 1 whole  ->  2 whole"])


if __name__ == "__main__":
    unittest.main()
