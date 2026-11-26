"""
Tests for match_utils/recipe_index.py: building index entries from
recipe text, loading recipes from a stand-in Chroma collection, and
saving and loading the index. Recipes here are made up in The Book On
Pie's format, not book text, and nothing needs the database or a model.

Run from app/:
    python3 -m unittest discover -s testing/unit -t .
"""

import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

# query_utils.retrieval imports the database and model clients; a
# stand-in collection replaces the database here.
for _name in ("chromadb", "ollama"):
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = types.ModuleType(_name)

from match_utils import recipe_index  # noqa: E402

BOOK = "The Book On Pie"

PEAR_PIE = """TEST PEAR PIE WITH OAT CRUMBLE
MAKES ONE 9-INCH / 23-CM PIE
1 All-Buttah Pie Dough (page 10)
FILLING
680 g / 1½ pounds ripe pears, peeled and sliced
100 g / ½ cup granulated sugar
2 g / ½ teaspoon ground cinnamon
50 g / 1 large egg
TOPPING
100 g / ½ cup granulated sugar
60 g / ½ cup rolled oats
GARNISH (OPTIONAL)
120 g / ½ cup heavy cream
5 g / 1 teaspoon flaky salt (optional)
1. Heat the oven to 400°F."""

GALETTE = """TEST FRUIT GALETTE
MAKES ONE 10-INCH / 25-CM GALETTE
1 All-Buttah Pie Dough (page 10)
400 g / 3 cups prepared fruit
113 g / ½ cup unsalted butter or shortening
50 g / ¼ cup granulated sugar
GLAZE (OPTIONAL)
1 Vanilla Glaze (page 20)
60 g / ¼ cup granulated sugar
1. Heat the oven."""


def recipe(text, book=BOOK, page=12, confirmed=True):
    return {"book": book, "text": text, "page": page, "page_confirmed": confirmed}


def names(entries):
    return [e["name"] for e in entries]


class IndexEntryTest(unittest.TestCase):
    def setUp(self):
        self.entry = recipe_index.index_entry("bop-1", recipe(PEAR_PIE))

    def test_title_and_page(self):
        e = self.entry
        self.assertEqual((e["recipe_id"], e["book"], e["page"], e["page_confirmed"]), ("bop-1", BOOK, 12, True))
        self.assertEqual(e["title"], "Test Pear Pie with Oat Crumble")
        self.assertEqual(e["match_title"], "TEST PEAR PIE")
        self.assertEqual(e["aliases"], [])

    def test_required_ingredients_once_each(self):
        # Sugar is in both the filling and the topping.
        self.assertEqual(names(self.entry["ingredients"]),
                         ["pear", "granulated sugar", "ground cinnamon", "egg", "rolled oats"])
        self.assertEqual(self.entry["ingredients"][0]["options"], ["pear"])

    def test_optional_group_and_optional_line(self):
        self.assertEqual(names(self.entry["optional"]), ["heavy cream", "flaky salt"])

    def test_sub_recipes(self):
        self.assertEqual(self.entry["sub_recipes"], ["All-Buttah Pie Dough (page 10)"])
        self.assertEqual(self.entry["optional_sub_recipes"], [])

    def test_groups(self):
        self.assertEqual(self.entry["groups"], {"Filling": "component", "Topping": "component",
                                                "Garnish (optional)": "optional"})


class IndexEntryChoicesTest(unittest.TestCase):
    def setUp(self):
        self.entry = recipe_index.index_entry("bop-2", recipe(GALETTE, page=0, confirmed=False))

    def test_x_or_y_splits_into_options(self):
        butter = self.entry["ingredients"][0]
        self.assertEqual(butter, {"name": "unsalted butter or shortening",
                                  "options": ["unsalted butter", "shortening"]})

    def test_placeholder_is_your_choice(self):
        self.assertEqual(self.entry["your_choice"], ["prepared fruit"])
        self.assertNotIn("prepared fruit", names(self.entry["ingredients"]))

    def test_required_somewhere_isnt_also_optional(self):
        self.assertIn("granulated sugar", names(self.entry["ingredients"]))
        self.assertEqual(self.entry["optional"], [])

    def test_optional_sub_recipe(self):
        self.assertEqual(self.entry["sub_recipes"], ["All-Buttah Pie Dough (page 10)", "Vanilla Glaze (page 20)"])
        self.assertEqual(self.entry["optional_sub_recipes"], ["Vanilla Glaze (page 20)"])

    def test_book_without_a_profile(self):
        self.assertIsNone(recipe_index.index_entry("x", recipe(GALETTE, book="A Book With No Module")))


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows
        self.where = None

    def get(self, where, include):
        self.where = where
        return {"ids": [r[0] for r in self.rows], "documents": [r[1] for r in self.rows],
                "metadatas": [r[2] for r in self.rows]}


