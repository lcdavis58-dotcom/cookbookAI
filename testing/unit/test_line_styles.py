"""
Tests for books/line_styles.py: one parser per way a cookbook prints an
amount. Lines here are made up in each style, not copied from the books.

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
"""

import unittest

from books.line_styles import (STYLES, metric_bracket_volume, metric_slash, names_sub_recipe, volume_paren_metric,
                               volume_pipe_weight)


class Fields:
    def assertFields(self, result, **expected):
        self.assertIsNotNone(result)
        for key, value in expected.items():
            with self.subTest(field=key):
                if isinstance(value, float):
                    self.assertAlmostEqual(result[key], value)
                else:
                    self.assertEqual(result[key], value)

    def assertRejects(self, parse, *lines):
        for line in lines:
            with self.subTest(line=line):
                self.assertIsNone(parse(line))


class StylesTableTest(unittest.TestCase):
    def test_every_style_is_listed(self):
        self.assertEqual(set(STYLES), {"metric_slash", "volume_paren_metric", "volume_pipe_weight",
                                       "metric_bracket_volume"})


class MetricSlashTest(Fields, unittest.TestCase):
    def test_metric_and_volume(self):
        self.assertFields(metric_slash("245 g / 1 cup whole milk"), format="metric_imperial", metric_amount=245.0,
                          metric_unit="g", imperial_amount=1.0, imperial_unit="cup", imperial_display="1 cup",
                          name="whole milk")

    def test_decimal_metric_and_fraction(self):
        self.assertFields(metric_slash("2.5 g / ½ teaspoon fine salt"), metric_amount=2.5,
                          imperial_amount=0.5, imperial_unit="teaspoon", name="fine salt")

    def test_two_imperial_measures_keeps_the_volume(self):
        self.assertFields(metric_slash("57 g / 2 ounces / 4 tablespoons unsalted butter"), metric_amount=57.0,
                          imperial_amount=4.0, imperial_unit="tablespoons", imperial_display="4 tablespoons",
                          name="unsalted butter")

    def test_weight_only_imperial(self):
        self.assertFields(metric_slash("100 g / 4 ounces dark chocolate"), imperial_amount=4.0,
                          imperial_unit="ounces", name="dark chocolate")

    def test_metric_with_a_count(self):
        self.assertFields(metric_slash("50 g / 1 large egg"), metric_amount=50.0, imperial_amount=1.0,
                          imperial_unit=None, imperial_display=None, name="large egg")

    def test_bare_count(self):
        self.assertFields(metric_slash("2 large eggs"), format="count_only", metric_amount=None,
                          imperial_amount=2.0, imperial_unit=None, name="large eggs")

    def test_rejects(self):
        self.assertRejects(metric_slash, "", "   ", "1. Whisk the eggs.", "Pinch of salt")


