import unittest

from match_utils.uses import Use, Uses

PARTS = {"egg": ["egg yolk", "egg white"], "lemon": ["lemon juice", "lemon zest"]}
NOT_VARIETIES = {"chocolate": ["white chocolate"], "cream": ["sour cream", "cream cheese"]}


def req(name, recipes=None, how=None):
    out = {"name": name, "options": name.split(" or ")}
    if recipes:
        out["recipes"], out["how"] = recipes, how or "title"
    return out


def entry(rid, title, ingredients=(), optional=()):
    return {"recipe_id": rid, "title": title, "book": "Test Book",
            "ingredients": [i if isinstance(i, dict) else req(i) for i in ingredients],
            "optional": [req(i) for i in optional]}


GROUPS = {"nut": ["nut", "walnut", "pecan", "peanut butter"], "dairy": ["milk", "butter", "cream"]}
NOT_VARIETIES = dict(NOT_VARIETIES, butter=["peanut butter"], milk=["coconut milk"])


def uses(index):
    return Uses(index, parts=PARTS, not_varieties=NOT_VARIETIES, groups=GROUPS)


class MatchesTest(unittest.TestCase):
    def setUp(self):
        self.u = uses([])

    def test_same_name(self):
        self.assertTrue(self.u.matches("half-and-half", "half-and-half"))

    def test_part_of_a_whole(self):
        self.assertTrue(self.u.matches("egg yolk", "egg"))
        self.assertTrue(self.u.matches("fresh lemon juice", "lemon"))

    def test_part_is_not_the_whole(self):
        self.assertFalse(self.u.matches("egg", "egg yolk"))

    def test_kind_of_it(self):
        self.assertTrue(self.u.matches("bittersweet chocolate", "chocolate"))
        self.assertTrue(self.u.matches("chocolate chips", "chocolate"))
        self.assertTrue(self.u.matches("heavy cream", "cream"))

    def test_plurals(self):
        self.assertTrue(self.u.matches("pecan", "pecans"))

    def test_never_a_kind_of_it(self):
        self.assertFalse(self.u.matches("white chocolate", "chocolate"))
        self.assertFalse(self.u.matches("white chocolate chips", "chocolate"))
        self.assertFalse(self.u.matches("cream cheese", "cream"))

    def test_different_words(self):
        self.assertFalse(self.u.matches("unsweetened cocoa powder", "chocolate"))
        self.assertFalse(self.u.matches("eggplant", "egg"))
        self.assertFalse(self.u.matches("buttermilk", "butter"))


class GroupTest(unittest.TestCase):
    def setUp(self):
        self.u = uses([])

    def test_members_count(self):
        self.assertTrue(self.u.matches("toasted walnut", "nut"))
        self.assertTrue(self.u.matches("mixed nut", "nut"))
        self.assertTrue(self.u.matches("unsalted butter", "dairy"))
        self.assertTrue(self.u.matches("heavy cream", "dairy"))

    def test_not_a_member(self):
        self.assertFalse(self.u.matches("nutmeg", "nut"))
        self.assertFalse(self.u.matches("coconut milk", "dairy"))
        self.assertFalse(self.u.matches("peanut butter", "dairy"))
        self.assertTrue(self.u.matches("peanut butter", "nut"))

    def test_without_nuts_leaves_out_walnuts(self):
        pie = entry("p", "Walnut Pie", ["walnut", "egg"])
        self.assertTrue(uses([pie]).find(pie, "nut").needed)

    def test_title_member(self):
        pie = entry("p", "Pecan Pie", ["corn syrup", "egg"])
        self.assertTrue(uses([pie]).find(pie, "nut").in_title)


class FindTest(unittest.TestCase):
    def test_needed(self):
        pie = entry("p", "Pumpkin Pie", ["pumpkin puree", "half-and-half"])
        use = uses([pie]).find(pie, "half-and-half")
        self.assertEqual(use, Use("half-and-half"))
        self.assertTrue(use.needed)
        self.assertEqual(use.note("half-and-half"), "")

    def test_not_used(self):
        pie = entry("p", "Pumpkin Pie", ["pumpkin puree", "heavy cream"])
        self.assertIsNone(uses([pie]).find(pie, "half-and-half"))

    def test_other_choice_on_the_line(self):
        pie = entry("p", "Pumpkin Pie", ["heavy cream or half-and-half"])
        use = uses([pie]).find(pie, "half-and-half")
        self.assertFalse(use.needed)
        self.assertEqual(use.note("half-and-half"), "or heavy cream")

    def test_optional(self):
        pie = entry("p", "Pumpkin Pie", ["pumpkin puree"], optional=["whipped cream"])
        use = uses([pie]).find(pie, "whipped cream")
        self.assertTrue(use.optional)
        self.assertFalse(use.needed)
        self.assertEqual(use.note("whipped cream"), "optional")

    def test_needed_line_wins_over_optional(self):
        cake = entry("c", "Cake", ["unsalted butter"], optional=["butter"])
        self.assertTrue(uses([cake]).find(cake, "butter").needed)

    def test_kind_named_in_the_note(self):
        cookies = entry("c", "Cookies", ["bittersweet chocolate"])
        self.assertEqual(uses([cookies]).find(cookies, "chocolate").note("chocolate"), "bittersweet chocolate")

    def test_in_a_sub_recipe(self):
        dough = entry("d", "All-Butter Pie Dough", ["unsalted butter", "flour"])
        pie = entry("p", "Apple Pie", ["apple", req("pie dough", ["d"])])
        use = uses([dough, pie]).find(pie, "butter")
        self.assertEqual(use.where, "All-Butter Pie Dough")
        self.assertTrue(use.needed)
        self.assertEqual(use.note("butter"), "unsalted butter, in All-Butter Pie Dough")

    def test_another_linked_recipe_does_without(self):
        butter = entry("d1", "Butter Crust", ["unsalted butter"])
        shortening = entry("d2", "Shortening Crust", ["shortening"])
        pie = entry("p", "Apple Pie", [req("pie crust", ["d1", "d2"], how="kind")])
        use = uses([butter, shortening, pie]).find(pie, "butter")
        self.assertFalse(use.needed)
        self.assertIn("or another pie crust", use.note("butter"))

    def test_bought_instead_of_made(self):
        mayo = entry("m", "Mayonnaise", ["egg yolk", "oil"])
        salad = entry("s", "Egg Salad Sandwich", [req("mayonnaise", ["m"], how="plain"), "bread"])
        use = uses([mayo, salad]).find(salad, "egg")
        self.assertFalse(use.needed)
        self.assertIn("or store-bought mayonnaise", use.note("egg"))

    def test_sub_recipe_loop(self):
        a = entry("a", "Sauce A", [req("sauce b", ["b"])])
        b = entry("b", "Sauce B", [req("sauce a", ["a"])])
        self.assertIsNone(uses([a, b]).find(a, "butter"))

    def test_title_names_it(self):
        cream = entry("w", "Chocolate Whipped Cream", ["heavy cream", "unsweetened cocoa powder"])
        use = uses([cream]).find(cream, "chocolate")
        self.assertTrue(use.in_title)
        self.assertTrue(use.needed)
        self.assertEqual(use.note("chocolate"), "")

    def test_title_naming_something_else(self):
        cake = entry("c", "White Chocolate Cake", ["white chocolate"])
        self.assertIsNone(uses([cake]).find(cake, "chocolate"))


if __name__ == "__main__":
    unittest.main()
