"""
Tests for which recipes a search returns: how much of what's listed a
recipe has to use and the order they come in (match_utils/matching.py),
and how what a person types finds titles (query_utils/title_lookup.py,
actions/ask.py, the listing rule in chat/router.py).

Run from app/:
    python3 -m unittest discover testing
"""

import unittest
from unittest import mock

from testing.unit.test_chat_router import fresh  # (also stubs chromadb/ollama)

from actions import ask, match  # noqa: E402
from chat import reply  # noqa: E402
from chat.router import Router  # noqa: E402
from match_utils.matching import enough_to_use, find_matches  # noqa: E402
from query_utils.title_lookup import candidates_from_index, list_titles, lookup  # noqa: E402


def entry(title, ingredients=(), book="Book A", kinds=()):
    return {"recipe_id": f"{book}-{title}", "book": book, "title": title, "match_title": title, "aliases": [],
            "page": 0, "page_confirmed": False, "kinds": list(kinds), "your_choice": [], "optional": [],
            "ingredients": [{"name": i, "options": [i]} for i in ingredients]}


def titles(results):
    return [r["entry"]["title"] for r in results]


class EnoughTest(unittest.TestCase):
    def test_share(self):
        self.assertEqual([enough_to_use(n) for n in (1, 2, 3, 4, 6, 8)], [1, 2, 2, 3, 4, 6])


class FindMatchesTest(unittest.TestCase):
    def test_two_listed_means_both(self):
        index = [entry("One", ["pecan", "sage"]), entry("Both", ["pecan", "lemon", "sage"])]
        results, partial = find_matches(index, ["pecan", "lemon"])
        self.assertEqual(titles(results), ["Both"])
        self.assertFalse(partial)

    def test_no_limit_on_what_is_missing(self):
        index = [entry("Long", ["pecan", "lemon", "a1", "a2", "a3", "a4", "a5", "a6", "a7"])]
        results, _ = find_matches(index, ["pecan", "lemon"])
        self.assertEqual(len(results[0]["missing"]), 7)

    def test_most_of_hers_comes_before_fewest_missing(self):
        index = [entry("Two", ["pecan", "lemon"]), entry("Three", ["pecan", "lemon", "lime", "x", "y"])]
        results, _ = find_matches(index, ["pecan", "lemon", "lime"])
        self.assertEqual(titles(results), ["Three", "Two"])

    def test_using_all_of_hers_beats_more_staples(self):
        hers = ["pecan", "lemon", "lime", "sage", "thyme", "mint"]
        index = [entry("Five And Staples", hers[:5] + ["egg", "kosher salt", "water", "vanilla extract"]),
                 entry("All Six", hers)]
        results, _ = find_matches(index, hers)
        self.assertEqual(titles(results), ["All Six", "Five And Staples"])

    def test_listed_staples_do_not_count(self):
        index = [entry("Staples", ["egg", "kosher salt", "sage"]), entry("Hers", ["pecan", "sage"])]
        results, partial = find_matches(index, ["egg", "kosher salt", "pecan"])
        self.assertEqual(titles(results), ["Hers"])
        self.assertFalse(partial)

    def test_only_staples_listed_still_works(self):
        results, _ = find_matches([entry("Eggy", ["egg", "sage"])], ["egg"])
        self.assertEqual(titles(results), ["Eggy"])

    def test_plain_staples_are_on_hand(self):
        results, _ = find_matches([entry("Plain", ["pecan", "salt", "pepper", "flour", "butter"])], ["pecan"])
        self.assertEqual(results[0]["missing"], [])

    def test_pumpkin_covers_puree_but_not_seeds(self):
        index = [entry("Pie", ["canned pumpkin puree"]), entry("Seeds", ["pumpkin seed"])]
        results, _ = find_matches(index, ["pumpkin"])
        self.assertEqual(titles(results), ["Pie"])

    def test_falls_back_to_some_and_says_so(self):
        index = [entry("Some", ["pecan", "sage"]), entry("Neither", ["sage"])]
        results, partial = find_matches(index, ["pecan", "lemon"])
        self.assertEqual(titles(results), ["Some"])
        self.assertTrue(partial)

    def test_nothing_at_all(self):
        self.assertEqual(find_matches([entry("Neither", ["sage"])], ["pecan"]), ([], False))


class WordingTest(unittest.TestCase):
    def found(self, missing=()):
        return {"entry": entry("Tart"), "uses": ["lemon"], "missing": list(missing), "staples_used": [],
                "optional_on_hand": []}

    def test_partial_results_say_so(self):
        result = match.MatchResult("matches", have=["lemon", "sage"], only_partial=True, missing_some=[self.found(["x"])])
        self.assertIn(match.ONLY_PARTIAL, reply.match_reply(result))
        self.assertIn(match.ONLY_PARTIAL, match.render(result))

    def test_long_missing_lists_are_shortened(self):
        result = match.MatchResult("matches", have=["lemon"], missing_some=[self.found([f"m{i}" for i in range(8)])])
        self.assertIn("missing: m0, m1, m2, m3, m4 and 3 more", reply.match_reply(result))

    def test_many_assumptions_about_one_ingredient_become_one_line(self):
        notes = [f"assuming your chocolate is {k} chocolate" for k in ("dark", "milk", "white")]
        self.assertEqual(match._combined(notes + ["assuming your butter is salted butter"]),
                         ["assuming your chocolate is the kind each recipe calls for",
                          "assuming your butter is salted butter"])

    def test_empty_sections_are_left_out(self):
        text = reply.match_reply(match.MatchResult("matches", have=["lemon"], missing_some=[self.found(["x"])]))
        self.assertNotIn("(none)", text)
        self.assertNotIn("You can make", text)
        self.assertIn("Missing some ingredients (1):", text)

    def test_no_results_at_all_says_so(self):
        text = reply.match_reply(match.MatchResult("matches", have=["lemon"]))
        self.assertIn("I couldn't find any recipes", text)

    def test_hint_is_plain(self):
        result = match.MatchResult("matches", have=["lemon"], ready=[self.found()])
        self.assertIn('To see a recipe, type its number. To change your search, type "add" or "without"',
                      reply.match_reply(result))


