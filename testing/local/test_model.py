"""
The jobs the chat model does, against the real model: reading a scaling
request, routing a message the rules don't catch, and answering from the
books. The model isn't fully predictable, so a single failure can be
chance; MODEL_REPEAT=5 asks each case 5 times to see how reliable it is.
Takes a minute or two. Not run by the pre-push hook.

Recipes for the scaling cases are made up; the search and chat cases use
the real database and index.

Run from app/:
    python3 -m unittest testing.local.test_model
    MODEL_REPEAT=5 python3 -m unittest testing.local.test_model
"""

import unittest

from actions import ask
from books.line_styles import metric_slash
from chat import turn
from chat.router import route
from chat.state import ChatState
from query_utils.title_lookup import candidates_from_index
from scale_utils.recipe_scaling import determine_scale_intent, resolve_scale_factor
from testing.local.needs import MODEL_REPEAT, needs_database, needs_model, needs_search

CAKE = [metric_slash(line) for line in (
    "300 g / 2 cups all-purpose flour",
    "100 g / ½ cup granulated sugar",
    "2 large eggs",
    "226 g / 1 cup unsalted butter",
    "240 g / 1 cup whole milk",
)]
CAKE_YIELD = "SERVES 8"


def scale_factor(request):
    intent, _ = determine_scale_intent(request, "Test Cake", CAKE_YIELD, CAKE)
    if intent is None:
        return None, "the model didn't call the tool"
    factor, explanation = resolve_scale_factor(intent, CAKE, CAKE_YIELD, request)
    return factor, f"{explanation} (model said {intent})"


@needs_model
class ScaleIntentTest(unittest.TestCase):
    def check(self, request, expected):
        for _ in range(MODEL_REPEAT):
            factor, explanation = scale_factor(request)
            self.assertIsInstance(factor, float, explanation)
            self.assertAlmostEqual(factor, expected, places=3, msg=explanation)

    def test_yield_from_the_recipe(self):
        for request, expected in (("make it for 4 people", 0.5), ("I need enough for 16", 2.0),
                                  ("scale it to serve 6", 0.75), ("this feeds 8, I need to feed 12", 1.5)):
            with self.subTest(request=request):
                self.check(request, expected)

    def test_yield_she_states(self):
        self.check("this usually feeds 5 people, make it feed 8", 1.6)

    @unittest.skip("known gap, planned for 1.1.2: the model uses the yield line's 8, not her 4")
    def test_yield_she_states_known_gap(self):
        self.check("it normally serves 4, i want 10", 2.5)

    def test_ingredient_she_has(self):
        for request, expected in (("I only have 1 egg", 0.5), ("i've got 3 eggs", 1.5),
                                  ("I only have 50 g of butter", 50 / 226), ("I have 150 grams of sugar", 1.5)):
            with self.subTest(request=request):
                self.check(request, expected)

    def test_multipliers_in_words(self):
        for request, expected in (("cut it to a third", 1 / 3), ("make two and a half batches", 2.5)):
            with self.subTest(request=request):
                self.check(request, expected)


ENTRIES = [{"recipe_id": f"r{i}", "book": book, "title": title, "page": 0, "page_confirmed": False}
           for i, (book, title) in enumerate([
               ("The Book On Pie", "Classic Whipped Cream"),
               ("Dessert Person", "Lemon Curd"),
               ("Momofuku Milk Bar", "Chocolate Cake"),
           ])]
CANDIDATES = candidates_from_index(ENTRIES)


@needs_model
class RoutingTest(unittest.TestCase):
    """Messages the rules don't catch, so the model routes them."""

    def check(self, message, action, has=()):
        for _ in range(MODEL_REPEAT):
            r = route(ChatState.new(), message, candidates=CANDIDATES)
            self.assertEqual((r.how, r.action), ("model", action), r.label)
            for word in has:
                self.assertIn(word, r.request)

    def test_what_can_i_make(self):
        self.check("I have cinnamon and heavy cream.  What can I make?", "match", has=("cinnamon", "heavy cream"))
        self.check("i've got strawberries, rhubarb and some cream, ideas?", "match", has=("strawberr", "rhubarb"))

    def test_question(self):
        self.check("how long does whipped cream keep in the fridge", "ask")

    @unittest.skip("known gap, planned for 1.4.0: the model asks her what she means instead of answering")
    def test_general_question_known_gap(self):
        self.check("what's the difference between baking soda and baking powder?", "ask")


@needs_search
class AnswerTest(unittest.TestCase):
    def test_finds_the_pumpkin_pies(self):
        result = ask.run("show me a pumpkin pie recipe")
        self.assertEqual(result.kind, "choices")
        self.assertEqual(sorted(c.title for c in result.choices),
                         ["Classic Pumpkin Pie", "Pumpkin Pie", "Pumpkin Pie", "Pumpkin Pie with Pecan Crunch"])

    @needs_model
    def test_answers_from_the_books(self):
        result = ask.run("how do I keep a pie crust from getting soggy?")
        self.assertEqual(result.kind, "answer")
        self.assertTrue(result.answer.strip())
        self.assertTrue(result.sources)

    @needs_model
    @unittest.skip("known gap, planned for 1.1.3: a question naming a recipe shows recipes instead of answering")
    def test_question_naming_a_recipe_known_gap(self):
        result = ask.run("how long does whipped cream keep in the fridge")
        self.assertEqual(result.kind, "answer")


@needs_model
@needs_database
class RealChatTest(unittest.TestCase):
    """Replays of real chats, through routing, the actions and the model."""

    @unittest.skip("known gap, planned for 1.1.2: chat 2026-11-12-2131-sz7k got 1.000x and 1.125x")
    def test_pumpkin_pie_for_more_people_known_gap(self):
        state = ChatState.new()
        turn.respond(state, "show me a pumpkin pie recipe")
        self.assertEqual(turn.respond(state, "4").result.recipe.title, "Pumpkin Pie with Pecan Crunch")
        self.assertEqual(turn.respond(state, "this usually feeds 5 people, make it feed 8").result.factor, 1.6)
        self.assertEqual(turn.respond(state, "this usually feeds 2 people, i need it to feed 9").result.factor, 4.5)


if __name__ == "__main__":
    unittest.main()
