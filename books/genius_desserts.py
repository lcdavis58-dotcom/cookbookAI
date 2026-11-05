"""
Genius Desserts (Kristen Miglore / Food52): settings for the shared
engine (books/engine.py). See books/__init__.py for the interface.

Format, for reference (sizes in points, as extracted):

    Parsley Cake                    25, Title Case, can wrap
    FROM ROBERTA'S & KATY PEETZ     15, the recipe's source
    <headnote>                      16.9
    SERVES 12 TO 14                 15, or "MAKES ..."
    2⅓ cups (290g) all-purpose flour (see this page)
    4 large eggs, at room temperature
    1 Combine about one-quarter of the parsley ...   steps numbered
                                    without a period
"""

import re

TITLE_MIN_SIZE = 24
YIELD_RE = re.compile(r"^(?:MAKES|SERVES)\b")
# "1½ cups (288 g) granulated sugar": the grams after the unit, as in
# The Cookie Book.
INGREDIENT_STYLE = "volume_paren_metric"
# "1 Combine ...", "2 With the blender on ...": a number with no period,
# then a capitalized word. No ingredient line here has that shape (counts
# are followed by lowercase: "4 large eggs").
STEP_RE = re.compile(r"^\d{1,2}\s+[A-Z]")

# "... baking apples like" / "Honeycrisp or a mix of apples, cored ...":
# a line left on a word that needs more after it.
_HANGING_WORD_RE = re.compile(r"\b(?:like|and|or|of|with|plus|such as|into|preferably)$")


def is_continuation(pending, last_line, line):
    return bool(_HANGING_WORD_RE.search(last_line))
