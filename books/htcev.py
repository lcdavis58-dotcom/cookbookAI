"""
How to Cook Everything Vegetarian (Mark Bittman): settings for the
shared engine (books/engine.py). See books/__init__.py for the interface.

Format, for reference (sizes in points, as extracted):

    Fried Fresh Cheese              21.2, sans-serif, Title Case
    MAKES: 4 to 6 servings          11.2
    TIME: 15 minutes with premade cheese
    <headnote>                      16.9, serif
    2 tablespoons chickpea flour, ground masoor or channa dal, or
      cornmeal, or more as needed   15, SANS-SERIF, ASCII fractions
    Salt and freshly ground black pepper
    Put the chickpea flour and 6 tablespoons water in a small bowl and
    whisk ...                       15, SERIF: the method, unnumbered
    Variations                      16.9 italic

The list and the method are the same size and the steps carry no
numbers, so the font is the only thing that tells them apart; ingest
marks the change (list_end_lines) and scale ends the list there.
"""

import re

TITLE_MIN_SIZE = 21
YIELD_RE = re.compile(r"^MAKES:")
HEADER_FIELD_RE = re.compile(r"^TIME:")
INGREDIENT_STYLE = "volume_paren_metric"
# Nothing marks a step in the text; the list ends at the blank line
# ingest puts before the method (ingredient_end).
STEP_RE = re.compile(r"(?!)")

_BODY_MIN, _BODY_MAX = 14.5, 15.5


def _is_body(record, family):
    return (_BODY_MIN <= record["size"] <= _BODY_MAX and family in record["font"]
            and bool(record["text"].strip()))


def list_end_lines(lines, layout):
    """Where a body-size sans-serif block (an ingredient list) gives way
    to body-size serif (the method)."""
    ends = set()
    for i in range(1, len(layout)):
        if _is_body(layout[i], "Serif") and "Sans" not in layout[i]["font"] \
                and _is_body(layout[i - 1], "Sans"):
            ends.add(i)
    return ends


def ingredient_end(lines, start):
    """The blank line ingest put before the method."""
    for i in range(start + 1, len(lines)):
        if not lines[i].strip():
            return i
    return len(lines)
