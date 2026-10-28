"""
How often each ingredient appears across every ingested recipe. The first
step toward "what can I make with what I have": the frequencies show
which ingredients are pantry staples (safe to assume) and which ones
actually tell recipes apart, and the rest of the report shows how well
ingredient names can be normalized before matching is built on them.

Reads the recipes already stored in Chroma (no re-ingest, no PDFs needed)
and parses them with the same extract_ingredient_groups scale.py uses,
so it needs the database and runs on the Pi.

Run from app/ (either form works):
    python3 tools/diagnostics/ingredient_frequency.py
    python3 -m tools.diagnostics.ingredient_frequency
    python3 tools/diagnostics/ingredient_frequency.py --csv ingredients.csv
    python3 tools/diagnostics/ingredient_frequency.py > report.txt

Normalization here is deliberately light: it only removes what doesn't
change WHICH ingredient it is (amounts, parentheticals, prep notes after
a comma, size/state/unit words like "large", "melted" or "ounces",
plurals). Varieties stay distinct, salted butter is not unsalted butter,
light brown sugar is not dark brown sugar. Names that might be the same
thing are listed for a person to decide, never merged automatically. The
rules live in match_utils/ingredient_names.py and
word_lists/universal/ingredient_normalization.json.
"""

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

# Lets this run as a plain file path, not only with -m: put app/ on the
# import path so the shared modules can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from books import strategy_for  # noqa: E402
from match_utils.ingredient_names import normalize, pieces  # noqa: E402
from match_utils.recipe_index import load_recipes  # noqa: E402
from query_utils.recipe_matching import display_title, extract_title  # noqa: E402
from scale_utils.ingredients import extract_ingredient_groups  # noqa: E402


def analyze(recipes):
    """Parse and normalize every recipe. Returns the per-recipe ingredient
    sets plus everything the report needs about how names were handled."""
    per_recipe = {}            # key -> set of normalized names
    raw_forms = defaultdict(Counter)   # normalized -> Counter of original names
    flagged = defaultdict(lambda: defaultdict(set))  # flag -> normalized -> titles
    unparsed = []              # (book, title, line)
    empty = []                 # (book, title) with nothing parsed

    for key, recipe in recipes.items():
        book, text = recipe["book"], recipe["text"]
        title = display_title(extract_title(text, book) or key)
        strategy = strategy_for(book)
        if strategy is None:
            continue
        # Lines the parser rejected inside an ingredient block: dropped
        # silently by scaling, but exactly what this report needs to show
        # (like "Butter for the pan", which has no amount).
        def trace(kind, line):
            if kind == "rejected":
                unparsed.append((book, title, line))
        groups = extract_ingredient_groups(text, strategy, trace=trace)

        names = set()
        for group_name, ingredients in groups.items():
            for ing in ingredients:
                norm, flags = normalize(ing["name"])
                if not norm:
                    continue
                # Everything in an optional component (OPTIONAL TOPPING)
                # is optional, whatever the line itself says.
                if groups.kinds.get(group_name) == "optional":
                    flags.add("optional")
                for flag in flags:
                    flagged[flag][norm].add(title)
                # Sub-recipe references, garnishes and placeholders don't
                # say anything about what the recipe needs from the pantry.
                if not flags & {"sub_recipe", "optional", "ignored"}:
                    # Split the same way the recipe index does.
                    for piece in pieces(norm, ing.get("unmeasured")):
                        names.add(piece)
                        raw_forms[piece][ing["name"]] += 1
        if names:
            per_recipe[key] = names
        else:
            empty.append((book, title))

    return per_recipe, raw_forms, flagged, unparsed, empty


def near_duplicates(names):
    """Pairs where one name is the other with extra words in front
    ("butter" / "unsalted butter", "kosher salt" / "diamond crystal kosher
    salt"). Sometimes a real variety difference, sometimes the same thing
    written two ways, which is a person's call."""
    pairs = []
    for short in names:
        for long in names:
            if short != long and long.endswith(" " + short):
                pairs.append((short, long))
    return sorted(pairs)


