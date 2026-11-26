"""
Tests for which recipes a search returns: how much of what's listed a
recipe has to use and the order they come in (match_utils/matching.py),
and how what a person types finds titles (query_utils/title_lookup.py,
actions/ask.py, the listing rule in chat/router.py).

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
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

    def test_rarer_ingredients_break_a_tie(self):
        # 1.1.3: both use two of hers and the cream misses less, but far
        # fewer recipes use pumpkin than heavy cream.
        index = [entry("Cream", ["heavy cream", "cream cheese"]),
                 entry("Pumpkin Pie", ["pumpkin", "cream cheese", "x", "y"]),
                 entry("Ganache", ["heavy cream", "z"]), entry("Mousse", ["heavy cream", "z"])]
        results, _ = find_matches(index, ["pumpkin", "cream cheese", "heavy cream"])
        self.assertEqual(titles(results)[:2], ["Pumpkin Pie", "Cream"])

    def test_pumpkin_covers_puree_but_not_seeds(self):
        index = [entry("Pie", ["canned pumpkin puree"]), entry("Seeds", ["pumpkin seed"])]
        results, _ = find_matches(index, ["pumpkin"])
        self.assertEqual(titles(results), ["Pie"])

    def test_whole_and_its_part_are_one_thing_to_get(self):
        # Cheesecake Pie listed both "lemon" and "lemon juice" as missing.
        results, _ = find_matches([entry("Cheesecake Pie", ["pecan", "lemon", "lemon juice", "lime zest"])],
                                  ["pecan"])
        self.assertEqual(results[0]["missing"], ["lemon", "lime zest"])

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

    def test_one_kind_in_two_word_orders_is_one_note(self):
        # Flag 1ncny: both were shown.
        notes = ["assuming your buttermilk is cultured low-fat buttermilk",
                 "assuming your buttermilk is low-fat cultured buttermilk"]
        self.assertEqual(match._combined(notes), notes[:1])

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
    def ask(self, question, kind="partial", clear=None, matches=CANDIDATES[:2], index=()):
        found = mock.Mock(kind=kind, matches=list(matches), more=0, books=[PIE_BOOK], typos={}, clear=clear, via={})
        hits = [{"book": "Other Book", "page": 0, "page_confirmed": False, "text": "x", "distance": 0.1}]
        with mock.patch("actions.ask.retrieve", return_value=hits), \
                mock.patch("actions.ask.within_distance", return_value=hits), \
                mock.patch("actions.ask.find_recipes", return_value=(found, "index")), \
                mock.patch("actions.ask.load_candidates", return_value=(list(index), "index")), \
                mock.patch("actions.ask.candidate_text", side_effect=lambda c: f"text of {c.title}"), \
                mock.patch("actions.ask._answer", return_value=("from the model", 0.1)) as model:
            return ask.run(question), model

    def test_one_plainly_closest_title_is_shown(self):
        result, model = self.ask("show me the fudge pie", clear=CANDIDATES[1])
        self.assertEqual((result.kind, result.recipe, result.note), ("recipe", CANDIDATES[1], ask.CLOSEST))
        model.assert_not_called()

    def test_titles_with_all_the_words_come_before_a_guess(self):
        pumpkin = [c for c in CANDIDATES if c.title == "Pumpkin Pie"]
        result, _ = self.ask("show me my pumpkin pie from the book on pie", kind="none", matches=[], index=pumpkin)
        self.assertEqual((result.kind, result.recipe.title, result.note), ("recipe", "Pumpkin Pie", ask.CLOSEST))
        result, _ = self.ask("show me my pumpkin pie", kind="none", matches=[], index=CANDIDATES)
        self.assertEqual((result.kind, result.heading), ("choices", ask.CLOSEST_SEVERAL))

    def test_a_question_naming_recipes_is_answered_from_them(self):
        result, model = self.ask("how long does the fudge pie keep?", kind="match", matches=CANDIDATES[:1])
        self.assertEqual((result.kind, result.recipe), ("answer", CANDIDATES[0]))
        self.assertIn("text of", model.call_args[0][0])
        result, model = self.ask("how long do these keep?", kind="match", matches=CANDIDATES[:5])
        self.assertEqual(len(result.sources), ask.ABOUT_MAX_RECIPES)
        self.assertIsNone(result.recipe)

    def test_asking_to_see_a_named_recipe_still_shows_it(self):
        for question in ("show me the fudge pie", "is there a fudge pie recipe?", "how do I make fudge pie?"):
            with self.subTest(question):
                result, model = self.ask(question, kind="match", matches=CANDIDATES[:1])
                self.assertEqual(result.kind, "recipe")
                model.assert_not_called()

    def test_asking_for_a_recipe_offers_titles_and_skips_the_model(self):
        for question in ("show me the fudge pie", "no show me the fudge pie", "recipe for fudge pie"):
            with self.subTest(question):
                result, model = self.ask(question)
                self.assertEqual((result.kind, result.heading), ("choices", ask.DID_YOU_MEAN))
                model.assert_not_called()

    def test_every_recipe_of_the_dish_is_offered(self):
        cookies = candidates_from_index([
            entry("Chocolate Chip Cookies"), entry("Chocolate Chip Cookies", book="Book B"),
            entry("Chewy Chocolate Chip Cookies"), entry("Brown Butter Chocolate Chip Cookies", book="Book B"),
            entry("Sugar Cookies")])
        found = mock.Mock(kind="match", matches=cookies[:2], more=0, rest=[], books=[], typos={}, clear=None, via={})
        with mock.patch("actions.ask.retrieve", return_value=[]), \
                mock.patch("actions.ask.within_distance", return_value=[]), \
                mock.patch("actions.ask.find_recipes", return_value=(found, "index")), \
                mock.patch("actions.ask.load_candidates", return_value=(cookies, "index")):
            result = ask.run("show me a chocolate chip cookie recipe")
            self.assertEqual(result.heading, "You have 4 recipes like that. Which one?")
            self.assertEqual([c.title for c in result.choices[:2]], ["Chocolate Chip Cookies"] * 2)
            self.assertEqual({c.title for c in result.choices[2:]},
                             {"Chewy Chocolate Chip Cookies", "Brown Butter Chocolate Chip Cookies"})
            # Only the closest exist: the usual "which one?".
            found.matches = cookies[:2]
            with mock.patch("actions.ask.load_candidates", return_value=(cookies[:2], "index")):
                self.assertEqual(ask.run("show me a chocolate chip cookie recipe").heading, "")

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

    def test_words_written_apart(self):
        shelf = candidates_from_index([entry("Silky Chocolate Buttercream"), entry("Brown Butter Cake")])
        found = list_titles("butter cream", "show me my butter cream recipe", shelf)
        self.assertEqual([c.title for c in found], ["Silky Chocolate Buttercream"])

    def test_a_kind_is_included(self):
        self.assertEqual(len(list_titles("pie crust", "pie crust", CANDIDATES)), 4)

    def test_nothing_found(self):
        with mock.patch("actions.ask.load_candidates", return_value=(CANDIDATES, "index")):
            result = ask.list_recipes("lasagna", "lasagna")
        self.assertEqual(result.kind, "said")
        self.assertEqual(result.heading, "I couldn't find a recipe with lasagna in its name.")

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
