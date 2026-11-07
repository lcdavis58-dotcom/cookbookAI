"""
Tests for routing chat messages (chat/router.py), the chat's reply
wording (chat/reply.py) and a whole turn (chat/turn.py). Recipes are a
handful of made-up index candidates; the model is patched out.

Run from app/:
    python3 -m unittest discover testing
"""

import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

for _name in ("chromadb", "ollama"):
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = types.ModuleType(_name)

from actions.match import MatchResult  # noqa: E402
from chat import reply, router, store, turn  # noqa: E402
from chat.router import NOT_SURE, Router, list_number, pick_from  # noqa: E402
from chat.state import ChatState, Numbered, Pending, RecipeRef, ScaleUsed  # noqa: E402
from query_utils.title_lookup import candidates_from_index  # noqa: E402

ENTRIES = [
    {"recipe_id": f"r{i}", "book": book, "title": title, "page": 0, "page_confirmed": False}
    for i, (book, title) in enumerate([
        ("The Book On Pie", "Classic Whipped Cream"),
        ("The Complete Cooking For Two Cookbook", "Whipped Cream"),
        ("The Book On Pie", "Chocolate Whipped Cream"),
        ("Dessert Person", "Lemon Curd"),
        ("Momofuku Milk Bar", "Chocolate Cake"),
        ("Book X", "Double Chocolate Cake"),
    ])
]
CANDIDATES = candidates_from_index(ENTRIES)
BY_TITLE = {c.title: c for c in CANDIDATES}


def ref(title):
    return RecipeRef.from_candidate(BY_TITLE[title])


def fresh():
    return ChatState.new()


def on_recipe(title="Classic Whipped Cream", factor=2.0, batch="Full Batch"):
    state = fresh()
    state.focus.recipe = ref(title)
    state.focus.scale = ScaleUsed(factor, batch) if factor else None
    return state


def picking(action="scale", request="double the whipped cream"):
    state = fresh()
    state.focus.numbered = Numbered(action, [ref("Whipped Cream"), ref("Classic Whipped Cream")])
    state.focus.pending = Pending("pick_recipe", action, request)
    return state


def after_match():
    state = fresh()
    state.focus.have = ["pecan", "lemon"]
    state.focus.numbered = Numbered("match", [ref("Lemon Curd")])
    return state


def route(state, message, model_says=None):
    response = {"message": {"tool_calls": [{"function": model_says}]} if model_says else {"message": {}}}
    with mock.patch.object(router.models, "chat", return_value=(response, 0.1)) as chat:
        result = Router(state, CANDIDATES).route(message)
    return result, chat.called


