"""
The Cookie Book (Rebecca Firth): settings for the shared engine
(books/engine.py). See books/__init__.py for the interface.

Format, for reference (sizes in points, as extracted):

    BROWN BUTTER CHOCOLATE          30, ALL CAPS, bold (a line can be
    CHIP COOKIES                    regular weight), wraps
    <intro prose>                   15, after a few photo pages
    MAKES 30 COOKIES                15
    10 tablespoons (143 g) unsalted butter
    ½ cup (118 ml) sunflower seed oil or other neutral oil
    2 large eggs, room temperature
    Sea salt flakes for dusting on top, optional
    GLAZE                           15 bold, ALL-CAPS component labels,
    2 cups (260 g) powdered sugar   all before the first step
    Preheat your oven to 375°F (190°C). Place a rack in the top third of
    the oven ...                    steps are plain paragraphs
    TIP                             an aside after the steps

The PDF's ligatures come out as IPA letters ("ɻour"); extraction expands
them (ingest_utils/extract.py).
"""

import re

from books.engine import end_of_unmarked_list
from books.line_styles import STYLES

TITLE_MIN_SIZE = 27
YIELD_RE = re.compile(r"^MAKES\b")
# "1½ cups (288 g) granulated sugar", like Dessert Person with the metric
# amount after the unit.
INGREDIENT_STYLE = "volume_paren_metric"
_parse = STYLES[INGREDIENT_STYLE]

# The steps are paragraphs with nothing marking them, so the list ends at
# the first line that isn't part of it (ingredient_end); STEP_RE never
# matches.
STEP_RE = re.compile(r"(?!)")

# An unmeasured ingredient ("Sprinkles, optional", "Sea salt flakes for
# dusting on top, optional") is short or says what it's for; a step's
# first line runs the width of the column.
_UNMEASURED_MAX_CHARS = 45
_PURPOSE_RE = re.compile(
    r"\boptional\b|\bfor\s+(?:dusting|sprinkling|rolling|garnish|serving|decorating|the tops?)\b",
    re.IGNORECASE)


# Two titles leave out the dish their chapter is about (the book's index
# prints them the same way), so they're also found by the full name.
TITLE_ALIASES = {
    "Favorite Thin and Crispy": ["Favorite Thin and Crispy Chocolate Chip Cookies"],
    "Spiced Chewy Molasses": ["Spiced Chewy Molasses Cookies"],
}


def ingredient_end(lines, start):
    """Where the steps begin: see books/engine.end_of_unmarked_list."""
    return end_of_unmarked_list(lines, start, _parse, _UNMEASURED_MAX_CHARS, _PURPOSE_RE)
