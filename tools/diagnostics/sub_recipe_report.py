"""
How the recipe index linked each book's sub-recipes (see
match_utils/sub_recipes.py): per book, how many references were linked
by title or by kind and how many weren't, and how many plain
ingredients the book also makes. The full list of links goes to
testing/one_off/sub_recipe_links.txt (it quotes the books, so it stays
local).

Run from app/ (either form works):
    python3 tools/diagnostics/sub_recipe_report.py [BOOK_TITLE ...]
    python3 tools/diagnostics/sub_recipe_report.py --index path/to/recipe_index.json
"""

import argparse
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from common.config import PROJECT_ROOT, RECIPE_INDEX_PATH  # noqa: E402
from match_utils.recipe_index import load_index  # noqa: E402

DETAIL_PATH = os.path.join(PROJECT_ROOT, "testing", "one_off", "sub_recipe_links.txt")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("books", nargs="*", help="only these books")
    parser.add_argument("--index", default=RECIPE_INDEX_PATH, help="the recipe index to read")
    args = parser.parse_args()

    entries = load_index(args.index)
    if entries is None:
        print(f"No recipe index at {args.index}. Run tools/build_recipe_index.py first.")
        return 1
    if args.books:
        wanted = {b.lower() for b in args.books}
        entries = [e for e in entries if e["book"].lower() in wanted]
    titles = {e["recipe_id"]: e["title"] for e in entries}

    counts = defaultdict(Counter)
    details = defaultdict(list)
    for e in entries:
        book = e["book"]
        for requirement in e["ingredients"] + e["optional"]:
            how = requirement.get("how")
            if not how or how == "unlinked":
                continue
            counts[book][how] += 1
            linked = ", ".join(titles.get(i, i) for i in requirement["recipes"][:4])
            more = len(requirement["recipes"]) - 4
            details[book].append(f"  [{how:5}] {e['title']}: {requirement['name']} -> {linked}"
                                 + (f" (+{more} more)" if more > 0 else ""))
        for line in e["sub_recipes"]:
            counts[book]["unlinked"] += 1
            details[book].append(f"  [none ] {e['title']}: {line}")
        for line in e.get("unread_lines", []):
            counts[book]["unread"] += 1
            details[book].append(f"  [step ] {e['title']}: {line}")

    print(f"{'Book':40} {'title':>5} {'kind':>5} {'none':>5} {'step':>5} {'plain':>6}")
    for book in sorted(counts):
        c = counts[book]
        print(f"{book:40} {c['title']:5} {c['kind']:5} {c['unlinked']:5} {c['unread']:5} {c['plain']:6}")
    total = sum(counts.values(), Counter())
    print(f"{'(all)':40} {total['title']:5} {total['kind']:5} {total['unlinked']:5} {total['unread']:5} {total['plain']:6}")
    print("\ntitle = reference linked by name, kind = linked to every recipe of its kind "
          "(or a plain ingredient a kind covers),\nnone = reference left unlinked (counted as missing), "
          "step = step text taken for a reference (ignored),\nplain = plain ingredient the book also has a recipe for")

    os.makedirs(os.path.dirname(DETAIL_PATH), exist_ok=True)
    with open(DETAIL_PATH, "w", encoding="utf-8") as f:
        for book in sorted(details):
            f.write(f"=== {book}\n" + "\n".join(sorted(details[book])) + "\n\n")
    print(f"\nEvery link: {os.path.relpath(DETAIL_PATH)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
