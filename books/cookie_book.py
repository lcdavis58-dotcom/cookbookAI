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

from books.line_styles import STYLES
from common.text_parsing import heading_text
from scale_utils.line_fallbacks import parse_fallback

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


def _is_ingredient(line):
    if _parse(line):
        return True
    parsed = parse_fallback(line, _parse)
    if parsed is None:
        return False
    if not parsed.get("unmeasured"):
        return True
    return len(line) <= _UNMEASURED_MAX_CHARS or bool(_PURPOSE_RE.search(line))


def _is_wrap(pending, line):
    """The shared wrap signals (scale_utils/ingredients.py): a parenthesis
    left open, or a lowercase or "(" start."""
    return pending.count("(") > pending.count(")") or line[:1].islower() or line.startswith("(")


def ingredient_end(lines, start):
    """Where the steps begin: the first line from start that isn't an
    ingredient, the wrap of one, or an ALL-CAPS group label."""
    pending = None
    for i in range(start, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        if pending is not None and _is_wrap(pending, line):
            pending = f"{pending} {line}"
            continue
        if heading_text(line):
            pending = None
            continue
        if _is_ingredient(line):
            pending = line
            continue
        return i
    return len(lines)
