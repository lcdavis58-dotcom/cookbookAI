"""
Tests for query_utils/title_lookup.py, against a small invented recipe
index (made-up titles, never ones copied from the books).

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
    python3 -m pytest testing          (if pytest is installed)
"""

import unittest

from query_utils.title_lookup import candidates_from_index, lookup, title_tokens, word_forms


def entry(recipe_id, book, title, match_title=None, aliases=()):
    return {"recipe_id": recipe_id, "book": book, "title": title,
            "match_title": match_title or title, "aliases": list(aliases)}


INDEX = [
    entry("a1", "Book A", "Toasted Sesame Cookie"),
    entry("a2", "Book A", "Sesame Cookie Bars"),
    entry("a3", "Book A", "Fig Galette with Honey and Thyme", match_title="Fig Galette"),
    entry("a4", "Book A", "Fig Galette with Almond Cream", match_title="Fig Galette"),
    entry("a5", "Book A", "Classic Butterscotch Pudding"),
    entry("a6", "Book A", "Angel’s Crème Caramel"),
    entry("a7", "Book A", "Deep-Dish Plum Crumble"),
    entry("a8", "Book A", "Double Crust"),
    entry("b1", "Book B", "Butterscotch Pudding"),
    entry("b2", "Book B", "Chewy and Crisp", aliases=["Chewy and Crisp Ginger Cookies"]),
    entry("b3", "Book B", "Pear Tart"),
    entry("b4", "Book B", "Tart"),
    entry("b5", "Book B", "Smoky Pear Tart Brûlée"),
    entry("b6", "Book B", "Walnut Brownies"),
    entry("b7", "Book B", "Blackberry Pancakes"),
]
CANDIDATES = candidates_from_index(INDEX)


def find(question, **kw):
    result = lookup(question, CANDIDATES, **kw)
    return result.kind, [c.key for c in result.matches]


class Words(unittest.TestCase):
    def test_tokens(self):
        self.assertEqual(title_tokens("Angel’s Crème Caramel"), ["angels", "creme", "caramel"])
        self.assertEqual(title_tokens("Deep-Dish Plum Crumble"), ["deep", "dish", "plum", "crumble"])
        self.assertEqual(title_tokens("Milky Star® Bars & Squares"), ["milky", "star", "bars", "squares"])
        self.assertEqual(title_tokens("Oat Milk™ Ice Cream"), ["oat", "milk", "ice", "cream"])

    def test_parenthesized_words_not_required(self):
        candidates = candidates_from_index([entry("x", "Book C", "Crumb Topping (For a Crisp Pie)")])
        self.assertEqual([c.key for c in lookup("double the crumb topping", candidates).matches], ["x"])
        self.assertEqual(title_tokens("Pie with a Crust"), ["pie", "crust"])
        self.assertEqual(title_tokens("Grain Mix #2"), ["grain", "mix", "2"])

    def test_plural_forms_meet(self):
        for a, b in [("cookies", "cookie"), ("berries", "berry"), ("peaches", "peach"),
                     ("loaves", "loaf"), ("tomatoes", "tomato"), ("quiches", "quiche"),
                     ("brownies", "brownie"), ("angels", "angel")]:
            self.assertTrue(word_forms(a) & word_forms(b), (a, b))

    def test_different_words_stay_apart(self):
        self.assertFalse(word_forms("pasta") & word_forms("paste"))
        self.assertFalse(word_forms("cream") & word_forms("creme"))


