"""
Find recipes you can make with the ingredients you have.

Run:
    python3 match.py "pecans, cream cheese, lemons"
    python3 match.py egg yolks, heavy cream
    python3 match.py -d "blueberries, buttermilk"    # with debug output

Pantry staples (word_lists/universal/pantry_staples.json) are assumed on
hand and don't need listing. Recipes are only shown if they use at least
one of the ingredients you listed.

Reads the recipe index built at ingest (or by tools/build_recipe_index.py),
so it needs neither the database nor a model.

Where things live:
    actions/match.py                 the steps, and what this prints
    match_utils/matching.py         what counts as on hand, ranking
    match_utils/ingredient_names.py  normalizing what you typed
    match_utils/recipe_index.py      the index itself
    match_utils/typos.py             correcting misspelled ingredients
"""

from actions import match
from common import cli

if __name__ == "__main__":
    request, cli.DEBUG = cli.parse_cli("Find recipes you can make with the ingredients you have.")
    print(match.render(match.run(request)))
