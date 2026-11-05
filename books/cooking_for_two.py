"""
The Complete Cooking For Two Cookbook (America's Test Kitchen): settings
for the shared engine (books/engine.py). See books/__init__.py for the
interface.

Format, for reference (sizes in points, as extracted):

    Chicken Soft Tacos              21.2 bold, Title Case
    SERVES 2                        11.2, or "MAKES ..."
    WHY THIS RECIPE WORKS: We like the convenience ...   15, prose
    1 teaspoon vegetable oil        11.2 bold, US amounts only
    2 (6- to 8-ounce) boneless, skinless chicken breasts, trimmed ...
      Salt and pepper
    1. Heat oil in 10-inch nonstick skillet ...   15, numbered steps

The chapter openers list each recipe in ALL CAPS at 14.8 bold with a
one-line description; they're below the title size, so they stay in
"other" chunks.
"""

import re
import sys

from books.engine import find_recipe_starts_by_size

TITLE_MIN_SIZE = 21
# Bold only: 21.2 regular is never a title, but keep the rule strict.
TITLE_BOLD = True
YIELD_RE = re.compile(r"^(?:SERVES|MAKES)\b")
INGREDIENT_STYLE = "volume_paren_metric"
# The test kitchen's sidebar after a recipe, which can hold amounts of its
# own ("NOTES FROM THE TEST KITCHEN", "SECRETS TO FOOLPROOF WHIPPED CREAM").
ASIDE_RE = re.compile(r"^NOTES FROM THE TEST KITCHEN$")


# Chapter headings are 27.5; their opening sidebars carry yield lines of
# their own ("Roasted Butternut Squash Salad" / "SERVES 2"), so a chapter
# would otherwise read as one big recipe.
_CHAPTER_MIN_SIZE = 26


def find_recipe_starts(lines, layout):
    """The shared size rule, without the chapter headings."""
    starts, consumed, _ = find_recipe_starts_by_size(lines, layout, sys.modules[__name__])
    chapters = {i for i in starts if layout[i]["size"] >= _CHAPTER_MIN_SIZE}
    keep = [i for i in starts if i not in chapters]
    dropped = set()
    for i in chapters:
        j = i
        while j in consumed:
            dropped.add(j)
            j += 1
    return keep, consumed - dropped


def is_continuation(pending, last_line, line):
    """A range split across lines: "10–" / "12 dried ladyfingers"."""
    return last_line.endswith(("–", "-"))
