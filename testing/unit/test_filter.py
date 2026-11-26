import unittest
from unittest import mock

from actions import ask, filter as recipe_filter
from chat import reply
from query_utils.title_lookup import candidates_from_index


def req(name, recipes=None, how="title"):
    out = {"name": name, "options": name.split(" or ")}
    if recipes:
        out["recipes"], out["how"] = recipes, how
    return out


def entry(rid, title, ingredients=(), optional=(), book="Test Book"):
    return {"recipe_id": rid, "title": title, "book": book,
            "ingredients": [i if isinstance(i, dict) else req(i) for i in ingredients],
            "optional": [req(i) for i in optional]}


PIES = [
    entry("p1", "Pumpkin Pie", ["pumpkin puree", "half-and-half"]),
    entry("p2", "Spiced Pumpkin Pie", ["pumpkin puree", "heavy cream or half-and-half"]),
    entry("p3", "Classic Pumpkin Pie", ["pumpkin puree", "heavy cream"]),
    entry("p4", "Honey Pumpkin Pie", ["pumpkin puree", "evaporated milk"], optional=["half-and-half"]),
]


def run(entries, ingredient, **kwargs):
    with mock.patch("match_utils.uses.load_parts", return_value={}), \
            mock.patch("match_utils.uses.load_not_varieties", return_value={"chocolate": ["white chocolate"]}):
        return recipe_filter.run(candidates_from_index(entries), ingredient, **kwargs)


def titles(result):
    return [c.title for c in result.choices]


class UsesItTest(unittest.TestCase):
    def test_lists_the_ones_that_use_it(self):
        result = run(PIES, "half and half")
        self.assertEqual(result.kind, "choices")
        self.assertEqual(titles(result), ["Pumpkin Pie", "Spiced Pumpkin Pie", "Honey Pumpkin Pie"])
        self.assertEqual(result.heading, "3 of these use half and half:")
        self.assertEqual(result.footer, "The other 1 doesn't.")
        self.assertEqual(result.notes, {"p2": "or heavy cream", "p4": "optional"})

    def test_a_dish_named(self):
        result = run(PIES[:1], "half and half", what="pumpkin pie")
        self.assertEqual(result.heading, "1 pumpkin pie recipe uses half and half:")
        self.assertEqual(result.footer, "")

    def test_none_use_it(self):
        result = run(PIES, "chocolate")
        self.assertEqual(result.kind, "said")
        self.assertEqual(result.heading, "None of these use chocolate.")
        self.assertEqual(run(PIES, "chocolate", what="pumpkin pie").heading,
                         "None of your pumpkin pie recipes use chocolate.")

    def test_kind_shown_in_the_note(self):
        creams = [entry("w1", "Whipped Cream", ["heavy cream", "bittersweet chocolate"]),
                  entry("w2", "Chocolate Whipped Cream", ["heavy cream", "cocoa powder"]),
                  entry("w3", "White Chocolate Whipped Cream", ["heavy cream", "white chocolate"])]
        result = run(creams, "chocolate", what="whipped cream")
        self.assertEqual(titles(result), ["Whipped Cream", "Chocolate Whipped Cream"])
        self.assertEqual(result.notes, {"w1": "bittersweet chocolate"})


class WithoutItTest(unittest.TestCase):
    def test_lists_the_ones_without_it(self):
        result = run(PIES, "half and half", without=True)
        self.assertEqual(titles(result), ["Spiced Pumpkin Pie", "Classic Pumpkin Pie", "Honey Pumpkin Pie"])
        self.assertEqual(result.heading, "3 of these don't use half and half:")
        self.assertEqual(result.notes, {"p2": "it can use heavy cream instead",
                                        "p4": "the half and half is optional"})
        self.assertEqual(result.footer, "")

    def test_a_dish_named(self):
        result = run(PIES, "half and half", without=True, what="pumpkin pie")
        self.assertEqual(result.heading, "3 pumpkin pie recipes without half and half:")

    def test_none_of_them_use_it(self):
        self.assertEqual(run(PIES[2:3], "chocolate", without=True).heading, "None of these use chocolate:")

    def test_all_use_it(self):
        result = run(PIES[:1] * 2, "half and half", without=True)
        self.assertEqual(result.kind, "said")
        self.assertEqual(result.heading, "All 2 of these use half and half.")
        self.assertEqual(run(PIES[:1], "half and half", without=True, what="pumpkin pie").heading,
                         "That one uses half and half.")

    def test_swap_a_sub_recipe(self):
        butter = entry("d1", "Butter Crust", ["unsalted butter"])
        shortening = entry("d2", "Shortening Crust", ["shortening"])
        pie = entry("p", "Apple Pie", [req("pie crust", ["d1", "d2"], how="kind"), "apple"])
        with mock.patch("match_utils.uses.load_parts", return_value={}), \
                mock.patch("match_utils.uses.load_not_varieties", return_value={}):
            result = recipe_filter.run(candidates_from_index([pie]), "butter", without=True,
                                       index=[butter, shortening, pie])
        self.assertEqual(result.notes, {"p": "it has butter in Butter Crust, but another pie crust works"})


class LongListTest(unittest.TestCase):
    def test_past_thirty_goes_to_rest(self):
        many = [entry(f"c{i}", f"Cookie {i}", ["butter"]) for i in range(35)]
        result = run(many, "butter")
        self.assertEqual(len(result.choices), 30)
        self.assertEqual(len(result.rest), 5)
        self.assertEqual(result.more, 5)


class ReplyTest(unittest.TestCase):
    def test_chat_reply(self):
        text = reply.ask_reply(run(PIES, "half and half"))
        self.assertIn("  2. Spiced Pumpkin Pie - or heavy cream  (Test Book)", text)
        self.assertIn("  3. Honey Pumpkin Pie - optional  (Test Book)\nThe other 1 doesn't.", text)

    def test_said(self):
        self.assertEqual(reply.ask_reply(run(PIES, "chocolate")), "None of these use chocolate.")
        self.assertEqual(ask.render(run(PIES, "chocolate")), "None of these use chocolate.")

    def test_command_line_footer(self):
        self.assertIn("The other 1 doesn't.", ask.render(run(PIES, "half and half")))


if __name__ == "__main__":
    unittest.main()
