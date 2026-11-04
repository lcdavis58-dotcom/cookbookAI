"""
What's For Dessert (Claire Saffitz): settings for the shared engine
(books/engine.py). See books/__init__.py for the interface.

Format, for reference (sizes in points, as extracted):

    Roasted Red Plum & Biscoff      21.2 bold, sometimes, a first title
    Icebox Cake                     30 bold, can wrap
    with Grapefruit                 21.2 bold, an optional subtitle
    SERVES 8                        11.2, or "MAKES ABOUT 24 COOKIES"
    DIFFICULTY: 1 (Very Easy)       11.2, the header block: also
    GLUTEN-FREE                     ACTIVE TIME, TOTAL TIME, SERVE WITH,
    SPECIAL EQUIPMENT: ...          SPECIAL EQUIPMENT (wraps)
    <intro prose>                   16.9
    MELON GRANITA                   11.2, ALL-CAPS component labels
    2 cups full-fat cottage cheese (15.9 oz / 450g), chilled
    1 pound (454g) ripe seedless watermelon ...
    MAKE THE MELON GRANITA: In a medium bowl, ...
    Can I…                          21.2 bold, a Q&A box ending the recipe
"""

import re
import sys

from books.engine import find_recipe_starts_by_size
from books.line_styles import STYLES
from common.text_parsing import heading_text

TITLE_MIN_SIZE = 27
YIELD_RE = re.compile(r"^(?:SERVES|MAKES)\b")
HEADER_FIELD_RE = re.compile(
    r"^(?:DIFFICULTY|ACTIVE TIME|TOTAL TIME|SPECIAL EQUIPMENT|SERVE WITH"
    r"|(?:DAIRY|GLUTEN)-FREE|VEGAN)\b")
# Dessert Person's printing: "¾ cup sugar (5.3 oz / 150g)".
INGREDIENT_STYLE = "volume_paren_metric"
# Every step opens with an ALL-CAPS heading and a colon ("MAKE THE
# GRANITA: In a medium bowl...", "FOR CRÈME BRÛLÉE: ..."), numbered in
# the Essential Recipes chapter ("1. COMBINE THE DRY INGREDIENTS: ...").
# Component labels have no colon.
STEP_RE = re.compile(r"^(?:\d+\.\s+)?[A-ZÀ-Ý][A-ZÀ-Ý0-9 ,&’'“”()\-]{2,80}:\s")
# The Essential Recipes chapter boxes a technique ("ESSENTIAL TECHNIQUE" /
# "SOFTENING GELATIN") into the recipe, sometimes before the first step.
ASIDE_RE = re.compile(r"^ESSENTIAL TECHNIQUE$")

# Some titles start with a line at the subtitle size (21.2 bold) above the
# 30pt part: "Roasted Red Plum & Biscoff" / "Icebox Cake". Bold lines that
# size elsewhere are subtitles ("with Grapefruit") or the "Can I…" box.
_LEAD_MIN_SIZE, _LEAD_MAX_SIZE = 20.5, 22


def _is_component_recipe(lines, layout, i):
    """A recipe inside another one ("HOT FUDGE SAUCE" in Profiterole Bar):
    an ALL-CAPS line at 21.2, not bold, with its own yield line next."""
    record = layout[i]
    return (not record["bold"] and _LEAD_MIN_SIZE <= record["size"] <= _LEAD_MAX_SIZE
            and bool(heading_text(lines[i])) and i + 1 < len(lines)
            and bool(YIELD_RE.match(lines[i + 1].strip())))


def find_recipe_starts(lines, layout):
    """The shared size rule on the 30pt titles, then each start moved up
    over a 21.2 bold line right above it, which is the title's first
    line. Component recipes with their own yield line start recipes too."""
    starts, consumed, _ = find_recipe_starts_by_size(lines, layout, sys.modules[__name__])
    components = [i for i in range(len(lines)) if _is_component_recipe(lines, layout, i)]
    consumed.update(components)
    moved = list(components)
    for start in starts:
        while start > 0:
            above = layout[start - 1]
            # Not checked against the page: "Salty Brownie" ends one page
            # and "Ice Cream Sandwiches" starts the next.
            if not (above["bold"] and _LEAD_MIN_SIZE <= above["size"] <= _LEAD_MAX_SIZE
                    and above["text"].strip()):
                break
            start -= 1
            consumed.add(start)
        moved.append(start)
    return sorted(moved), consumed


# "A pinch plus ½ teaspoon Diamond Crystal kosher salt or ¼ teaspoon" /
# "Morton kosher salt": a line ending on its alternative's unit, so the
# capitalized next line is that alternative's name.
_ENDS_ON_UNIT_RE = re.compile(r"\bor\s+[\d¼½¾⅓⅔⅛]+\s+(?:teaspoons?|tablespoons?|cups?)$")


def is_continuation(pending, last_line, line):
    """Also a line after one left on a comma ("2 sticks unsalted butter
    (8 oz / 227g), preferably European," / "European-style, or cultured,
    ..."), unless it's an ingredient of its own."""
    if _ENDS_ON_UNIT_RE.search(last_line):
        return True
    return last_line.endswith(",") and not STYLES[INGREDIENT_STYLE](line)
