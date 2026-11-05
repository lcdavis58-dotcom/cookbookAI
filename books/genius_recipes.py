"""
Genius Recipes (Kristen Miglore / Food52): settings for the shared
engine (books/engine.py). See books/__init__.py for the interface.

The same layout as Genius Desserts (books/genius_desserts.py), with the
yield in Title Case and mostly US-only amounts:

    Chicken Thighs with Lemon       25, can wrap
    FROM CANAL HOUSE                11.2, the recipe's source
    <headnote>                      15
    Serves 4                        11.2, or "Makes ..."
    1 tablespoon olive oil
    Salt and freshly ground black pepper
    1 Put the olive oil into a large, heavy skillet ...   steps numbered
                                    without a period
"""

import re

from books.genius_desserts import STEP_RE, is_continuation  # noqa: F401  (same printing)

TITLE_MIN_SIZE = 24
YIELD_RE = re.compile(r"^(?:Makes|Serves)\b")
INGREDIENT_STYLE = "volume_paren_metric"
