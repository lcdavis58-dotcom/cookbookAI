"""
Dessert Person (Claire Saffitz): settings for the shared engine
(books/engine.py). See books/__init__.py for the interface every book
module provides.

Format, for reference (sizes in points, as extracted):

    Spiced Pear Cake                21.2, can wrap
    with Maple Glaze                16.9, an optional subtitle
    Season: Fall | Active Time: 40 minutes | Total Time: 2 hours, plus time to cool
    | Difficulty: 2 (Easy) | Dairy-Free
    <intro prose>
    Makes 1 round cake
    Special Equipment: 9-inch round cake pan, stand mixer
    CAKE
    ¾ cup sugar (5.3 oz / 150g)
    2 tablespoons plus ¼ cup tahini (2.4 oz / 68g) ①
    Make the batter: In a large bowl, whisk...
"""

import re

TITLE_MIN_SIZE = 21
# "Season:" follows every recipe title (after the subtitle, if any).
YIELD_RE = re.compile(r"^Season:", re.IGNORECASE)
INGREDIENT_STYLE = "volume_paren_metric"

# Every instruction step opens with a short bolded heading and a colon
# ("Make the glaze: In a small saucepan..."). The first one ends the
# ingredient list, so a wrapped step line that happens to start with a
# number ("½ inch apart, then bake...") is never read as an ingredient.
# "Special Equipment:" has the same shape but sits before the
# ingredients, so it's skipped.
STEP_RE = re.compile(r"^[A-Z][^:]{2,80}:\s")
SKIP_RE = re.compile(r"^Special Equipment:", re.IGNORECASE)

# Where the ingredient list starts: right after the yield line ("Makes 1
# round cake", or "Serves 8"). Everything before it is skipped: the
# metadata block wraps unpredictably and can put "20 minutes (for a
# parbaked crust) | ..." at the start of a line, which looks exactly like
# a count-only ingredient, and intro prose like "So here's my secret: A
# good crust..." has the same shape as STEP_RE.
_MAKES_RE = re.compile(r"^(?:Makes|Serves)\b")
_DIFFICULTY_RE = re.compile(r"Difficulty", re.IGNORECASE)


def ingredient_start(lines):
    """Just after the "Makes"/"Serves" line, or, if a recipe has neither,
    just after the Difficulty line that ends its metadata block (searched
    only near the top, so a later mention of difficulty doesn't count)."""
    for i, line in enumerate(lines):
        if _MAKES_RE.match(line.strip()):
            return i + 1
    for i, line in enumerate(lines[:8]):
        if _DIFFICULTY_RE.search(line):
            return i + 1
    return 0