class VolumeParenMetricTest(Fields, unittest.TestCase):
    def test_volume_with_ounces_and_grams(self):
        self.assertFields(volume_paren_metric("¾ cup sugar (5.3 oz / 150g)"), format="dessert_person",
                          metric_amount=150.0, metric_unit="g", imperial_amount=0.75, imperial_unit="cup",
                          imperial_display="¾ cup", name="sugar")

    def test_kilograms(self):
        self.assertFields(volume_paren_metric("1 cup flour (1.2kg)"), metric_amount=1.2, metric_unit="kg")

    def test_compound_is_summed_in_the_larger_unit(self):
        # 3 tablespoons = 3/16 cup, plus 1/3 cup
        self.assertFields(volume_paren_metric("3 tablespoons plus ⅓ cup almond butter (90g)"),
                          metric_amount=90.0, imperial_amount=3 / 16 + 1 / 3, imperial_unit="cup",
                          imperial_display="3 tablespoons plus ⅓ cup", name="almond butter")

    def test_millilitres_after_the_unit(self):
        self.assertFields(volume_paren_metric("1 tablespoon (15 ml) vanilla extract"), metric_amount=15.0,
                          metric_unit="ml", imperial_amount=1.0, imperial_unit="tablespoon", name="vanilla extract")

    def test_range_scales_from_the_low_end(self):
        self.assertFields(volume_paren_metric("1 to 2 tablespoons (15 to 30 ml) milk"), metric_amount=15.0,
                          imperial_amount=1.0, imperial_display="1 to 2 tablespoons", name="milk")
        self.assertFields(volume_paren_metric("¼–⅓cup water"), metric_amount=None,
                          metric_unit=None, imperial_amount=0.25, imperial_unit="cup", name="water")

    def test_glued_fraction_shows_with_a_space(self):
        self.assertFields(volume_paren_metric("11/2 cups milk (360g)"), imperial_amount=1.5,
                          imperial_display="1 1/2 cups", name="milk")

    def test_footnote_marker_is_dropped(self):
        self.assertFields(volume_paren_metric("1 cup① butter (227g)"), metric_amount=227.0, name="butter")

    def test_metric_in_the_middle(self):
        self.assertFields(volume_paren_metric("1 cup sugar (200g), divided"), metric_amount=200.0,
                          name="sugar, divided")

    def test_unreadable_grams_stay_in_the_name(self):
        self.assertFields(volume_paren_metric("1 cup sugar (abcg)"), metric_amount=None, name="sugar (abcg)")

    def test_counts(self):
        self.assertFields(volume_paren_metric("2 large eggs"), imperial_amount=2.0, imperial_unit=None,
                          name="large eggs")
        self.assertFields(volume_paren_metric("2 (3-inch) cinnamon sticks"), imperial_amount=2.0,
                          name="(3-inch) cinnamon sticks")
        self.assertFields(volume_paren_metric("4–6 slices bacon"), imperial_amount=4.0, name="slices bacon")

    def test_rejects(self):
        self.assertRejects(volume_paren_metric, "", "1. Heat the oven.", "Salt")


class VolumePipeWeightTest(Fields, unittest.TestCase):
    def test_volume_and_ounces(self):
        self.assertFields(volume_pipe_weight("2⅓ cups | 10½ ounces all-purpose flour"),
                          format="bravetart", metric_amount=10.5, metric_unit="oz", imperial_amount=7 / 3,
                          imperial_unit="cup", imperial_display="2⅓ cups", name="all-purpose flour")

    def test_pounds(self):
        self.assertFields(volume_pipe_weight("6 heaping cups | 2 pounds strawberries"), metric_amount=2.0,
                          metric_unit="lb", imperial_amount=6.0, imperial_display="6 heaping cups")

    def test_plus_and_minus(self):
        self.assertFields(volume_pipe_weight("1 cup plus 2 tablespoons | 8 ounces sugar"), imperial_amount=1.125,
                          imperial_unit="cup", imperial_display="1 cup plus 2 tablespoons")
        self.assertFields(volume_pipe_weight("1 cup minus 1 tablespoon | 7 ounces water"), imperial_amount=0.9375,
                          imperial_unit="cup")

    def test_volume_words(self):
        self.assertFields(volume_pipe_weight("¼ cup packed | 2 ounces light brown sugar"),
                          imperial_amount=0.25, imperial_display="¼ cup packed", name="light brown sugar")

    def test_range(self):
        self.assertFields(volume_pipe_weight("½ to ¾ cup | 3 to 5 ounces sugar"), metric_amount=3.0,
                          imperial_amount=0.5, imperial_display="½ to ¾ cup")

    def test_note_after_the_volume(self):
        self.assertFields(volume_pipe_weight("3 cups (finely chopped) | 15 ounces milk chocolate"),
                          metric_amount=15.0, imperial_amount=3.0, name="milk chocolate")

    def test_volume_alone(self):
        self.assertFields(volume_pipe_weight("1 tablespoon vanilla extract"), metric_amount=None,
                          imperial_amount=1.0, imperial_unit="tablespoon", name="vanilla extract")

    def test_weight_alone(self):
        self.assertFields(volume_pipe_weight("8 ounces cream cheese"), metric_amount=8.0, metric_unit="oz",
                          imperial_amount=None, name="cream cheese")

    def test_counts(self):
        self.assertFields(volume_pipe_weight("1 large egg"), format="count_only", imperial_amount=1.0,
                          name="large egg")
        self.assertFields(volume_pipe_weight("1 3- or 4-ounce block white chocolate"), format="count_only",
                          imperial_amount=1.0, name="3- or 4-ounce block white chocolate")

    def test_pipe_inside_parentheses_isnt_the_split(self):
        self.assertFields(volume_pipe_weight("1 envelope (2¼ teaspoons | ¼ ounce) gelatin"),
                          format="count_only", imperial_amount=1.0)

    def test_shy_is_scant(self):
        self.assertFields(volume_pipe_weight("Shy ½ teaspoon salt"), raw="Shy ½ teaspoon salt",
                          qualifier="scant", imperial_amount=0.5, name="salt")
        self.assertIsNone(volume_pipe_weight("Shy "))

    def test_named_sub_recipe_with_no_amount(self):
        self.assertFields(volume_pipe_weight("Cinnamon Sugar (page 44), to taste"), format="fallback",
                          unmeasured=True, name="Cinnamon Sugar (page 44), to taste")

    def test_rejects(self):
        self.assertRejects(volume_pipe_weight, "", "1 cup | nothing", "See page 12. Then stir.")


