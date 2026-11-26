import unittest
from unittest import mock

from match_utils import chapters
from match_utils.dish_labels import headnote, shown

# Every recipe listed under its chapter, like The Book On Pie.
LISTED = [(1, "Contents", 3), (1, "Chapter One: Doughs & Crusts", 10), (2, "All-Butter Pie Dough", 12),
          (2, "Graham Cracker Crust: From the Test Kitchen", 14), (1, "Chapter Two: Fruit Pies", 20),
          (2, "Apple Pie", 22), (1, "Index", 90)]
# Only chapters, out of page order, like the ebooks.
CHAPTERS_ONLY = [(1, "Table of Contents", 5), (1, "Master Recipe Listing", 900), (1, "Chapter 1: Salads", 10),
                 (1, "Chapter 2: Soups", 50), (2, "Cold Soups", 70), (1, "Index", 950)]
# Recipes three levels down, like Salt Fat Acid Heat.
DEEP = [(1, "Part Two: Recipes", 100), (2, "Recipes", 101), (3, "Salads", 102), (4, "Caesar Salad", 103)]


def entry(rid, title, book="Book"):
    return {"recipe_id": rid, "title": title, "match_title": title, "book": book}


class ByTitleTest(unittest.TestCase):
    def test_listed_under_its_chapter(self):
        found = chapters.find_chapters([entry("a", "Apple Pie"), entry("b", "All-Butter Pie Dough")], LISTED)
        self.assertEqual(found, {"a": "Chapter Two: Fruit Pies", "b": "Chapter One: Doughs & Crusts"})

    def test_listed_with_more_after_it(self):
        found = chapters.find_chapters([entry("a", "Graham Cracker Crust")], LISTED)
        self.assertEqual(found, {"a": "Chapter One: Doughs & Crusts"})

    def test_the_two_headings_right_above(self):
        self.assertEqual(chapters.find_chapters([entry("a", "Caesar Salad")], DEEP), {"a": "Recipes > Salads"})

    def test_not_listed(self):
        self.assertEqual(chapters.find_chapters([entry("a", "Pecan Pie")], LISTED), {})


class ByPageTest(unittest.TestCase):
    def test_chapter_starting_last_before_the_page(self):
        self.assertEqual(chapters.chapter_at_page(CHAPTERS_ONLY, 30), "Chapter 1: Salads")
        self.assertEqual(chapters.chapter_at_page(CHAPTERS_ONLY, 75), "Chapter 2: Soups > Cold Soups")

    def test_front_matter_is_not_a_chapter(self):
        self.assertEqual(chapters.chapter_at_page(CHAPTERS_ONLY, 6), "")

    def test_page_from_the_extraction(self):
        # The title on the table of contents page in small type, and on
        # its own page in large type.
        extraction = {"pages": [
            {"index": 5, "lines": [{"text": "Gazpacho", "size": 9}]},
            {"index": 59, "lines": [{"text": "GAZPACHO", "size": 24}, {"text": "Serves 4", "size": 9}]}]}
        found = chapters.find_chapters([entry("g", "Gazpacho")], CHAPTERS_ONLY, extraction)
        self.assertEqual(found, {"g": "Chapter 2: Soups"})


class AddChaptersTest(unittest.TestCase):
    def test_without_a_pdf(self):
        entries = [entry("a", "Apple Pie", book="The Book On Pie")]
        with mock.patch.object(chapters, "load_toc", return_value=[]):
            self.assertEqual(chapters.add_chapters(entries, log=lambda *_: None), 0)
        self.assertNotIn("chapter", entries[0])

    def test_sets_the_chapter(self):
        entries = [entry("a", "Apple Pie", book="The Book On Pie")]
        with mock.patch.object(chapters, "load_toc", return_value=LISTED), \
                mock.patch("os.path.isfile", return_value=False):
            self.assertEqual(chapters.add_chapters(entries, log=lambda *_: None), 1)
        self.assertEqual(entries[0]["chapter"], "Chapter Two: Fruit Pies")


class HeadnoteTest(unittest.TestCase):
    def test_up_to_the_ingredients(self):
        text = "Apple Pie\nA pie for a crowd, great at parties.\nIt keeps two days.\n6 apples\n1 cup sugar"
        self.assertEqual(headnote(text, "Apple Pie"), "A pie for a crowd, great at parties. It keeps two days.")

    def test_yield_and_time_lines_left_out(self):
        text = "Bean Soup\nSERVES 2\nWHY THIS RECIPE WORKS: A quick soup.\n1 can beans"
        self.assertEqual(headnote(text, "Bean Soup"), "A quick soup.")
        text = "Bean Soup\nMAKES: 4 servings TIME: 30 minutes\nA rich soup.\n2 cups beans"
        self.assertEqual(headnote(text, "Bean Soup"), "A rich soup.")

    def test_cut_short_at_a_word(self):
        text = "Pie\n" + "word " * 200 + "\n1 cup flour"
        note = headnote(text, "Pie")
        self.assertTrue(note.endswith("word..."))
        self.assertLessEqual(len(note), 403)

    def test_none(self):
        self.assertEqual(headnote("Pie\n1 cup flour", "Pie"), "")
        self.assertEqual(headnote("", ""), "")

    def test_shown_to_the_model(self):
        recipe = {"title": "Deviled Eggs", "book": "Book", "chapter": "Snacks & Drinks",
                  "ingredients": [{"name": "egg"}], "headnote": "Party food."}
        self.assertEqual(shown(recipe), "Deviled Eggs (Book) - ingredients: egg")
        line = shown(recipe, chapter=True, note=True)
        self.assertEqual(line, 'Deviled Eggs (Book) - chapter: Snacks & Drinks - ingredients: egg'
                               ' - the book says: "Party food."')


if __name__ == "__main__":
    unittest.main()
