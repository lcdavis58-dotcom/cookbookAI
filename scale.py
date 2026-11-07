"""
Scale a recipe up, down, or to fit an ingredient constraint.

Run:
    python3 scale.py "please double the classic whipped cream recipe"
    python3 scale.py "the chocolate whipped cream feeds 6, I need 10"
    python3 scale.py "classic whipped cream needs 2 eggs, I only have 1"
    python3 scale.py -d "double the sweet tart dough"    # with debug output

Where things live:
    actions/scale.py                 the steps, and what this prints
    query_utils/                   finding the recipe (shared with query.py),
                                     by title in query_utils/title_lookup.py
    scale_utils/ingredients.py       ingredient list -> groups (all books)
    books/<book>.py           each book's ingredient line format
    scale_utils/recipe_scaling.py    scale factor from the request, the math
    scale_utils/pan_scaling.py       pan-size scale factors
    scale_utils/measurement_display.py  amounts -> real measuring tools
    scale_utils/scaling_rules.py     non-scalable / storage-sensitive notes

Requires the same packages/models as query.py, plus a chat model that
supports tool calling (llama3.2:1b does).
"""

from actions import scale
from common import cli

if __name__ == "__main__":
    request, cli.DEBUG = cli.parse_cli("Scale a recipe from your ingested cookbooks.")
    print(scale.render(scale.run(request)))
