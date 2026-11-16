"""
Tests for ingredient name normalization (match_utils/ingredient_names.py).

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
"""

import time
import unittest

from match_utils.ingredient_names import normalize, options, pieces


def index_names(raw, unmeasured=False):
    """What the recipe index stores for one parsed line: each piece with
    its options."""
    name, _ = normalize(raw)
    return [(p, options(p)) for p in pieces(name, unmeasured)] if name else []


class OddNameTests(unittest.TestCase):
    """Names that read oddly once listed as missing (1.1.1)."""

    def test_for_rolling_and_finishing_are_cut(self):
        # "flour for rolling" was missing although flour is a staple.
        self.assertEqual(normalize("Flour for rolling"), ("flour", set()))
        self.assertEqual(normalize("Egg wash for finishing")[0], "egg wash")
        self.assertEqual(normalize("Egg wash for finishing (optional)"), ("egg wash", {"optional"}))

    def test_rolling_is_not_optional(self):
        # The sugar the cookies are rolled in is part of the recipe.
        self.assertEqual(normalize("demerara sugar, for rolling"), ("demerara sugar", set()))

    def test_size_choice(self):
        self.assertEqual(index_names("large or 2 medium onions, chopped"), [("onion", ["onion"])])
        self.assertEqual(index_names("small or 1 or 2 large eggplant (about 11/2 pounds)"),
                         [("eggplant", ["eggplant"])])
        self.assertEqual(index_names("medium or large avocados, pitted")[0][0], "avocado")
        self.assertEqual(index_names("medium to large onion, thinly sliced")[0][0], "onion")
        self.assertEqual(index_names("small or 1/2 large red or yellow bell pepper")[0][0],
                         "red or yellow bell pepper")

    def test_size_as_a_grade_is_kept(self):
        self.assertEqual(index_names("medium or coarse yellow cornmeal"),
                         [("medium or coarse yellow cornmeal", ["medium yellow cornmeal", "coarse yellow cornmeal"])])

    def test_amount_range_left_in_front(self):
        self.assertEqual(normalize("to 11/2 pounds seitan, cooled and patted dry")[0], "seitan")
        self.assertEqual(normalize("to ½ cup plus 2 tablespoons (100g to 125g) sugar")[0], "granulated sugar")

    def test_dried_side_of_a_choice(self):
        self.assertEqual(index_names("minced fresh thyme or ¼ teaspoon dried"),
                         [("thyme or dried", ["thyme", "dried thyme"])])
        self.assertEqual(index_names("ground or grated nutmeg")[0][1], ["ground nutmeg", "nutmeg"])
        self.assertEqual(index_names("cooked or canned chickpeas")[0][1], ["cooked chickpea", "canned chickpea"])

    def test_prep_side_of_a_choice(self):
        self.assertEqual(index_names("chopped or grated mozzarella cheese")[0][1], ["mozzarella cheese"])

    def test_amount_inside_a_choice(self):
        self.assertEqual(normalize("kosher salt or 1/2 teaspoon fine sea salt")[0], "kosher salt or fine sea salt")
        self.assertEqual(index_names("whole chamomile buds or 2 or 3 chamomile tea bags")[0][1],
                         ["whole chamomile bud", "chamomile tea bag"])

    def test_plus_is_two_ingredients(self):
        self.assertEqual([p for p, _ in index_names("grated lemon zest plus 1 teaspoon juice")],
                         ["lemon zest", "lemon juice"])
        self.assertEqual([p for p, _ in index_names("large eggs plus 1 large yolk")], ["egg", "egg yolk"])
        self.assertEqual([p for p, _ in index_names("large egg yolks plus 1 large white")],
                         ["egg yolk", "egg white"])
        self.assertEqual([p for p, _ in index_names("butter plus 3 tablespoons olive oil, or all oil")],
                         ["butter", "olive oil"])
        self.assertEqual([p for p, _ in index_names("(2-inch) strips lemon zest plus 1 tablespoon juice")],
                         ["lemon zest", "lemon juice"])
        self.assertEqual([p for p, _ in index_names("grated lemon zest and 1 tablespoon juice from 1 lemon")],
                         ["lemon zest", "lemon juice"])
        # "and" splits only before an amount.
        self.assertEqual([p for p, _ in index_names("salt and pepper")], ["salt and pepper"])

    def test_plus_a_cut_is_one_ingredient(self):
        self.assertEqual([p for p, _ in index_names("sprigs fresh thyme plus ½ teaspoon chopped")], ["thyme"])
        self.assertEqual([p for p, _ in index_names("water plus 2 cups (475ml) hot water")], ["water"])

    def test_plus_inside_a_choice_stays_one(self):
        self.assertEqual(index_names("coconut milk or 11/2 cups coconut milk plus 11/2 cups water")[0][1],
                         ["coconut milk"])

    def test_plus_more_is_cut(self):
        self.assertEqual(normalize("homemade or low-sodium canned chicken stock plus more if necessary")[0],
                         "homemade or low-sodium canned chicken stock")

    def test_or_more(self):
        self.assertEqual(normalize("clove or more garlic")[0], "garlic")
        self.assertEqual(index_names("butter or more oil")[0][1], ["butter", "butter oil", "more oil"])

    def test_not_ingredients(self):
        self.assertEqual(normalize("Scant 1 cup")[0], "")
        self.assertEqual(normalize("cups")[0], "")
        # Genius Recipes' Pumpkin Pie listed "unbaked" as missing.
        self.assertEqual(normalize("Unbaked, unpricked, chilled 9-inch (23cm) pie shell (store-bought or homemade)")[0],
                         "pie shell")

    def test_colour_list_before_prep_notes(self):
        self.assertEqual(normalize("red, orange, or yellow bell pepper, cored, seeded, and thinly sliced")[0],
                         "red or orange or yellow bell pepper")

    def test_longest_list_still_wins(self):
        self.assertIn("blueberry", options(normalize(
            "sliced apple or pear (peeled and cored), banana, or strawberries, or whole raspberries or blueberries")[0]))

    def test_squeezed_juice_is_the_juice(self):
        # Lemons cover "lemon juice", but didn't cover "squeezed lemon juice".
        self.assertEqual(normalize("freshly squeezed lemon juice, or more to taste")[0], "lemon juice")
        self.assertEqual(normalize("Freshly squeezed lime juice to taste")[0], "lime juice")

    def test_to_taste_and_as_needed(self):
        self.assertEqual(normalize("Extra virgin olive oil as needed")[0], "extra virgin olive oil")
        chile = index_names("minced fresh chile, or to taste, or hot red pepper flakes")[0][1]
        self.assertIn("hot red pepper flake", chile)
        self.assertFalse([o for o in chile if "taste" in o])

    def test_choices_set_off_by_semicolons(self):
        self.assertEqual(options(normalize("distilled vinegar; 1/4 cup lemon juice; or 2 teaspoons nigari")[0]),
                         ["distilled vinegar", "lemon juice", "nigari"])
        # Not a choice: a note after the semicolon.
        self.assertEqual(options(normalize("Sharp Vinaigrette; vigorously shaken")[0]),
                         ["sharp vinaigrette; vigorously shaken"])

    def test_gallon(self):
        self.assertEqual(normalize("gallon soy milk")[0], "soy milk")


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