class Matches(unittest.TestCase):
    def test_exact_title(self):
        self.assertEqual(find("double the toasted sesame cookie"), ("match", ["a1"]))

    def test_plural_and_case(self):
        self.assertEqual(find("TRIPLE THE TOASTED SESAME COOKIES"), ("match", ["a1"]))

    def test_accents_apostrophes_hyphens(self):
        self.assertEqual(find("halve the angels creme caramel"), ("match", ["a6"]))
        self.assertEqual(find("double the deep dish plum crumble"), ("match", ["a7"]))

    def test_filler_words(self):
        self.assertEqual(find("double the chewy crisp"), ("match", ["b2"]))

    def test_typo(self):
        result = lookup("double the toasted sesmae cookie", CANDIDATES)
        self.assertEqual((result.kind, [c.key for c in result.matches]), ("match", ["a1"]))
        self.assertEqual(result.typos, {"sesmae": ["sesame"]})

    def test_real_word_is_not_a_typo(self):
        # "tart" is a title word, so it's never read as "pear" or "part".
        self.assertEqual(find("double the tart"), ("match", ["b4"]))

    def test_longer_title_wins(self):
        self.assertEqual(find("double the pear tart"), ("match", ["b3"]))

    def test_with_tail_not_required(self):
        # Both are as close (two "with" words unnamed), so by title.
        self.assertEqual(find("double the fig galette"), ("match", ["a4", "a3"]))

    def test_with_tail_picks_one(self):
        self.assertEqual(find("double the fig galette with almond cream"), ("match", ["a4"]))

    def test_soft_word_not_required(self):
        # Both butterscotch puddings: Book B's is named in full, Book A's
        # only lacks "Classic". Exact titles are listed first.
        self.assertEqual(find("double the butterscotch pudding"), ("match", ["b1", "a5"]))

    def test_alias(self):
        self.assertEqual(find("double the chewy and crisp ginger cookies"), ("match", ["b2"]))

    def test_book_name_narrows(self):
        self.assertEqual(find("double the butterscotch pudding from Book A"), ("match", ["a5"]))

    def test_book_name_words_dont_count(self):
        # "pancakes" alone isn't the title; "Book B" mustn't count either.
        self.assertEqual(find("show me something from book b"), ("none", []))

    def test_request_word_in_title(self):
        self.assertEqual(find("double the double crust"), ("match", ["a8"]))


class Partial(unittest.TestCase):
    def test_missing_title_word(self):
        # The brûlée is closest, but "Tart" is named in full, so it's
        # offered first.
        self.assertEqual(find("double the smoky tart"), ("partial", ["b4", "b5"]))

    def test_one_word_half_the_title(self):
        self.assertEqual(find("double the brownies"), ("partial", ["b6"]))

    def test_full_titles_listed_first(self):
        # "Pear Tart" is all there; the brûlée shares one more word.
        self.assertEqual(find("scale the smoky pear tart"), ("partial", ["b3", "b5"]))

    def test_request_word_is_not_a_guess(self):
        self.assertEqual(find("double the lasagna"), ("none", []))

    def test_nearby_breaks_ties(self):
        self.assertEqual(find("scale the walnut and blackberry"), ("partial", ["b7", "b6"]))
        self.assertEqual(find("scale the walnut and blackberry", nearby={"b6": 0, "b7": 5}),
                         ("partial", ["b6", "b7"]))

    def test_nothing(self):
        self.assertEqual(find("hello there"), ("none", []))


SHELF = [
    entry("p1", "Butter Sugar Flour Eggs", "Lemon Bars"),
    entry("p2", "The Weekend Kitchen", "Lemon Bars"),
    entry("p3", "The Weekend Kitchen Cookbook", "Lemon Bars"),
    entry("p4", "Pie Person", "Lemon Bars"),
    entry("p5", "Crumbworks", "Lemon Bars"),
    entry("p6", "The Big Pie Book", "Lemon Bars"),
    entry("p7", "The Little Cake Book", "Lemon Bars"),
    entry("p8", "Bread Sugar Fire Earth", "Lemon Bars"),
    entry("p9", "Pie Person", "Tbpb Crumble"),
]
SHELF_CANDIDATES = candidates_from_index(SHELF)


def books_in(question):
    return lookup(question, SHELF_CANDIDATES).books


