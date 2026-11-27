"""
Routing and answering ingredient filters and flavors in the chat (1.2.0):
"do any of these use half and half", "a pumpkin pie without half and
half", "something pineapple flavored". Recipes are made-up index entries;
the model is patched out.
"""

import sys
import types
import unittest
from unittest import mock

for _name in ("chromadb", "ollama"):
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = types.ModuleType(_name)

from chat import router, turn  # noqa: E402
from chat.router import Router, known_ingredient  # noqa: E402
from chat.state import ChatState, Numbered, RecipeRef  # noqa: E402
from query_utils.title_lookup import candidates_from_index  # noqa: E402


def entry(rid, title, ingredients, dishes=(), book="Test Book"):
    return {"recipe_id": rid, "book": book, "title": title, "page": 1, "page_confirmed": True,
            "ingredients": [{"name": n, "options": n.split(" or ")} for n in ingredients],
            "optional": [], "dishes": list(dishes)}


ENTRIES = [
    entry("p1", "Pumpkin Pie", ["pumpkin puree", "half-and-half", "egg"], ["pie"]),
    entry("p2", "Spiced Pumpkin Pie", ["pumpkin puree", "heavy cream", "egg"], ["pie"]),
    entry("p3", "Pumpkin Pie with Pecan Crunch", ["pumpkin puree", "pecan", "heavy cream"], ["pie"]),
    entry("w1", "Classic Whipped Cream", ["heavy cream", "granulated sugar"]),
    entry("w2", "Chocolate Whipped Cream", ["heavy cream", "unsweetened cocoa powder"]),
    entry("w3", "Mocha Whipped Cream", ["heavy cream", "bittersweet chocolate"]),
    entry("c1", "Brown Butter Snickerdoodles", ["unsalted butter", "granulated sugar", "milk chocolate"],
          ["cookie"]),
    entry("c2", "Sugar Cookies", ["unsalted butter", "granulated sugar"], ["cookie"]),
    entry("a1", "Pineapple Upside-Down Cake", ["pineapple", "unsalted butter"], ["cake"]),
    entry("a2", "Grilled Pineapple Salsa", ["pineapple", "red onion"], ["sauce"]),
]
CANDIDATES = candidates_from_index(ENTRIES)
BY_ID = {c.key: c for c in CANDIDATES}


def ref(rid):
    return RecipeRef.from_candidate(BY_ID[rid])


def fresh():
    return ChatState.new()


def pies_listed():
    state = fresh()
    state.focus.numbered = Numbered("ask", [ref("p1"), ref("p2")], rest=[ref("p3")])
    return state


def after_match():
    state = fresh()
    state.focus.have = ["pecan", "pumpkin"]
    state.focus.numbered = Numbered("match", [ref("p3")])
    return state


def route(state, message, model_says=None):
    response = {"message": {"tool_calls": [{"function": model_says}]} if model_says else {"message": {}}}
    with mock.patch.object(router.models, "chat", return_value=(response, 0.1)) as chat:
        result = Router(state, CANDIDATES).route(message)
    return result, chat.called


