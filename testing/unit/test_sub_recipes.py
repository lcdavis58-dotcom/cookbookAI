"""
Tests for sub-recipe linking (match_utils/sub_recipes.py) and matching
through sub-recipes (match_utils/matching.py), on an invented book.

Run from app/:
    python3 -m unittest discover testing
"""

import copy
import unittest

from match_utils.ingredient_names import options
from match_utils.matching import Matcher
from match_utils.sub_recipes import link_sub_recipes, plain_ingredient, short_name

KINDS = {"pie dough": ["pie dough", "pie crust", "piecrust"], "mayonnaise": ["mayonnaise", "mayo"]}
BOOK = "The Invented Kitchen"


def recipe(rid, title, needs=(), refs=(), optional_refs=(), book=BOOK):
    return {"recipe_id": rid, "book": book, "title": title, "match_title": title, "aliases": [],
            "ingredients": [{"name": n, "options": options(n)} for n in needs], "optional": [],
            "sub_recipes": list(refs) + list(optional_refs), "optional_sub_recipes": list(optional_refs),
            "your_choice": []}


BASE = [
    recipe("dough", "Flaky Pie Dough", needs=["flour", "unsalted butter"]),
    recipe("cream", "Lemon Cream", needs=["lemon", "heavy cream"]),
    recipe("pie", "Lemon Cream Pie", needs=["egg"],
           refs=["recipe Flaky Pie Dough, chilled", "Lemon Cream (this page)"]),
    recipe("tart", "Berry Slab Pie", needs=["blackberry"],
           refs=["9-inch pie crust (see Our Crusts), parbaked"]),
    recipe("mayo", "Mayonnaise", needs=["egg yolk", "neutral oil"]),
    recipe("salad", "Potato Salad", needs=["potato", "mayonnaise"]),
    recipe("cake", "Spice Cake", needs=["egg"], refs=["all-purpose flour (see this page)"]),
    recipe("a", "Sauce A", needs=["egg"], refs=["recipe Sauce B"]),
    recipe("b", "Sauce B", needs=["milk"], refs=["recipe Sauce A"]),
    recipe("junk", "Bean Soup", needs=["bean"],
           refs=["minutes, then see the note after this recipe. Stir well."]),
    recipe("other", "Lemon Cream", needs=["lime"], book="Another Book"),
    recipe("brioche", "Brioche Plum Tart", needs=["plum"], refs=["recipe Brioche Dough, cold"]),
    recipe("cheese", "Farmer Cheese, the Quick Way", needs=["whole milk"]),
    recipe("toast", "Cheese Toast", needs=["bread"],
           refs=["recipe Farmer Cheese, the Quick Way, or store-bought ricotta"]),
]


def linked():
    return link_sub_recipes(copy.deepcopy(BASE), KINDS)


def by_id(entries):
    return {e["recipe_id"]: e for e in entries}


def matcher(have, staples=("flour", "unsalted butter", "neutral oil")):
    return Matcher(have, staples=set(staples), parts={"egg": ["egg yolk"]}, not_varieties={},
                   index=linked(), kinds=KINDS)


class Names(unittest.TestCase):
    def test_short_name(self):
        self.assertEqual(short_name("recipe Brioche Dough, cold"), "Brioche Dough")
        self.assertEqual(short_name("Mile-High Batch of Meringue Topping"), "Meringue Topping")
        self.assertEqual(short_name("rectangular portion Flaky Dough (this page), chilled"), "Flaky Dough")

    def test_plain_ingredient(self):
        self.assertEqual(plain_ingredient("all-purpose flour (see this page)"), "all-purpose flour")
        self.assertIsNone(plain_ingredient("recipe Snow Cream (page 12)"))
        self.assertIsNone(plain_ingredient("Fig Jam (recipe follows)"))
        self.assertIsNone(plain_ingredient("minutes, then see the note after this recipe. Stir well."))


