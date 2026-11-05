"""
Momofuku Milk Bar (Christina Tosi): settings for the shared engine
(books/engine.py). See books/__init__.py for the interface.

Format, for reference (sizes in points, as extracted):

    cereal milk™ ice cream pie      25, all lowercase; 21.2 for the
                                    smaller recipes ("corn cookies")
    MAKES 1 (10-INCH) PIE; SERVES 8 TO 10       11.2
    <intro prose>                   11.2, sometimes
    225 g butter, at room temperature           11.2
    [16 tablespoons (2 sticks)]     the volume, on its own line
    1 egg
    ½ recipe Cornflake Crunch
    [180 g (2 cups)]
    We use corn flour in the corn cookies to deepen the flavor. If you
    can't find corn flour, ...      11.2, a note after the list
    1. Combine the butter and sugar ...         15, numbered steps
"""

import re

from books.engine import end_of_unmarked_list
from books.line_styles import STYLES

TITLE_MIN_SIZE = 21
YIELD_RE = re.compile(r"^MAKES\b")
# The yield line is ALL CAPS and can wrap onto a line that's only that
# ("...SWISS & MUSTARD" / "CROISSANTS"); the book has no ALL-CAPS groups.
HEADER_FIELD_RE = re.compile(r"^[A-Z0-9 ,&;'’()\-]+$")
INGREDIENT_STYLE = "metric_bracket_volume"
_parse = STYLES[INGREDIENT_STYLE]

# A note between the list and the steps ("We use corn flour in the corn
# cookies to deepen the flavor. If you can't") ends the list. The book's
# unmeasured ingredients are short ("Nonstick cooking spray").
_UNMEASURED_MAX_CHARS = 40
_PURPOSE_RE = re.compile(r"\boptional\b|\bfor\s+(?:serving|garnish|dusting|the pan)\b", re.IGNORECASE)


def is_continuation(pending, last_line, line):
    """The volume line under a weighed one: "[2 cups]", or "1½ cups]"
    where the PDF lost the opening bracket."""
    return line.startswith("[") or (line.endswith("]") and "[" not in line)


# The layer cakes list their equipment after the ingredients:
# "special equipment" / "1 (6-inch) cake ring" / "2 strips acetate".
_EQUIPMENT_RE = re.compile(r"^special equipment$", re.IGNORECASE)


def ingredient_end(lines, start):
    """See books/engine.end_of_unmarked_list; the list also ends at
    "special equipment"."""
    end = end_of_unmarked_list(lines, start, _parse, _UNMEASURED_MAX_CHARS, _PURPOSE_RE,
                               continues=lambda pending, line: is_continuation(pending, None, line))
    equipment = next((i for i in range(start, end) if _EQUIPMENT_RE.match(lines[i].strip())), end)
    return min(end, equipment)