class RouteTest(unittest.TestCase):
    CASES = [
        ("do any of these 3 recipes use half and half", pies_listed, "rule: ask filter list with half and half"),
        ("which ones don't use eggs?", pies_listed, "rule: ask filter list without eggs"),
        ("the ones without half and half", pies_listed, "rule: ask filter list without half and half"),
        ("without half and half", pies_listed, "rule: ask filter list without half and half"),
        ("what about without heavy cream", pies_listed, "rule: ask filter list without heavy cream"),
        ("do they have pecans in them", pies_listed, "rule: ask filter list with pecans"),
        ("a pumpkin pie without half and half", fresh, "rule: ask filter pumpkin pie without half and half"),
        ("do i have a whipped cream recipe that uses chocolate", fresh,
         "rule: ask filter whipped cream with chocolate"),
        ("show me whipped cream with chocolate", fresh, "rule: ask filter whipped cream with chocolate"),
        ("is there a pumpkin pie with no eggs?", fresh, "rule: ask filter pumpkin pie without eggs"),
        ("something with a pineapple flavor, what can I make", fresh, "rule: ask flavor"),
        ("any pineapple-flavored desserts?", fresh, "rule: ask flavor"),
        ("do any of these use butter", fresh, "rule: reply filter, no list"),
        # Not filters
        ("without the pecans", after_match, "rule: match remove ['pecan']"),
        ("show me the pumpkin pie with pecan crunch", fresh, "rule: ask find"),
        ("what can I make with pecans", fresh, "rule: match new"),
        ("double the pumpkin pie with half and half", fresh, "rule: scale named"),
    ]

    def test_routes(self):
        for message, make_state, expected in self.CASES:
            with self.subTest(message=message):
                result, _ = route(make_state(), message)
                self.assertEqual(result.label, expected)

    def test_not_an_ingredient(self):
        for message in ("how do I make pumpkin pie without an oven", "pumpkin pie without a lattice top"):
            with self.subTest(message=message):
                result, _ = route(fresh(), message)
                self.assertNotIn("filter", result.label)

    def test_new_filter_while_picking_from_a_list(self):
        state = pies_listed()
        state.focus.pending = router.Pending("pick_recipe", "ask", "pumpkin pie")
        result, _ = route(state, "whipped cream with chocolate")
        self.assertEqual(result.label, "rule: ask filter whipped cream with chocolate")
        result, _ = route(state, "the spiced one")
        self.assertEqual(result.label, "pending: ask by name")

    def test_the_one_with_is_not_a_dish(self):
        result, _ = route(pies_listed(), "the one with pecans")
        self.assertNotIn("filter pecans", result.label)
        self.assertNotIn("filter the one", result.label)

    def test_list_filter_covers_the_part_not_shown(self):
        result, _ = route(pies_listed(), "do any of these use pecans")
        self.assertEqual([c.key for c in result.choices], ["p1", "p2", "p3"])

    def test_dish_found_by_its_label(self):
        result, _ = route(fresh(), "cookies with chocolate")
        self.assertEqual(result.what, "cookies")
        self.assertEqual({c.key for c in result.choices}, {"c1", "c2"})

    def test_flavor_lists_titles(self):
        result, _ = route(fresh(), "something pineapple flavored")
        self.assertEqual((result.mode, result.find_text), ("list", "pineapple"))


class KnownIngredientTest(unittest.TestCase):
    def test_known(self):
        self.assertEqual(known_ingredient("the half and half", CANDIDATES), "half and half")
        self.assertEqual(known_ingredient("eggs", CANDIDATES), "eggs")

    def test_a_group_is_known(self):
        self.assertEqual(known_ingredient("dairy", CANDIDATES), "dairy")
        self.assertEqual(known_ingredient("nuts", CANDIDATES), "nuts")

    def test_not_known(self):
        self.assertIsNone(known_ingredient("an oven", CANDIDATES))
        self.assertIsNone(known_ingredient("this recipe", CANDIDATES))
        self.assertIsNone(known_ingredient("lots of pecans and other stuff", CANDIDATES))


