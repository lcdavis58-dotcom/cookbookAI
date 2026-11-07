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
    match_utils/typos.py             correcting misspelled ingredients
"""

from common import cli
from match_utils.matching import find_matches, load_staples, parse_have
from match_utils.recipe_index import load_index, load_ingredient_words
from match_utils.typos import TypoFixer
from match_utils.typos import describe as describe_typos

# How many recipes to list in each section before summarizing the rest.
SHOW_PER_SECTION = 15


def describe(result):
    entry = result["entry"]
    lines = [f"  {entry['title']}  [{entry['book']}"
             + (f", p.{entry['page']}" if entry["page_confirmed"] else "") + "]"]
    lines.append(f"      uses: {', '.join(result['uses'])}")
    if result.get("stand_ins"):
        lines.append(f"      using {'; '.join(result['stand_ins'])}")
    if result.get("makes"):
        scratch = set(result.get("from_scratch", []))
        lines.append("      make first: " + ", ".join(
            f"{name} (from pantry staples)" if name in scratch else name for name in result["makes"]))
    if result["missing"]:
        lines.append(f"      missing: {', '.join(result['missing'])}")
    # Unlinked sub-recipes are counted in "missing" now; only the
    # placeholders that can't be matched are shown on their own.
    also = [f"{name} (your choice)" for name in entry.get("your_choice", [])]
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
    # Misspelled ingredients are corrected before anything else, and
    # said so first, so a typo never silently loses every match.
    have, corrections = TypoFixer(load_ingredient_words(entries=index), load_staples()).fix(have)
    if corrections:
        print(describe_typos(corrections))
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
    ready = [r for r in results if not r["missing"]]
    print_section("You can make", [r for r in ready if not r["from_scratch"]])
    # Makeable, but only by making a sub-recipe (a pie dough) entirely
    # from pantry staples: real work the person didn't mention.
    print_section("You can make, with a sub-recipe from scratch", [r for r in ready if r["from_scratch"]])
    print_section("Missing one thing", [r for r in results if len(r["missing"]) == 1])


if __name__ == "__main__":
    request, cli.DEBUG = cli.parse_cli("Find recipes you can make with the ingredients you have.")
    match(request)