class NamesSubRecipeTest(unittest.TestCase):
    def test_page_reference(self):
        self.assertTrue(names_sub_recipe("Caramel Sauce (page 60)"))
        self.assertTrue(names_sub_recipe("Pie Dough (pages 10-12)"))

    def test_sentence_isnt_one(self):
        self.assertFalse(names_sub_recipe("Bake as directed. See page 60."))
        self.assertFalse(names_sub_recipe("Caramel Sauce"))


class MetricBracketVolumeTest(Fields, unittest.TestCase):
    def test_weight_and_bracketed_volume(self):
        self.assertFields(metric_bracket_volume("225 g butter, at room temperature [16 tablespoons (2 sticks)]"),
                          format="metric_bracket", metric_amount=225.0, metric_unit="g", imperial_amount=16.0,
                          imperial_unit="tablespoon", name="butter, at room temperature")

    def test_bracket_that_isnt_a_volume_isnt_read(self):
        self.assertFields(metric_bracket_volume("300 g mini pretzels [about ¾ (16-ounce) bag (6 cups)]"),
                          metric_amount=300.0, imperial_amount=None, name="mini pretzels")

    def test_lost_opening_bracket(self):
        self.assertFields(metric_bracket_volume("190 g graham cracker crumbs 1½ cups]"), metric_amount=190.0,
                          imperial_amount=1.5, imperial_unit="cup", name="graham cracker crumbs")

    def test_weight_alone(self):
        self.assertFields(metric_bracket_volume("100 g sugar"), metric_amount=100.0, imperial_amount=None,
                          name="sugar")

    def test_sub_recipe_count_takes_the_bracketed_weight(self):
        self.assertFields(metric_bracket_volume("½ recipe Cornflake Crunch [180 g (2 cups)]"),
                          format="count_only", imperial_amount=0.5, metric_amount=180.0, metric_unit="g",
                          name="recipe Cornflake Crunch")

    def test_count_with_a_volume_bracket_has_no_weight(self):
        self.assertFields(metric_bracket_volume("2 recipes Crumb [about 3 cups]"), format="count_only",
                          imperial_amount=2.0, metric_amount=None)

    def test_plain_count(self):
        self.assertFields(metric_bracket_volume("1 egg"), format="count_only", imperial_amount=1.0, name="egg")

    def test_rejects(self):
        self.assertRejects(metric_bracket_volume, "", "1. Mix.", "salt to taste")


if __name__ == "__main__":
    unittest.main()
