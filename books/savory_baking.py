"""
Savory Baking (Erin Jeanne McDowell): settings for the shared engine
(books/engine.py). See books/__init__.py for the interface.

Format, for reference (sizes in points, as extracted):

    Classic Cornbread               21.2 bold, can wrap; 16.9 bold for
                                    a small extra ("Small-Batch
                                    Oven-Roasted Jam")
    <intro prose>                   15 italic, sometimes after the yield
    Makes one 8 × 8-inch/20 × 20 cm pan     11.2 bold
    DIFFICULTY: EASY                11.2
    113 g / 4 ounces / 8 tablespoons unsalted butter, melted
                                    11.2 bold, like The Fearless Baker
    1. Preheat the oven to 400°F/205°C ...
    Variations                      15 bold

A section name can sit right above a title at the same size ("Favorite
Soups" / "Cheddar Ale Soup"), well above it; a wrapped title's lines
are close together.
"""

import re

from books.engine import yield_block_length
from scale_utils.line_fallbacks import parse_fallback

TITLE_MIN_SIZE = 16.9
# 16.9 is also the size of the pull quotes, which aren't bold.
TITLE_BOLD = True
TITLE_MAX_GAP = 10
YIELD_RE = re.compile(r"^Makes\b")
HEADER_FIELD_RE = re.compile(r"^DIFFICULTY:")
INGREDIENT_STYLE = "metric_slash"


# A prose line runs the width of the column; one that long without an
# ending is mid-paragraph, so the next line can't start the list.
_FULL_LINE_CHARS = 60
_ENDS_SENTENCE_RE = re.compile(r"[.!?:)”\"’]$")


def ingredient_start(lines):
    """The shared rule (books/engine.Profile.ingredient_start), but never
    on a line that continues a paragraph: the short recipes with their
    amounts in the prose ("Olive Spread", "Stuffed" Pretzels) have no
    list, and a line deep in their prose can look like an ingredient
    ("40 cm and ½ inch/1 cm thick. Cut the dough...")."""
    profile = _profile()
    first = next((i for i, line in enumerate(lines) if YIELD_RE.match(line.strip())), None)
    if first is None:
        return len(lines)
    prev = None
    for i in range(first + yield_block_length(lines, first, HEADER_FIELD_RE), len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        if profile.STEP_RE.match(line):
            break
        mid_paragraph = (prev is not None and len(prev) >= _FULL_LINE_CHARS
                         and not _ENDS_SENTENCE_RE.search(prev))
        if not mid_paragraph and (profile.starts_ingredients(lines, i) or _has_amount(line, profile)):
            return i
        prev = line
    return len(lines)


def _has_amount(line, profile):
    """A hedged amount only the fallbacks read ("About 1050 g / 6 large
    heirloom tomatoes")."""
    parsed = parse_fallback(line, profile.parse_ingredient_line)
    return parsed is not None and bool(parsed.get("qualifier"))


def _profile():
    from books import profile_for
    return profile_for("savory_baking")