class RulesTest(unittest.TestCase):
    """(message, state, the route's label, or a start of it)."""
    CASES = [
        ("double the classic whipped cream", fresh, "rule: scale named"),
        ("double the double chocolate cake", fresh, "rule: scale named"),
        ("show me the double chocolate cake", fresh, "rule: ask find"),
        ("classic whipped cream", fresh, "rule: ask find"),
        ("halve it", fresh, "rule: reply need recipe"),
        ("pecans, cream cheese, lemons", fresh, "rule: match list"),
        ("what can I make with pecans", fresh, "rule: match new"),
        ("I have butter and eggs", fresh, "rule: match new"),
        ("the second one", fresh, "rule: reply no list"),
        ("now halve it", on_recipe, "rule: scale current"),
        ("back to the original", on_recipe, "rule: scale current, as written"),
        ("double the original", on_recipe, "rule: scale current"),
        ("scale it for 12 people", on_recipe, "rule: scale current"),
        ("how long does it keep?", on_recipe, "rule: ask about current"),
        ("what temperature?", on_recipe, "rule: ask about current"),
        ("show me that recipe again", on_recipe, "rule: ask show current"),
        ("triple the lemon curd", on_recipe, "rule: scale named"),
        ("2", picking, "pending: scale #2"),
        ("the classic one", picking, "pending: scale by name"),
        ("the one from cooking for two", picking, "pending: scale by name"),
        ("the 3rd one", picking, "pending: reply out of range"),
        ("add butter", after_match, "rule: match add"),
        ("what about with butter too", after_match, "rule: match add"),
        ("without the lemons", after_match, "rule: match remove"),
        ("without cheese", after_match, "rule: reply nothing to remove"),
        ("ok forget the lemons", after_match, "rule: match remove"),
        ("actually, leave out the pecans", after_match, "rule: match remove"),
        ("show me #1", after_match, "rule: ask show #1"),
        ("scale the first one by 2x", after_match, "rule: scale #1"),
    ]

    def test_cases(self):
        for message, make_state, expected in self.CASES:
            with self.subTest(message=message):
                result, called_model = route(make_state(), message)
                self.assertTrue(result.label.startswith(expected), f"{message!r} -> {result.label}")
                self.assertFalse(called_model)

    def test_unclear_messages_go_to_the_model(self):
        for message, make_state in [("what's for dinner", on_recipe), ("what goes with chocolate cake?", on_recipe),
                                    ("something fancy", fresh),
                                    # Names "Lemon Curd", but asks for more than it.
                                    ("something with lemon curd I can bring to a party", fresh)]:
            with self.subTest(message=message):
                result, called_model = route(make_state(), message)
                self.assertTrue(called_model)
                self.assertEqual((result.action, result.text), ("reply", NOT_SURE))

    def test_scaling_builds_on_the_current_factor(self):
        result, _ = route(on_recipe(factor=2.0), "now halve it")
        self.assertEqual((result.base, result.batch), (2.0, "Full Batch"))
        result, _ = route(on_recipe(factor=2.0), "double the original")
        self.assertEqual(result.base, 1.0)
        result, _ = route(on_recipe(factor=2.0), "back to the original")
        self.assertEqual((result.factor, result.batch), (1.0, "Full Batch"))

    def test_batch_switch_keeps_the_factor(self):
        with mock.patch.object(router, "recipe_batches", return_value=["Half Batch", "Full Batch", "Mile-High Batch"]):
            result, _ = route(on_recipe(factor=2.0), "make it the mile-high batch")
            self.assertEqual((result.batch, result.factor), ("Mile-High Batch", 2.0))
            # "half" names the batch here, it isn't a multiplier.
            result, _ = route(on_recipe(factor=3.0), "half batch")
            self.assertEqual((result.batch, result.factor), ("Half Batch", 3.0))
            result, _ = route(on_recipe(factor=3.0), "double the half batch")
            self.assertEqual((result.batch, result.factor, result.base), ("Half Batch", None, 1.0))

    def test_pending_batch(self):
        state = on_recipe(factor=None)
        state.focus.pending = Pending("pick_batch", "scale", "double it", ["Half Batch", "Mile-High Batch"])
        result, _ = route(state, "mile high")
        self.assertEqual((result.batch, result.request, result.remember_as), ("Mile-High Batch", "double it", "double it"))

    def test_need_recipe_is_finished_by_a_name(self):
        state = fresh()
        state.focus.pending = Pending("need_recipe", "scale", "halve it")
        result, _ = route(state, "the lemon curd")
        self.assertEqual((result.label, result.recipe.title, result.request), ("pending: scale named", "Lemon Curd",
                                                                              "halve it"))

    def test_list_number(self):
        for text, n in [("2", 2), ("#3", 3), ("the second one", 2), ("number 4", 4), ("the last one", -1),
                        ("second", 2), ("what should I make first", None), ("for 12 people", None)]:
            self.assertEqual(list_number(text), n, text)

    def test_pick_from(self):
        choices = [BY_TITLE["Whipped Cream"], BY_TITLE["Classic Whipped Cream"]]
        self.assertEqual(pick_from("the classic one", choices).title, "Classic Whipped Cream")
        self.assertIsNone(pick_from("the whipped cream", choices))