PIE_BOOK = "The Book On Pie"
INDEX = [
    entry("All-Buttah Pie Dough", book=PIE_BOOK, kinds=["pie dough"]),
    entry("Cornmeal Pie Dough", book=PIE_BOOK, kinds=["pie dough"]),
    entry("Caramelized Pie Crust", book=PIE_BOOK, kinds=["pie dough"]),
    entry("All-Butter Pie Dough", book="Other Book", kinds=["pie dough"]),
    entry("Pumpkin Pie", book=PIE_BOOK),
    entry("Classic Pumpkin Pie", book="Other Book"),
    entry("Pumpkin Soup", book="Other Book"),
]
CANDIDATES = candidates_from_index(INDEX)


class LookupTest(unittest.TestCase):
    def test_crust_finds_dough_and_butter_finds_buttah(self):
        found = lookup("show me the all butter pie crust recipe from the book on pie", CANDIDATES)
        self.assertEqual((found.kind, [c.title for c in found.matches]), ("match", ["All-Buttah Pie Dough"]))

    def test_a_kind_lists_every_recipe_of_it(self):
        found = lookup("show me a recipe for pie crust", CANDIDATES)
        self.assertEqual(found.kind, "match")
        self.assertEqual(len(found.matches), 4)

    def test_a_kind_within_a_book(self):
        found = lookup("pie crust from the book on pie", CANDIDATES)
        self.assertEqual({c.book for c in found.matches}, {PIE_BOOK})
        self.assertEqual(len(found.matches), 3)

    def test_linking_at_ingest_stays_strict(self):
        self.assertEqual(lookup("all butter pie crust", CANDIDATES, loose=False).kind, "partial")
        self.assertNotEqual(len(lookup("pie crust", CANDIDATES, loose=False).matches), 4)


class AskPartialTest(unittest.TestCase):
    def ask(self, question, kind="partial"):
        found = mock.Mock(kind=kind, matches=CANDIDATES[:2], more=0, books=[PIE_BOOK], typos={})
        hits = [{"book": "Other Book", "page": 0, "page_confirmed": False, "text": "x", "distance": 0.1}]
        with mock.patch("actions.ask.retrieve", return_value=hits), \
                mock.patch("actions.ask.within_distance", return_value=hits), \
                mock.patch("actions.ask.find_recipes", return_value=(found, "index")), \
                mock.patch("actions.ask._answer", return_value=("from the model", 0.1)) as model:
            return ask.run(question), model

    def test_asking_for_a_recipe_offers_titles_and_skips_the_model(self):
        for question in ("show me the fudge pie", "no show me the fudge pie", "recipe for fudge pie"):
            with self.subTest(question):
                result, model = self.ask(question)
                self.assertEqual((result.kind, result.heading), ("choices", ask.DID_YOU_MEAN))
                model.assert_not_called()

    def test_a_named_book_limits_the_excerpts(self):
        result, model = self.ask("what goes with banana bread in the book on pie")
        self.assertEqual(result.kind, "nothing")
        model.assert_not_called()

    def test_show_me_how_is_not_asking_for_a_recipe(self):
        self.assertIsNone(ask.WANTS_RECIPE_RE.search("show me how to fold dough"))


class ListingTest(unittest.TestCase):
    def test_lists_every_title_with_the_words(self):
        found = list_titles("pumpkin pie", "pumpkin pie", CANDIDATES)
        self.assertEqual([c.title for c in found], ["Classic Pumpkin Pie", "Pumpkin Pie"])

    def test_a_named_book_limits_it(self):
        found = list_titles("pumpkin", "my pumpkin recipes from the book on pie", CANDIDATES)
        self.assertEqual([c.title for c in found], ["Pumpkin Pie"])

    def test_a_kind_is_included(self):
        self.assertEqual(len(list_titles("pie crust", "pie crust", CANDIDATES)), 4)

    def test_nothing_found(self):
        with mock.patch("actions.ask.load_candidates", return_value=(CANDIDATES, "index")):
            self.assertEqual(ask.list_recipes("lasagna", "lasagna").kind, "nothing")

    def test_routing(self):
        for message, what in (("tell me what pumpkin pie recipes i have", "pumpkin pie"),
                              ("what pumpkin pie recipes do i have?", "pumpkin pie"),
                              ("do i have any pumpkin recipes", "pumpkin"),
                              ("show me all the pumpkin pie recipes", "pumpkin pie"),
                              ("show me pumpkin pie recipes", "pumpkin pie"),
                              ("list my cookie recipes", "cookie")):
            with self.subTest(message):
                result = Router(fresh(), CANDIDATES).route(message)
                self.assertEqual((result.mode, result.find_text), ("list", what))

    def test_one_recipe_is_not_a_list(self):
        self.assertNotEqual(Router(fresh(), CANDIDATES).route("show me a pumpkin pie recipe").mode, "list")


if __name__ == "__main__":
    unittest.main()
