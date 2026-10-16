"""
Show, line by line, what the ingredient parser decided about a stored
recipe: where the ingredient list was taken to start, which lines were
parsed or rejected, joined to the line above, treated as a label, or
ended the list. For finding out why a recipe comes back with missing
ingredients, or none at all (see the last section of
ingredient_frequency.py's report). Uses the same
extract_ingredient_groups that scale.py does, so whatever this shows is
what scaling sees.

Reads the recipes stored in Chroma, so it runs on the Pi.

Run from app/ (either form works):
    python3 testing/one_off/ingredient_trace.py "rice pudding cake"
    python3 testing/one_off/ingredient_trace.py "black forest" "eton mess"
    python3 testing/one_off/ingredient_trace.py --empty > empty_trace.txt
    python3 testing/one_off/ingredient_trace.py --empty --next > empty_next.txt
    python3 testing/one_off/ingredient_trace.py --late-labels > late_labels.txt

A title argument matches any recipe whose title contains it (ignoring
case). --empty traces every recipe that parses to no ingredients at all.
--next also prints the start of the chunk stored right after each
recipe, which is where a recipe's missing ingredients end up if ingest
cut the recipe short (chunk ids are numbered in book order, see
ingest.py).

--late-labels lists component-style headings (ALL CAPS, ingredients
right after) that sit after a recipe's instructions have started. Ingest
keeps those inside the recipe. That's right for a variation, but wrong
for a separate mini-recipe that has no yield line of its own, so this is
the list to check by eye after a re-ingest.
"""

import argparse
import os
import re
import sys

# Lets this run as a plain file path, not only with -m: put app/ on the
# import path so the shared modules can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from books import profile_for, strategy_for  # noqa: E402
from common.text_parsing import ALLCAPS_LINE_RE, is_component_label  # noqa: E402
from query_utils.recipe_matching import display_title, extract_title  # noqa: E402
from scale_utils.ingredients import extract_ingredient_groups  # noqa: E402
from testing.one_off.ingredient_frequency import load_recipes  # noqa: E402

# Short tags so the decision lines up in a column ahead of the text.
TAGS = {
    "before start": "  before",
    "parsed": "  PARSED",
    "rejected": "REJECTED",
    "joined to line above": "  joined",
    "group label": "   GROUP",
    "skipped": " skipped",
    "step (ends list)": "    STEP",
    "non-ingredient label (ends list)": "NOTE-END",
    "after list ended": "   after",
}


def trace_recipe(key, recipe):
    """Every (kind, line) decision for one recipe, plus how many
    ingredients were parsed in total."""
    events = []
    groups = extract_ingredient_groups(recipe["text"], strategy_for(recipe["book"]),
                                       trace=lambda kind, line: events.append((kind, line)))
    return events, sum(len(ings) for ings in groups.values())


def next_chunk(recipe):
    """(content_type, text) of the chunk stored right after this recipe's
    last part, or None if there isn't one."""
    from query_utils.retrieval import get_collection  # needs chromadb, so imported late

    numbered = [m for m in (re.match(r"^(.*)-c(\d+)$", cid) for cid in recipe["chunk_ids"]) if m]
    if not numbered:
        return None
    last = max(numbered, key=lambda m: int(m.group(2)))
    result = get_collection().get(ids=[f"{last.group(1)}-c{int(last.group(2)) + 1}"])
    if not result["ids"]:
        return None
    return result["metadatas"][0].get("content_type", "unknown"), result["documents"][0]


def print_next(recipe, max_lines=12):
    found = next_chunk(recipe)
    if found is None:
        print("  (no chunk stored after this recipe)\n")
        return
    content_type, text = found
    print(f"  --- next chunk [{content_type}], first {max_lines} lines ---")
    for line in text.splitlines()[:max_lines]:
        print(f"  {line}")
    print()


def late_labels(recipe):
    """(heading, first line after it) for every component-style heading
    that comes after this recipe's first instruction step."""
    profile = profile_for(strategy_for(recipe["book"]))
    lines = recipe["text"].splitlines()
    found = []
    steps_started = False
    # From where the ingredients start, since Dessert Person's "Season: ..."
    # metadata line has the same shape as one of its steps.
    for i in range(profile.ingredient_start(lines), len(lines)):
        stripped = lines[i].strip()
        # Skipped lines first, the same order extract_ingredient_groups
        # uses: "Special Equipment: ..." also has a step's shape.
        if profile.SKIP_RE and profile.SKIP_RE.match(stripped):
            continue
        if profile.STEP_RE.match(stripped):
            steps_started = True
        elif (steps_started and ALLCAPS_LINE_RE.match(stripped)
              and is_component_label(lines, i, profile)):
            following = next((l.strip() for l in lines[i + 1:] if l.strip()), "")
            found.append((stripped, following))
    return found


def print_trace(key, recipe, events, parsed_count):
    title = display_title(extract_title(recipe["text"], recipe["book"]) or key)
    print("=" * 78)
    print(f"{title}  [{recipe['book']}, {key}]  {parsed_count} ingredient(s) parsed")
    print("=" * 78)
    # "joined" lines are reported when they're read, but the line they
    # were joined onto is only parsed/rejected afterwards, so the order
    # below is the order decisions were made, not always page order.
    for kind, line in events:
        print(f"{TAGS.get(kind, kind):>8} | {line}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("titles", nargs="*", help="title text to match (case-insensitive)")
    parser.add_argument("--empty", action="store_true",
                        help="trace every recipe with no parsed ingredients")
    parser.add_argument("--next", action="store_true",
                        help="also show the start of the chunk stored after each recipe")
    parser.add_argument("--late-labels", action="store_true",
                        help="list component headings that come after a recipe's steps")
    args = parser.parse_args()
    if args.late_labels:
        count = 0
        for key, recipe in sorted(load_recipes().items()):
            if strategy_for(recipe["book"]) is None:
                continue
            found = late_labels(recipe)
            if found:
                title = display_title(extract_title(recipe["text"], recipe["book"]) or key)
                print(f"{title}  [{recipe['book']}]")
                for heading, following in found:
                    print(f"    {heading}  ->  {following}")
                count += len(found)
        print(f"{count} heading(s) after a recipe's steps.")
        sys.exit(0)
    if not args.titles and not args.empty:
        parser.error("give at least one title, or --empty, or --late-labels")

    wanted = [t.lower() for t in args.titles]
    found = 0
    for key, recipe in sorted(load_recipes().items()):
        if strategy_for(recipe["book"]) is None:
            continue
        title = (extract_title(recipe["text"], recipe["book"]) or key).lower()
        events, parsed_count = trace_recipe(key, recipe)
        if any(w in title for w in wanted) or (args.empty and parsed_count == 0):
            print_trace(key, recipe, events, parsed_count)
            if args.next:
                print_next(recipe)
            found += 1
    print(f"{found} recipe(s) traced.")