class ModelRouteTest(unittest.TestCase):
    def model(self, state, name, args, message="whatever"):
        result, called = route(state, message, {"name": name, "arguments": args})
        self.assertTrue(called)
        return result

    def test_scale_current(self):
        result = self.model(on_recipe(factor=2.0), "scale_recipe", {"request": "make it 50% bigger", "recipe": "current"},
                            "make that one 50% bigger")
        self.assertEqual((result.label, result.base), ("model: scale current", 2.0))

    def test_scale_from_the_original(self):
        result = self.model(on_recipe(factor=2.0), "scale_recipe",
                            {"request": "make 1.5x", "recipe": "current", "from_original": True},
                            "can I get a bigger version of the plain recipe")
        self.assertEqual(result.base, 1.0)

    def test_scale_needs_an_amount_in_the_message(self):
        result = self.model(on_recipe(), "scale_recipe", {"request": "scale it", "recipe": "current"},
                            "what's for dinner")
        self.assertEqual(result.label, "model: reply scale, but no amount")
        self.assertIn("Do you want me to scale Classic Whipped Cream?", result.text)

    def test_current_without_a_recipe_asks(self):
        result = self.model(fresh(), "scale_recipe", {"request": "halve it", "recipe": "current"},
                            "can you make it bigger")
        self.assertEqual((result.action, result.pending.kind), ("reply", "need_recipe"))

    def test_list_number_checked(self):
        result = self.model(after_match(), "find_or_answer", {"question": "show it", "recipe": "5"})
        self.assertEqual(result.label, "model: reply out of range")
        result = self.model(after_match(), "find_or_answer", {"question": "show it", "recipe": "1"})
        self.assertEqual((result.mode, result.recipe.title), ("show", "Lemon Curd"))

    def test_arguments_as_json_text(self):
        result = self.model(after_match(), "find_by_ingredients", '{"ingredients": ["butter"], "mode": "add"}')
        self.assertEqual((result.action, result.request), ("match", "pecan, lemon, butter"))

    def test_unknown_tool_and_questions(self):
        self.assertEqual(self.model(fresh(), "bake_it", {}).text, NOT_SURE)
        self.assertEqual(self.model(fresh(), "ask_user", {"question": "Sweet or savory?"}).text, "Sweet or savory?")

    def test_summary(self):
        state = after_match()
        state.focus.recipe, state.focus.scale = ref("Lemon Curd"), ScaleUsed(2.0)
        summary = Router(state, CANDIDATES).summary()
        self.assertIn("Current recipe: Lemon Curd (Dessert Person), now scaled to 2x", summary)
        self.assertIn("1. Lemon Curd (Dessert Person)", summary)
        self.assertIn("Last ingredients searched: pecan, lemon", summary)


class ReplyAndTurnTest(unittest.TestCase):
    def test_match_results_are_numbered_across_sections(self):
        def found(title):
            return {"entry": {"title": title, "book": "B", "page": 0, "page_confirmed": False},
                    "uses": ["lemon"], "missing": [], "staples_used": [], "optional_on_hand": []}
        text = reply.match_reply(MatchResult("matches", have=["lemon"], ready=[found("A")],
                                             missing_one=[dict(found("C"), missing=["x"])]))
        self.assertIn("  1. A  [B]", text)
        self.assertIn("  2. C  [B]", text)
        self.assertIn("Say a number", text)

    def test_a_turn_is_saved_with_its_route_and_timings(self):
        directory = tempfile.mkdtemp()
        try:
            state = fresh()
            with mock.patch.object(router, "load_candidates", return_value=CANDIDATES):
                result = turn.handle(state, "halve it", directory)
            self.assertEqual(result.text, "Which recipe should I scale?")
            saved = store.load(state.id, directory)
            self.assertEqual([t.role for t in saved.messages], ["user", "assistant"])
            self.assertEqual(saved.messages[1].route, "rule: reply need recipe")
            self.assertEqual(saved.messages[1].model_calls, [])
            self.assertEqual(saved.focus.pending, Pending("need_recipe", "scale", "halve it"))
        finally:
            shutil.rmtree(directory)


if __name__ == "__main__":
    unittest.main()
