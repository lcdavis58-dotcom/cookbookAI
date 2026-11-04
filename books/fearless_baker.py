"""
The Fearless Baker (Erin Jeanne McDowell): settings for the shared
engine (books/engine.py). See books/__init__.py for the interface.

Format, for reference (sizes in points, as extracted):

    Jammy Hand Pies                 30, Title Case
    <intro prose>                   16.9
    Makes 12 individual pies        15
    DIFFICULTY: Easy                11.2
    MAKE AHEAD AND STORAGE: The beignet batter can be made
    up to 1 day ahead ...           15, a paragraph
    120 g / 1 cup all-purpose flour 11.2, like The Book On Pie
    85 g / 2 large eggs
    1. Preheat the oven to 350°F...
"""

import re

TITLE_MIN_SIZE = 27
YIELD_RE = re.compile(r"^Makes\b")
# The yield block runs on through the difficulty line and the make-ahead
# paragraph; its wrapped lines are taken by the shared rules (lowercase
# starts, lines left hanging).
HEADER_FIELD_RE = re.compile(r"^(?:DIFFICULTY|MAKE AHEAD AND STORAGE):")
INGREDIENT_STYLE = "metric_slash"

# SINGLE CRUST / DOUBLE CRUST: alternative batch sizes of a dough, only
# one gets made.
BATCH_LABEL_RE = re.compile(r"^(?:SINGLE|DOUBLE) CRUST$")