class Linking(unittest.TestCase):
    def setUp(self):
        self.e = by_id(linked())

    def test_reference_by_title(self):
        pie = self.e["pie"]
        refs = {r["name"]: r for r in pie["ingredients"] if r.get("recipes")}
        self.assertEqual(refs["Flaky Pie Dough"]["recipes"], ["dough"])
        self.assertEqual(refs["Flaky Pie Dough"]["how"], "title")
        self.assertEqual(refs["Flaky Pie Dough"]["kinds"], ["pie dough"])
        self.assertEqual(refs["Lemon Cream"]["recipes"], ["cream"])   # never the other book's
        self.assertEqual(pie["sub_recipes"], [])

    def test_reference_by_kind(self):
        crust = [r for r in self.e["tart"]["ingredients"] if r.get("recipes")][0]
        self.assertEqual((crust["recipes"], crust["how"]), (["dough"], "kind"))

    def test_plain_buy_or_make(self):
        mayo = [r for r in self.e["salad"]["ingredients"] if r["name"] == "mayonnaise"][0]
        self.assertEqual((mayo["recipes"], mayo["how"]), (["mayo"], "plain"))
        self.assertEqual(mayo["options"], ["mayonnaise"])

    def test_page_note_is_an_ingredient(self):
        names = [r["name"] for r in self.e["cake"]["ingredients"]]
        self.assertIn("all-purpose flour", names)
        self.assertEqual(self.e["cake"]["sub_recipes"], [])

    def test_step_text_set_aside(self):
        self.assertEqual(len(self.e["junk"]["unread_lines"]), 1)
        self.assertEqual(self.e["junk"]["sub_recipes"], [])
        self.assertEqual([r["name"] for r in self.e["junk"]["ingredients"]], ["bean"])

    def test_unlinked_reference_is_a_requirement(self):
        tart = self.e["brioche"]
        self.assertEqual(tart["sub_recipes"], ["recipe Brioche Dough, cold"])
        self.assertIn({"name": "Brioche Dough", "options": ["brioche dough"], "how": "unlinked"},
                      tart["ingredients"])

    def test_title_with_a_comma(self):
        ref = [r for r in self.e["toast"]["ingredients"] if r.get("recipes")][0]
        self.assertEqual(ref["recipes"], ["cheese"])

    def test_pan_size_dropped_from_name(self):
        self.assertEqual(short_name("9-inch / 23-cm pie crust (see Our Crusts), parbaked"), "pie crust")

    def test_kinds_of_recipes(self):
        self.assertEqual(self.e["dough"]["kinds"], ["pie dough"])
        self.assertEqual(self.e["cream"]["kinds"], [])


class Matching(unittest.TestCase):
    def check(self, have, rid):
        m = matcher(have)
        return m.check_recipe(by_id(m.by_id.values())[rid])

    def test_makes_sub_recipes(self):
        r = self.check(["lemon", "heavy cream", "egg"], "pie")
        self.assertEqual(r["missing"], [])
        self.assertEqual(r["makes"], ["Flaky Pie Dough", "Lemon Cream"])
        self.assertEqual(sorted(r["uses"]), ["egg", "heavy cream", "lemon"])

    def test_missing_inside_sub_recipe(self):
        r = self.check(["egg"], "pie")
        self.assertEqual(r["missing"], ["lemon, for Lemon Cream", "heavy cream, for Lemon Cream"])

    def test_general_form_covers_it(self):
        r = matcher(["egg", "lemon", "heavy cream", "pie crust"], staples=()).check_recipe(
            by_id(linked())["pie"])
        self.assertEqual(r["missing"], [])
        self.assertEqual(r["stand_ins"], ["your pie crust for Flaky Pie Dough"])
        self.assertEqual(r["assumptions"], [])
        self.assertEqual(r["makes"], ["Lemon Cream"])

    def test_generic_crust_from_staples(self):
        r = self.check(["blackberry"], "tart")
        self.assertEqual((r["missing"], r["makes"]), ([], ["Flaky Pie Dough"]))
        self.assertEqual(r["from_scratch"], ["Flaky Pie Dough"])

    def test_sub_recipe_using_listed_items_is_not_from_scratch(self):
        r = self.check(["lemon", "heavy cream", "egg"], "pie")
        self.assertEqual(r["from_scratch"], ["Flaky Pie Dough"])   # the cream used your lemons

    def test_unlinked_counts_as_missing(self):
        r = self.check(["plum"], "brioche")
        self.assertEqual(r["missing"], ["Brioche Dough"])
        r = self.check(["plum", "brioche dough"], "brioche")
        self.assertEqual(r["missing"], [])

    def test_buy_or_make(self):
        made = self.check(["potato", "egg"], "salad")
        self.assertEqual((made["missing"], made["makes"]), ([], ["Mayonnaise"]))
        bought = matcher(["potato", "mayonnaise"], staples=()).check_recipe(by_id(linked())["salad"])
        self.assertEqual((bought["missing"], bought["makes"]), ([], []))
        neither = matcher(["potato"], staples=()).check_recipe(by_id(linked())["salad"])
        self.assertEqual(neither["missing"], ["mayonnaise"])

    def test_sub_recipe_only_use_counts(self):
        # Lemons only go into the Lemon Cream, but the pie still uses them.
        r = self.check(["lemon"], "pie")
        self.assertEqual(r["uses"], ["lemon"])

    def test_cycle_stops(self):
        r = self.check(["egg", "milk"], "a")
        self.assertIsNotNone(r)


if __name__ == "__main__":
    unittest.main()