def print_report(recipes, per_recipe, raw_forms, flagged, unparsed, empty):
    books = sorted({r["book"] for r in recipes.values()})
    recipe_books = {key: recipes[key]["book"] for key in per_recipe}
    total = len(per_recipe)

    counts = Counter()
    by_book = defaultdict(Counter)
    for key, names in per_recipe.items():
        counts.update(names)
        by_book[recipe_books[key]].update(names)
    book_totals = Counter(recipe_books.values())

    print("=" * 78)
    print("INGREDIENT FREQUENCY REPORT")
    print("=" * 78)
    print(f"Books: {', '.join(books)}")
    print(f"Recipes in database: {len(recipes)}, with at least one parsed ingredient: {total}")
    for book in books:
        print(f"  {book}: {book_totals[book]} recipes")
    print(f"Distinct normalized ingredients: {len(counts)}"
          f" ({sum(1 for c in counts.values() if c == 1)} appear in only one recipe)")

    print("\n--- Frequency (share of recipes that use it) " + "-" * 32)
    short = {b: "".join(w[0] for w in b.split()).upper() for b in books}
    book_cols = "  ".join(f"{short[b]:>5}" for b in books)
    print(f"{'all':>5}  {'n':>4}  {book_cols}  ingredient")
    for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        per_book = "  ".join(
            f"{100 * by_book[b][name] / book_totals[b]:4.0f}%" if book_totals[b] else "    -"
            for b in books)
        print(f"{100 * n / total:4.0f}%  {n:>4}  {per_book}  {name}")
    print("(book columns: " + ", ".join(f"{short[b]} = {b}" for b in books) + ")")

    print("\n--- What normalization merged (counted lines only, check nothing should have"
          " stayed separate) ---")
    for name in sorted(raw_forms):
        forms = raw_forms[name]
        if len(forms) > 1:
            print(f"{name}")
            for form, n in forms.most_common():
                print(f"    {n:>3}x  {form}")

    print("\n--- Possible duplicates, NOT merged (one name ends with the other) ---")
    for short_name, long_name in near_duplicates(counts):
        print(f"  {short_name!r} ({counts[short_name]})  vs  {long_name!r} ({counts[long_name]})")

    sections = [
        ("sub_recipe", "References to other recipes (left out of the counts)"),
        ("optional", "Optional / garnish / pan prep (left out of the counts for that recipe)"),
        ("ignored", "On the ignore list (left out of the counts)"),
        ("alternative", "'X or Y' choices (counted as written, matching will need to split them)"),
    ]
    for flag, heading in sections:
        print(f"\n--- {heading} ---")
        for name, titles in sorted(flagged[flag].items()):
            print(f"  {name}  [{len(titles)} recipe(s): {', '.join(sorted(titles)[:3])}"
                  f"{', ...' if len(titles) > 3 else ''}]")

    print(f"\n--- Lines in an ingredient list the parser rejected ({len(unparsed)}) ---")
    for book, title, line in unparsed:
        print(f"  [{short[book]}] {title}: {line!r}")

    print(f"\n--- Recipes with no parsed ingredients ({len(empty)}) ---")
    for book, title in sorted(empty):
        print(f"  [{short.get(book, book)}] {title}")


def write_csv(path, recipes, per_recipe, raw_forms):
    books = sorted({recipes[key]["book"] for key in per_recipe})
    counts = Counter()
    by_book = defaultdict(Counter)
    for key, names in per_recipe.items():
        counts.update(names)
        by_book[recipes[key]["book"]].update(names)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ingredient", "recipes", "share"] + books + ["original_names"])
        for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            writer.writerow([name, n, f"{n / len(per_recipe):.3f}"]
                            + [by_book[b][name] for b in books]
                            + [" | ".join(raw_forms[name])])
    print(f"\nWrote {len(counts)} ingredients to {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--csv", help="also write the frequency table to this CSV file")
    args = parser.parse_args()

    recipes = load_recipes()
    if not recipes:
        sys.exit("No recipe chunks found in the database. Has ingest.py been run?")
    per_recipe, raw_forms, flagged, unparsed, empty = analyze(recipes)
    print_report(recipes, per_recipe, raw_forms, flagged, unparsed, empty)
    if args.csv:
        write_csv(args.csv, recipes, per_recipe, raw_forms)