class LoadRecipesTest(unittest.TestCase):
    def load(self, rows):
        collection = FakeCollection(rows)
        retrieval = types.SimpleNamespace(get_collection=lambda: collection)
        with mock.patch.dict(sys.modules, {"query_utils.retrieval": retrieval}):
            result = recipe_index.load_recipes()
        self.assertEqual(collection.where, {"content_type": "recipe"})
        return result

    def test_split_recipe_is_stitched_in_order(self):
        recipes = self.load([
            ("c2", "second half", {"book": BOOK, "recipe_id": "r1", "part": 1, "page": 99}),
            ("c1", "first half", {"book": BOOK, "recipe_id": "r1", "part": 0, "page": 12, "page_confirmed": True}),
        ])
        self.assertEqual(recipes, {"r1": {"book": BOOK, "text": "first half\nsecond half", "chunk_ids": ["c2", "c1"],
                                          "page": 12, "page_confirmed": True}})

    def test_chunk_without_a_recipe_id_is_its_own_recipe(self):
        recipes = self.load([("old-chunk", "text", {"book": BOOK})])
        self.assertEqual(recipes["old-chunk"], {"book": BOOK, "text": "text", "chunk_ids": ["old-chunk"],
                                                "page": 0, "page_confirmed": False})


class BuildIndexTest(unittest.TestCase):
    def test_sorted_and_linked(self):
        recipes = {"b": recipe(PEAR_PIE), "a": recipe(GALETTE), "skip": recipe(GALETTE, book="No Module")}
        with mock.patch.object(recipe_index, "load_recipes", return_value=recipes), \
                mock.patch.object(recipe_index, "link_sub_recipes") as link:
            with mock.patch("match_utils.chapters.add_chapters"):
                entries = recipe_index.build_index(label=False)
        self.assertEqual([e["title"] for e in entries], ["Test Fruit Galette", "Test Pear Pie with Oat Crumble"])
        link.assert_called_once()
        self.assertEqual(len(link.call_args.args[0]), 2)

    def test_dish_labels_are_added(self):
        recipes = {"a": recipe(GALETTE)}
        with mock.patch.object(recipe_index, "load_recipes", return_value=recipes),                 mock.patch("match_utils.chapters.add_chapters") as chapters,                 mock.patch("match_utils.dish_labels.label_dishes") as label:
            entries = recipe_index.build_index()
        label.assert_called_once_with(entries)
        chapters.assert_called_once_with(entries)
        self.assertNotIn("headnote", entries[0])


def entry(title, ingredients=(), optional=(), book=BOOK):
    def reqs(items):
        return [{"name": n, "options": n.split(" or ")} for n in items]
    return {"title": title, "book": book, "ingredients": reqs(ingredients), "optional": reqs(optional)}


class SaveAndLoadTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "recipe_index.json")
        self.entries = [entry("Pie", ["heavy cream", "egg"]), entry("Tart", ["egg", "butter or shortening"])]

    def tearDown(self):
        self.dir.cleanup()

    def test_round_trip(self):
        recipe_index.save_index(self.entries, self.path)
        self.assertEqual(recipe_index.load_index(self.path), self.entries)
        self.assertEqual(recipe_index.load_ingredient_words(self.path),
                         {"butter": 1, "cream": 1, "egg": 2, "heavy": 1, "shortening": 1})
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_not_built_yet(self):
        self.assertIsNone(recipe_index.load_index(self.path))
        self.assertEqual(recipe_index.load_ingredient_words(self.path), {})
        self.assertEqual(recipe_index.load_ingredient_words(self.path, self.entries)["egg"], 2)

    def test_older_index_without_word_counts(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"recipes": self.entries}, f)
        self.assertEqual(recipe_index.load_ingredient_words(self.path)["egg"], 2)


class IngredientWordsTest(unittest.TestCase):
    def test_counts_recipes_not_mentions(self):
        entries = [entry("A", ["egg", "egg yolk"], optional=["2% milk"]), entry("B", [], optional=["egg"])]
        self.assertEqual(recipe_index.ingredient_words(entries), {"egg": 2, "milk": 1, "yolk": 1})


class SummarizeTest(unittest.TestCase):
    def test_summary(self):
        entries = [entry("Pie", ["butter or shortening"]), entry("Toast", [], book="Other Book")]
        self.assertEqual(recipe_index.summarize(entries), [
            "Recipe index: 2 recipes",
            "  Other Book: 1",
            f"  {BOOK}: 1",
            "  1 with no required ingredients: Toast",
            '  1 ingredient choices ("X or Y") split into options',
            "  0 variations named, in 0 recipes",
            "  0 with a dish type, 0 with a chapter",
        ])

    def test_long_list_is_cut_short(self):
        entries = [entry(f"Empty {i}") for i in range(10)]
        self.assertTrue(recipe_index.summarize(entries)[2].endswith("Empty 7, ..."))


if __name__ == "__main__":
    unittest.main()
