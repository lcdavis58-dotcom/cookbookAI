"""
Narrowing a long list down (chat/narrow.py, 1.2.0): past 30 recipes the
chat asks how to narrow it, suggests title words and books, and reads her
answer inside the same recipes, whether or not it was a suggestion.
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

from chat import narrow, router, turn  # noqa: E402
from chat.state import ChatState  # noqa: E402
from query_utils.title_lookup import candidates_from_index  # noqa: E402


def entry(rid, title, ingredients=("unsalted butter", "granulated sugar"), book="Cookie Book", dishes=("cookie",)):
    return {"recipe_id": rid, "book": book, "title": title, "page": 1, "page_confirmed": True,
            "ingredients": [{"name": n, "options": [n]} for n in ingredients], "optional": [],
            "dishes": list(dishes)}


ENTRIES = (
    [entry(f"cc{i}", f"Chocolate Chip Cookies {i}", ["unsalted butter", "chocolate chips", "egg"]) for i in range(12)]
    + [entry(f"pb{i}", f"Peanut Butter Cookies {i}", ["peanut butter", "egg", "peanut"], book="Pie Book")
       for i in range(8)]
    + [entry(f"oc{i}", f"Oatmeal Cookies {i}", ["rolled oat", "unsalted butter"]) for i in range(8)]
    + [entry(f"sd{i}", f"Snickerdoodles {i}", book="Pie Book") for i in range(6)]
    + [entry("pie", "Apple Pie", ["apple", "unsalted butter"], dishes=("pie",)),
       entry("wc", "Classic Whipped Cream", ["heavy cream"], dishes=())]
)
CANDIDATES = candidates_from_index(ENTRIES)
COOKIES = [c for c in CANDIDATES if "cookie" in c.payload["dishes"]]


def respond(state, message):
    with mock.patch.object(router.models, "chat", return_value=({"message": {}}, 0.1)), \
            mock.patch("actions.ask.load_candidates", return_value=(CANDIDATES, "index")), \
            mock.patch("actions.ask.candidate_text", side_effect=lambda c: f"{c.title}\ntext"):
        return turn.respond(state, message, CANDIDATES)


def asked():
    state = ChatState.new()
    respond(state, "what cookie recipes do i have")
    return state


class SuggestTest(unittest.TestCase):
    def test_common_title_words_and_books(self):
        words, books = narrow.suggest(COOKIES, "cookie")
        self.assertEqual(words[:3], [("chocolate chip", 12), ("peanut butter", 8), ("oatmeal", 8)])
        self.assertNotIn("cookies", [w for w, _ in words])
        self.assertEqual(books, [("Cookie Book", 20), ("Pie Book", 14)])

    def test_one_book_isnt_offered(self):
        _, books = narrow.suggest(COOKIES[:12], "cookie")
        self.assertEqual(books, [])

    def test_question_and_options(self):
        words, books = [("chocolate chip", 12)], [("Cookie Book", 20)]
        text = narrow.question(34, "cookie recipes", words, books)
        self.assertTrue(text.startswith("You have 34 cookie recipes. Want to narrow it down?\nchocolate chip (12),"))
        self.assertIn("or from a book: Cookie Book (20).", text)
        self.assertEqual(narrow.options(words, books), ["chocolate chip", "from Cookie Book", "show them all"])

    def test_show_all(self):
        for message in ("show them all", "all of them", "just show me all of them", "everything"):
            with self.subTest(message=message):
                self.assertTrue(narrow.SHOW_ALL_RE.match(message))
        self.assertFalse(narrow.SHOW_ALL_RE.match("all butter cookies"))


class NarrowTurnTest(unittest.TestCase):
    def test_too_many_asks_to_narrow(self):
        state = ChatState.new()
        result = respond(state, "what cookie recipes do i have")
        self.assertIn("You have 34 cookie recipes. Want to narrow it down?", result.text)
        pending = state.focus.pending
        self.assertEqual((pending.kind, pending.what), ("narrow", "cookie recipes"))
        self.assertIn("show them all", pending.options)
        self.assertEqual(len(state.focus.numbered.rest), 34)
        self.assertEqual(state.focus.numbered.items, [])

    def test_a_suggestion(self):
        state = asked()
        result = respond(state, "chocolate chip")
        self.assertIn("12 chocolate chip cookie recipes. Which one?", result.text)
        self.assertEqual(state.focus.pending.kind, "pick_recipe")
        self.assertEqual(len(state.focus.numbered.items) + len(state.focus.numbered.rest), 12)

    def test_her_own_words_inside_the_dish(self):
        state = asked()
        result = respond(state, "a snickerdoodle one")
        self.assertIn("6 snickerdoodle cookie recipes", result.text)

    def test_an_ingredient(self):
        state = asked()
        result = respond(state, "without peanuts")
        self.assertIn("26 of these don't use peanuts:", result.text)
        state = asked()
        result = respond(state, "something with oats")
        self.assertIn("8 of these use oats:", result.text)

    def test_a_book(self):
        state = asked()
        result = respond(state, "from the pie book")
        self.assertIn("14 cookie recipes from Pie Book. Which one?", result.text)

    def test_show_them_all(self):
        state = asked()
        result = respond(state, "show them all")
        self.assertIn("All 34 cookie recipes:", result.text)
        self.assertIn("...and 24 more.", result.text)
        self.assertEqual(len(state.focus.numbered.items), 10)
        more = respond(state, "more")
        self.assertIn("  11. ", more.text)

    def test_still_too_many_asks_again(self):
        many = candidates_from_index(ENTRIES + [entry(f"x{i}", f"Butter Cookies {i}") for i in range(40)])
        state = ChatState.new()
        with mock.patch.object(router.models, "chat", return_value=({"message": {}}, 0.1)), \
                mock.patch("actions.ask.load_candidates", return_value=(many, "index")):
            turn.respond(state, "what cookie recipes do i have", many)
            result = turn.respond(state, "butter", many)
        # 40 butter cookies, and the 8 peanut butter ones.
        self.assertIn("You have 48 butter cookie recipes. Want to narrow it down?", result.text)
        self.assertEqual(state.focus.pending.what, "butter cookie recipes")

    def test_nothing_left_keeps_waiting(self):
        state = asked()
        result = respond(state, "chocolate-mint")
        self.assertEqual(result.text, 'None of your cookie recipes are chocolate mint. '
                                      'Try another word, a book, or "show them all".')
        self.assertEqual(state.focus.pending.kind, "narrow")

    def test_something_else_moves_on(self):
        state = asked()
        result = respond(state, "show me the classic whipped cream")
        self.assertEqual(result.route.label, "rule: ask find")
        self.assertIsNone(state.focus.pending)

    def test_thirty_or_fewer_is_a_list(self):
        state = ChatState.new()
        result = respond(state, "what peanut butter cookie recipes do i have")
        self.assertIn("You have 8 peanut butter cookie recipes:", result.text)


if __name__ == "__main__":
    unittest.main()