class Books(unittest.TestCase):
    def test_full_name_anywhere(self):
        self.assertEqual(books_in("the weekend kitchen's lemon bars, doubled"), ["The Weekend Kitchen"])

    def test_typo_after_cue(self):
        self.assertEqual(books_in("double the lemon bars from pie persn"), ["Pie Person"])
        self.assertEqual(books_in("double the lemon bars from crumbwork"), ["Crumbworks"])

    def test_shortened_after_cue(self):
        self.assertEqual(books_in("double the lemon bars from butter sugar"), ["Butter Sugar Flour Eggs"])
        self.assertEqual(books_in("double the lemon bars in big pie book"), ["The Big Pie Book"])

    def test_shortening_needs_a_cue(self):
        # Ingredients, not a book.
        self.assertEqual(books_in("halve the lemon bars, I only have butter sugar"), [])

    def test_one_shared_word_is_not_a_book(self):
        self.assertEqual(books_in("double the lemon bars from pie"), [])

    def test_most_words_wins(self):
        self.assertEqual(books_in("double the lemon bars from pie book"), ["The Big Pie Book"])

    def test_full_name_beats_part_of_another(self):
        self.assertEqual(books_in("double the lemon bars from weekend kitchen"), ["The Weekend Kitchen"])

    def test_tie_names_both(self):
        self.assertEqual(books_in("double the lemon bars from weekend kitchn"),
                         ["The Weekend Kitchen", "The Weekend Kitchen Cookbook"])

    def test_acronym(self):
        self.assertEqual(books_in("double the lemon bars, tlcb"), ["The Little Cake Book"])
        self.assertEqual(books_in("double the lemon bars from lcb"), ["The Little Cake Book"])

    def test_acronym_that_is_a_title_word(self):
        # "Tbpb Crumble" makes "tbpb" a recipe word; "bpb" still works.
        self.assertEqual(books_in("double the tbpb crumble"), [])
        self.assertEqual(books_in("double the lemon bars from bpb"), ["The Big Pie Book"])

    def test_two_letter_acronym_ignored(self):
        self.assertEqual(books_in("double the lemon bars from pp"), [])

    def test_shared_acronym_names_both(self):
        self.assertEqual(books_in("double the lemon bars from bsfe"),
                         ["Bread Sugar Fire Earth", "Butter Sugar Flour Eggs"])
        result = lookup("double the lemon bars from bsfe", SHELF_CANDIDATES)
        self.assertEqual((result.kind, sorted(c.key for c in result.matches)), ("match", ["p1", "p8"]))

    def test_book_picks_recipe(self):
        result = lookup("double the lemon bars from pie persn", SHELF_CANDIDATES)
        self.assertEqual([c.key for c in result.matches], ["p4"])


class SplitAndJoinedWordsTest(unittest.TestCase):
    """1.1.3: "butter cream" for "Buttercream", "short bread" the other way."""
    SHELF = candidates_from_index([entry("j1", "Book J", "Buttercream"),
                                   entry("j2", "Book J", "Short Bread"),
                                   entry("j3", "Book J", "Peanut Butter Cream Pie")])

    def find(self, question):
        result = lookup(question, self.SHELF)
        return result.kind, [c.key for c in result.matches]

    def test_written_apart(self):
        self.assertEqual(self.find("show me the butter cream"), ("match", ["j1"]))

    def test_written_together(self):
        self.assertEqual(self.find("double the shortbread"), ("match", ["j2"]))

    def test_the_words_apart_still_count(self):
        self.assertEqual(self.find("peanut butter cream pie"), ("match", ["j3"]))


class VariationsTest(unittest.TestCase):
    """1.1.3: a recipe found through a variation printed inside it."""
    SHELF = candidates_from_index([
        dict(entry("v1", "Book V", "Classic Cream Cheese Frosting"),
             variations=["Brown Butter Cream Cheese Frosting", "Chocolate Cream Cheese Frosting"]),
        entry("v2", "Book W", "Cream Cheese Frosting"),
        entry("v3", "Book W", "Brown Butter Carrot Cake"),
    ])

    def test_found_through_its_variation(self):
        result = lookup("show me my brown butter cream cheese frosting", self.SHELF)
        self.assertEqual((result.kind, [c.key for c in result.matches]), ("match", ["v1"]))
        self.assertEqual(result.via, {"v1": "Brown Butter Cream Cheese Frosting"})

    def test_the_title_wins_a_tie(self):
        result = lookup("cream cheese frosting", self.SHELF)
        self.assertEqual(sorted(c.key for c in result.matches), ["v1", "v2"])
        self.assertEqual(result.via, {})

    def test_linking_at_ingest_leaves_variations_out(self):
        result = lookup("brown butter cream cheese frosting", self.SHELF, loose=False)
        self.assertEqual(result.via, {})


class ClearBestTest(unittest.TestCase):
    """1.1.3: a near miss with one title plainly closest."""
    SHELF = candidates_from_index([entry("w1", "Book W", "Extra-Thick and Creamy Whipped Cream"),
                                   entry("w2", "Book W", "Chocolate Whipped Cream"),
                                   entry("w3", "Book W", "Almond Butter Banana Bread"),
                                   entry("w4", "Book W", "Banana Bread")])

    def test_one_plainly_closest(self):
        result = lookup("show me the extra thick creamy cream", self.SHELF)
        self.assertEqual((result.kind, result.clear.key), ("partial", "w1"))

    def test_not_when_another_is_named_in_full(self):
        result = lookup("how much almond butter is in the banana bread", self.SHELF)
        self.assertIsNone(result.clear)

    def test_not_from_a_few_words_of_a_long_title(self):
        self.assertIsNone(lookup("show me the thick cream", self.SHELF).clear)


if __name__ == "__main__":
    unittest.main()
