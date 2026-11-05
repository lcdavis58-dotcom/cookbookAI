"""
Salt Fat Acid Heat (Samin Nosrat): settings for the shared engine
(books/engine.py). See books/__init__.py for the interface.

Format, for reference (sizes in points, as extracted):

    Lime Vinaigrette                16.9 bold
    Makes a scant 1/2 cup           15 italic, or "Serves 4"
    2 tablespoons freshly squeezed lime juice (from about 2 small limes)
    Salt                            11.3, US amounts, typed fractions
    Pour the lime juice and olive oil into a small bowl ...
                                    15, the method, unnumbered
    Variation                       15 bold, then "•" paragraphs

Most of the book is the essays on its four elements (technique for a
later pass); the recipes are in the second half. The PDF sets
fractions as "1 /2"; extraction closes them up (ingest_utils/extract.py).
"""

import re

TITLE_MIN_SIZE = 16.9
TITLE_BOLD = True
# A chapter heading sits far above the first recipe title on its page
# ("FISH" / "Slow-Roasted Salmon"); a wrapped title's lines are close.
TITLE_MAX_GAP = 20
YIELD_RE = re.compile(r"^(?:Makes|Serves)\b")
INGREDIENT_STYLE = "volume_paren_metric"
# Nothing in the text marks a step; ingest marks where the 11.3pt list
# gives way to the 15pt method (list_end_lines) and the list ends there.
STEP_RE = re.compile(r"(?!)")

_LIST_SIZE = (11.0, 11.6)
_METHOD_SIZE = (14.5, 15.5)


def list_end_lines(lines, layout):
    """Where body-size method text follows a line at the list's size."""
    ends = set()
    for i in range(1, len(layout)):
        prev, cur = layout[i - 1], layout[i]
        if (_METHOD_SIZE[0] <= cur["size"] <= _METHOD_SIZE[1]
                and _LIST_SIZE[0] <= prev["size"] <= _LIST_SIZE[1] and cur["text"].strip()):
            ends.add(i)
    return ends


def ingredient_end(lines, start):
    """The blank line ingest put before the method."""
    for i in range(start + 1, len(lines)):
        if not lines[i].strip():
            return i
    return len(lines)