class ModelFilterTest(unittest.TestCase):
    def call(self, **args):
        return {"name": "filter_recipes", "arguments": args}

    def test_dish(self):
        result, _ = route(fresh(), "got a pie that skips the dairy half and half?",
                          self.call(ingredient="half and half", without=True, dish="pumpkin pie"))
        self.assertEqual(result.label, "model: ask filter pumpkin pie without half and half")

    def test_last_list(self):
        result, _ = route(pies_listed(), "any of em got pecans",
                          self.call(ingredient="pecans", without="false", dish="none"))
        self.assertEqual(result.label, "model: ask filter list with pecans")

    def test_no_dish_and_no_list_filters_every_recipe(self):
        # Flag 1ncny: 1.2.0 asked for a dish here.
        result, _ = route(fresh(), "show recipes that use a lot of pecans",
                          self.call(ingredient="pecans", without=False))
        self.assertEqual(result.label, "model: ask filter all with pecans")
        self.assertTrue(result.every)
        self.assertEqual(len(result.choices), len(CANDIDATES))
        # The rule too, with "anything" where a dish would be.
        result, _ = route(fresh(), "anything made with pecans")
        self.assertEqual(result.label, "rule: ask filter all with pecans")
        # Naming a food isn't asking for recipes with it: answered.
        result, _ = route(fresh(), "what goes well with pecans?", self.call(ingredient="pecans", without=False))
        self.assertEqual(result.label, "model: ask filter_recipes, not an ingredient or dish, so answered")

    def test_these_or_without_and_no_list_asks_for_a_dish(self):
        for args in ({"dish": "these", "without": False}, {"without": True}):
            with self.subTest(args=args):
                result, _ = route(fresh(), "anything pecan-ish for me", self.call(ingredient="pecans", **args))
                self.assertEqual(result.label, "model: reply filter, no list")

    def test_not_an_ingredient(self):
        result, _ = route(fresh(), "pie but not in an oven", self.call(ingredient="oven", without=True, dish="pie"))
        self.assertEqual(result.label, "model: ask filter_recipes, not an ingredient or dish, so answered")
        self.assertEqual(result.find_text, "pie but not in an oven")


class TurnTest(unittest.TestCase):
    def respond(self, state, message):
        with mock.patch.object(router.models, "chat", return_value=({"message": {}}, 0.1)):
            return turn.respond(state, message, CANDIDATES)

    def test_filter_then_pick(self):
        state = fresh()
        result = self.respond(state, "a pumpkin pie without half and half")
        self.assertIn("2 pumpkin pie recipes without half and half:", result.text)
        self.assertIn("  2. Spiced Pumpkin Pie  (Test Book)", result.text)
        self.assertEqual([r.title for r in state.focus.numbered.items],
                         ["Pumpkin Pie with Pecan Crunch", "Spiced Pumpkin Pie"])
        with mock.patch("actions.ask.candidate_text", return_value="Spiced Pumpkin Pie\nthe recipe"):
            shown = self.respond(state, "2")
        self.assertEqual(state.focus.recipe.title, "Spiced Pumpkin Pie")
        self.assertIn("Spiced Pumpkin Pie, from Test Book", shown.text)

    def test_title_counts_for_the_ingredient(self):
        result = self.respond(fresh(), "do i have a whipped cream recipe that uses chocolate")
        self.assertIn("Chocolate Whipped Cream", result.text)
        self.assertIn("Mocha Whipped Cream - bittersweet chocolate", result.text)
        self.assertNotIn("Classic Whipped Cream", result.text)

    def test_every_recipe_reply(self):
        with mock.patch.object(router.models, "chat", return_value=(
                {"message": {"tool_calls": [{"function": self.call_args("pecans")}]}}, 0.1)):
            result = turn.respond(fresh(), "show recipes that use pecans", CANDIDATES)
        self.assertIn("1 recipe uses pecans:", result.text)
        self.assertNotIn("The other", result.text)

    @staticmethod
    def call_args(ingredient):
        return {"name": "filter_recipes", "arguments": {"ingredient": ingredient, "without": False}}

    def test_none_keeps_the_list(self):
        state = pies_listed()
        result = self.respond(state, "do any of these use pineapple")
        self.assertEqual(result.text, "None of these use pineapple.")
        self.assertEqual(len(state.focus.numbered.items), 2)

    def test_flavor_reply(self):
        with mock.patch("actions.ask.load_candidates", return_value=(CANDIDATES, "index")):
            result = self.respond(fresh(), "something with a pineapple flavor, what can I make")
        self.assertIn("You have 2 pineapple recipes:", result.text)


if __name__ == "__main__":
    unittest.main()
