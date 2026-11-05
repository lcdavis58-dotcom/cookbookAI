"""
Ratio (Michael Ruhlman): settings for the shared engine (books/engine.py).
See books/__init__.py for the interface.

Format, for reference (sizes in points, as extracted):

    Classic Sugar Cookies           16.9 italic (21.2 italic for the
                                    ratio's own base recipe)
    <headnote>                      15, sans-serif
    8 ounces unsalted butter (2 sticks)     15 ITALIC serif: the list
    1 large egg
    Preheat your oven to 350°F. ... 15, sans-serif: the method, unnumbered
    YIELD: ABOUT 24 COOKIES         11.2, AFTER the recipe

Most of the book is the ratios and the reasoning behind them (technique
for a later pass). The yield follows the method, so the list starts at
the first ingredient after the title rather than after the yield, and it
ends where the italic list gives way to the method (list_end_lines, as in
books/htcev.py).
"""

import re

TITLE_MIN_SIZE = 16.9
TITLE_ITALIC = True
YIELD_RE = re.compile(r"^(?:YIELD|SERVES|MAKES)\b")
INGREDIENT_STYLE = "volume_paren_metric"
STEP_RE = re.compile(r"(?!)")

_BODY_MIN, _BODY_MAX = 14.5, 15.5


def _is_list_line(record):
    return _BODY_MIN <= record["size"] <= _BODY_MAX and record["italic"] and bool(record["text"].strip())


def list_end_lines(lines, layout):
    """Where body text stops being italic after an italic list line."""
    ends = set()
    for i in range(1, len(layout)):
        cur = layout[i]
        if (_is_list_line(layout[i - 1]) and _BODY_MIN <= cur["size"] <= _BODY_MAX
                and not cur["italic"] and cur["text"].strip()):
            ends.add(i)
    return ends


def ingredient_start(lines):
    """The first line after the title that starts an ingredient list."""
    profile = _profile()
    for i in range(1, len(lines)):
        if lines[i].strip() and profile.starts_ingredients(lines, i):
            return i
    return len(lines)


def ingredient_end(lines, start):
    """The blank line ingest put before the method."""
    for i in range(start + 1, len(lines)):
        if not lines[i].strip():
            return i
    return len(lines)


def _profile():
    from books import profile_for
    return profile_for("ratio")
