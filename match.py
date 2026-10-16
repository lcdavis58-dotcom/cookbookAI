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
    match_utils/matching.py          what counts as on hand, ranking
    match_utils/ingredient_names.py  normalizing what you typed
    match_utils/recipe_index.py      the index itself
"""

import re

from common import cli
from match_utils.matching import find_matches, load_staples, parse_have
from match_utils.recipe_index import load_index

# How many recipes to list in each section before summarizing the rest.
SHOW_PER_SECTION = 15


def short_name(sub_recipe):
    """A sub-recipe line without its prep notes: "9-inch / 23-cm pie crust
    (see Recommended Crusts), parbaked and cooled" -> "9-inch / 23-cm pie
    crust", "recipe Brioche Dough" -> "Brioche Dough"."""
    name = re.sub(r"\s*\([^)]*\)", "", sub_recipe.split(",", 1)[0]).strip()
    return re.sub(r"^(?:[\d½]+\s+)?(?:double |triple )?(?:recipes?|(?:half |full |regular |mile-high )?"
                  r"batch(?:es)? of)\s+", "", name, flags=re.IGNORECASE)


def describe(result):
    entry = result["entry"]
    lines = [f"  {entry['title']}  [{entry['book']}"
             + (f", p.{entry['page']}" if entry["page_confirmed"] else "") + "]"]
    lines.append(f"      uses: {', '.join(result['uses'])}")
    if result["missing"]:
        lines.append(f"      missing: {', '.join(result['missing'])}")
    also = ([f"{name} (your choice)" for name in entry.get("your_choice", [])]
            + [short_name(name) for name in entry["sub_recipes"]])
    if also:
        lines.append(f"      also needs: {'; '.join(also)}")
    if cli.DEBUG:
        lines.append(f"      [debug] staples: {', '.join(result['staples_used']) or '(none)'}"
                     f"  optional on hand: {', '.join(result['optional_on_hand']) or '(none)'}")
    return lines


def print_section(heading, results):
    print(f"\n{heading} ({len(results)}):")
    if not results:
        print("  (none)")
    for result in results[:SHOW_PER_SECTION]:
        print("\n".join(describe(result)))
    if len(results) > SHOW_PER_SECTION:
        print(f"  ...and {len(results) - SHOW_PER_SECTION} more")


def match(text):
    index = load_index()
    if index is None:
        print("No recipe index yet. Run python3 ingest.py, or python3 tools/build_recipe_index.py "
              "if the database already exists.")
        return

    have = parse_have(text)
    if not have:
        print("List the ingredients you have, separated by commas.")
        return
    print(f"You have: {', '.join(have)}  (plus pantry staples)")
    if cli.DEBUG:
        print(f"[debug] staples: {', '.join(sorted(load_staples()))}")

    results = find_matches(index, have)
    # What a general name ("cream") was taken to mean, listed once rather
    # than under every recipe it applies to.
    assumptions = []
    for result in results:
        for note in result["assumptions"]:
            if note not in assumptions:
                assumptions.append(note)
    for note in assumptions:
        print(f"  ({note})")
    print_section("You can make", [r for r in results if not r["missing"]])
    print_section("Missing one thing", [r for r in results if len(r["missing"]) == 1])


if __name__ == "__main__":
    request, cli.DEBUG = cli.parse_cli("Find recipes you can make with the ingredients you have.")
    match(request)
