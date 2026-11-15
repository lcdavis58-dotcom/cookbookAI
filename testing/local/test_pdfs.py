"""
What ingest makes of the real PDFs (the structure step only: no
embedding, no database, no model), so a parser change that loses or
adds recipes shows up. Takes a few seconds for all 16 books. Skips a
book whose PDF isn't in COOKBOOKS_DIR.

A count changing on purpose (a parser fix finds more recipes) is fine:
update the number here in the same commit, and rebuild the index or
re-ingest so test_index.py agrees. tools/diagnostics/structure_baseline.py
shows exactly what changed.

Run from app/:
    python3 -m unittest discover -s testing/local -t .
"""

import unittest

from common.config import BOOK_FILES
from testing.local.needs import books_found, needs_pdfs
from tools.diagnostics.structure_baseline import snapshot

# Recipes found per book (2026-11-15), and how many of them may have no
# required ingredients (prose-only recipes, layer cakes made of other
# recipes; see BOOK_FORMATS.md Follow-ups).
RECIPES = {
    "The Book On Pie": (128, 0),
    "Dessert Person": (105, 0),
    "BraveTart": (100, 1),
    "Flour Water Salt Yeast": (37, 0),
    "Genius Desserts": (92, 0),
    "Genius Recipes": (92, 0),
    "How to Cook Everything Vegetarian": (729, 2),
    "Momofuku Milk Bar": (129, 13),
    "Ratio": (65, 1),
    "Salt Fat Acid Heat": (94, 0),
    "Savory Baking": (149, 19),
    "The Complete Cooking For Two Cookbook": (436, 0),
    "The Cookie Book": (74, 0),
    "The Fearless Baker": (106, 0),
    "The Food Lab": (243, 0),
    "What's For Dessert": (104, 0),
}

# A few titles each book must still have.
TITLES = {
    "The Book On Pie": ["Cornmeal Pie Dough", "Cranberry-Orange Pie", "Classic Whipped Cream"],
    "Dessert Person": ["Confetti Cake", "Cranberry-Pomegranate Mousse Pie"],
    "BraveTart": ["Homemade Cinnamon Rolls"],
    "Flour Water Salt Yeast": ["Overnight Country Blonde"],
    "Genius Desserts": ["Croccante", "Pumpkin Pie with Pecan Crunch"],
    "Genius Recipes": ["Fried Eggs with Wine Vinegar", "Garlic Green Beans"],
    "How to Cook Everything Vegetarian": ["Dried Fruit and Lima Stew", "Dry-Pan Eggplant"],
    "Momofuku Milk Bar": ["Chocolate Hazelnut Ganache", "Chocolate Malt Layer Cake"],
    "Ratio": ["Classic Hollandaise Sauce"],
    "Salt Fat Acid Heat": ["Classic Sandwich Mayo", "Creamy Herb Dressing"],
    "Savory Baking": ["Everyday Egg Dumplings", "Flakiest Cheese Biscuits"],
    "The Complete Cooking For Two Cookbook": ["French Potato Salad"],
    "The Cookie Book": ["Everything Chocolate Chip Cookies", "Favorite Thin and Crispy"],
    "The Fearless Baker": ["Concord Grape Pie", "Cream Puffs"],
    "The Food Lab": ["Diner-Style Ham and Cheese Omelet"],
    "What's For Dessert": ["Crystallized Meyer Lemon Bundt Cake"],
}


@needs_pdfs
class BookStructureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshots = {book: snapshot(book) for book in books_found()}

    def each_book(self):
        for book in BOOK_FILES:
            with self.subTest(book=book):
                if book not in self.snapshots:
                    self.skipTest(f"{book} isn't in COOKBOOKS_DIR")
                yield book, self.snapshots[book]

    def test_every_book_is_listed_here(self):
        self.assertEqual(set(RECIPES), set(BOOK_FILES))
        self.assertEqual(set(TITLES), set(BOOK_FILES))

    def test_recipe_counts(self):
        for book, snap in self.each_book():
            self.assertEqual(len(snap["recipes"]), RECIPES[book][0])

    def test_recipes_with_no_ingredients(self):
        for book, snap in self.each_book():
            empty = sum(1 for r in snap["recipes"] if not r["ingredients"])
            self.assertLessEqual(empty, RECIPES[book][1])

    def test_known_titles(self):
        for book, snap in self.each_book():
            titles = {r["title"] for r in snap["recipes"]}
            for title in TITLES[book]:
                self.assertIn(title, titles)


if __name__ == "__main__":
    unittest.main()
