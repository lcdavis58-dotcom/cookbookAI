"""
Checks on the model's answers (actions/answer_checks.py) and the one
retry in actions/ask.py. The excerpts here are made up, not book text.

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
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

from actions import answer_checks, ask  # noqa: E402
from chat import reply  # noqa: E402
from common import models  # noqa: E402

TEXT = ("Test Cake\nMAKES 12\n1½ cups (300 g) sugar\n2 large eggs\n1. Bake 25 to 30 minutes at 350°F.\n"
        "2. Cool for 1 hour in a 9-inch pan.")
SOURCES = [{"book": "Dessert Person", "page": 112, "page_confirmed": True, "distance": 0.1, "text": TEXT},
           {"book": "The Food Lab", "page": 0, "page_confirmed": False, "distance": 0.2,
            "text": "Toast 3 slices of bread."}]


def problems(answer, question=""):
    return [(p["kind"], p["what"]) for p in answer_checks.check(answer, SOURCES, question)]


class QuantitiesTest(unittest.TestCase):
    def test_forms_of_a_number(self):
        found = answer_checks.quantities("1½ cups, 1 1/2 cups, 1-1/2 cups, 1.5 cups, ½ cup, 3/4 tsp")
        self.assertEqual([(v, u) for v, u, _ in found],
                         [(1.5, "cup")] * 4 + [(0.5, "cup"), (0.75, "tsp")])

    def test_units(self):
        found = answer_checks.quantities("350°F, 180 °C, 300 g, 2 tbsp, 9-inch, 12 minutes, 2 large eggs")
        self.assertEqual([u for _, u, _ in found], ["degf", "degc", "g", "tbsp", "inch", "min", None])

    def test_a_range_shares_its_unit(self):
        found = answer_checks.quantities("bake 25 to 30 minutes, 2-3 cups")
        self.assertEqual([(v, u) for v, u, _ in found], [(25, "min"), (30, "min"), (2, "cup"), (3, "cup")])

    def test_list_and_page_numbers_left_out(self):
        self.assertEqual(answer_checks.quantities("1. Mix.\n2) Bake, see page 40, p. 41."), [])
        self.assertEqual(len(answer_checks.quantities("1. Mix.", skip_lists=False)), 1)


class CheckTest(unittest.TestCase):
    def test_a_faithful_answer_passes(self):
        self.assertEqual(problems("Use 1 1/2 cups (300 g) sugar and 2 eggs. Bake 25 minutes at 350 degrees F "
                                  "in a 9-inch pan (Dessert Person, page 112). Step 2 says to cool it."), [])

    def test_amounts_not_in_the_excerpts(self):
        self.assertEqual(problems("Use 2 cups sugar and bake 40 minutes."),
                         [("quantity", "2 cups"), ("quantity", "40 minutes")])

    def test_the_same_number_with_another_unit(self):
        # 300 g is in the excerpt; 300 cups isn't.
        self.assertEqual(problems("Use 300 cups sugar."), [("quantity", "300 cups")])

    def test_a_number_she_typed_is_fine(self):
        self.assertEqual(problems("For 24 people, use the recipe twice.", "make it serve 24"), [])

    def test_pages(self):
        self.assertEqual(problems("See page 112."), [])
        self.assertEqual(problems("See page 40, and p. 113."), [("page", "page 40"), ("page", "page 113")])

    def test_books(self):
        self.assertEqual(problems("From Dessert Person and The Food Lab."), [])
        self.assertEqual(problems("BraveTart has one too, and so does salt fat acid heat."),
                         [("book", "BraveTart"), ("book", "Salt Fat Acid Heat")])

    def test_ratio_only_as_a_name(self):
        self.assertEqual(problems("The ratio of flour to water matters. Ratio is a word too."), [])
        self.assertEqual(problems("This is like the one in Ratio."), [("book", "Ratio")])

    def test_wording(self):
        found = answer_checks.check("2 cups, page 40, BraveTart", SOURCES)
        self.assertEqual(answer_checks.for_her(found), "(Check this against the recipe: I couldn't find 2 cups "
                                                        "in the book text I read; I didn't read page 40 or "
                                                        "BraveTart for this.)")
        self.assertIn("2 cups is not in the excerpts", answer_checks.for_the_model(found))


class RetryTest(unittest.TestCase):
    def answer(self, *replies):
        models.clear()
        calls = iter(replies)

        def chat(job, messages, **_):
            self.messages = messages
            models.CALLS.append({"job": job, "model": "test", "seconds": 1.0})
            return {"message": {"content": next(calls)}}, 1.0

        with mock.patch.object(models, "chat", side_effect=chat):
            return ask._answer("Question: how much sugar?", SOURCES, "how much sugar?")

    def test_a_good_answer_is_asked_once(self):
        answer, seconds, left = self.answer("1½ cups (300 g).")
        self.assertEqual((answer, seconds, left), ("1½ cups (300 g).", 1.0, []))
        self.assertEqual(models.CALLS, [{"job": "answer", "model": "test", "seconds": 1.0, "checks": []}])

    def test_a_bad_answer_is_asked_again(self):
        answer, seconds, left = self.answer("2 cups.", "1½ cups.")
        self.assertEqual((answer, seconds, left), ("1½ cups.", 2.0, []))
        self.assertEqual([(c["job"], c["checks"]) for c in models.CALLS],
                         [("answer", [{"kind": "quantity", "what": "2 cups"}]), ("answer again", [])])
        self.assertEqual([m["role"] for m in self.messages], ["system", "user", "assistant", "user"])
        self.assertIn("2 cups is not in the excerpts", self.messages[-1]["content"])

    def test_still_wrong_is_shown_with_a_note(self):
        answer, _, left = self.answer("2 cups.", "3 cups.")
        self.assertEqual(left, [{"kind": "quantity", "what": "3 cups"}])
        result = ask.AskResult("answer", "how much sugar?", answer=answer, sources=SOURCES, unchecked=left)
        self.assertIn("(Check this against the recipe: I couldn't find 3 cups", reply.ask_reply(result))
        self.assertIn("I couldn't find 3 cups", ask.render(result))


if __name__ == "__main__":
    unittest.main()
