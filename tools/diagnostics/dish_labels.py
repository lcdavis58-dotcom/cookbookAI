"""
How well the dish labels came out (match_utils/dish_labels.py): how many
recipes have each type, a sample of each, the recipes whose title names
a type the model didn't give, and the recipes with no type at all.

Run from app/ after building the index:
    python3 tools/diagnostics/dish_labels.py
    python3 tools/diagnostics/dish_labels.py --type cookie     # every recipe of one type
    python3 tools/diagnostics/dish_labels.py --sample 10       # titles shown per type
    python3 tools/diagnostics/dish_labels.py --key             # score against the hand-checked key
    python3 tools/diagnostics/dish_labels.py --holdout         # score against the hold-out set

The key (testing/evals/dish_label_key.json) is a set of recipes with
their types checked by hand: a recipe is right when its labels include
at least one of its "types" and nothing outside "types" and "also".
The key was tuned against while the types were written, so its score
runs high; the hold-out set (dish_label_holdout.json, recipes picked at
random from the rest) wasn't, and is the honest number: don't tune
types to it. Recipes in dish_label_overrides.json are left out of both
scores, which measure the labeling, not the hand fixes.
"""

import argparse
import json
import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from match_utils.dish_labels import load_overrides, load_types, model_labels, override_for, title_dishes  # noqa: E402
from match_utils.recipe_index import load_index  # noqa: E402
from tools.run_evals import CASES_PATH  # noqa: E402

KEY_PATH = os.path.join(os.path.dirname(CASES_PATH), "dish_label_key.json")
HOLDOUT_PATH = os.path.join(os.path.dirname(CASES_PATH), "dish_label_holdout.json")


def load_key(path=KEY_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["recipes"]


def judge(labels, checked):
    """"right", "partly" (a right type, and a wrong one too), "wrong"
    (none of the right types) or "missing" (no labels at all)."""
    labels = set(labels or [])
    if not labels:
        return "missing"
    if not labels & set(checked["types"]):
        return "wrong"
    return "right" if labels <= set(checked["types"]) | set(checked["also"]) else "partly"


def score_key(labels_of, key, overrides=None):
    """labels_of: {(title, book): labels}. Lines scoring them against the
    key, with the ones not right listed. Recipes in overrides are left
    out."""
    skipped = [c for c in key if override_for(c, overrides or {}) is not None]
    key = [c for c in key if c not in skipped]
    verdicts = [(c, judge(labels_of.get((c["title"], c["book"])), c)) for c in key]
    counts = {v: sum(1 for _, x in verdicts if x == v) for v in ("right", "partly", "wrong", "missing")}
    lines = [f"{counts['right']}/{len(key)} right, {counts['partly']} partly (a wrong type too), "
             f"{counts['wrong']} wrong, {counts['missing']} with no type"
             + (f" ({len(skipped)} left out: set by hand in the overrides)" if skipped else "")]
    for c, verdict in verdicts:
        if verdict != "right":
            got = sorted(labels_of.get((c["title"], c["book"])) or [])
            lines.append(f"  {verdict}: {c['title']} ({c['book']}): {got}, should be {c['types']}"
                         + (f" (or also {c['also']})" if c["also"] else ""))
    return lines


def report(entries, labels, types, sample=5, only=None, seed=0):
    lines, rng = [], random.Random(seed)
    by_type = defaultdict(list)
    for e in entries:
        for dish in e.get("dishes", []):
            by_type[dish].append(e)
    if only:
        found = sorted(by_type.get(only, []), key=lambda e: (e["book"], e["title"]))
        lines.append(f"{only}: {len(found)} recipes")
        for e in found:
            model = labels.get(e["recipe_id"], [])
            lines.append(f"  {e['title']} ({e['book']})" + ("" if only in model else "  [title only]"))
        return lines

    unlabeled = [e for e in entries if not e.get("dishes")]
    no_model = [e for e in entries if e["recipe_id"] not in labels]
    lines.append(f"{len(entries)} recipes, {len(entries) - len(unlabeled)} with a dish type, "
                 f"{len(no_model)} never labeled by the model")
    lines.append("")
    lines.append("Per type (recipes; how many the model gave it to):")
    for name in types:
        found = by_type.get(name, [])
        by_model = sum(1 for e in found if name in labels.get(e["recipe_id"], []))
        shown = ", ".join(e["title"] for e in rng.sample(found, min(sample, len(found))))
        lines.append(f"  {name}: {len(found)} ({by_model} by the model)  e.g. {shown}")

    # A title naming one type the model didn't give at all: one of the two is wrong.
    disagree = [(e, title_dishes(e, types), labels[e["recipe_id"]]) for e in entries
                if e["recipe_id"] in labels and title_dishes(e, types)
                and not set(title_dishes(e, types)) & set(labels[e["recipe_id"]])]
    lines.append("")
    lines.append(f"Title names a type the model didn't give ({len(disagree)}):")
    for e, by_title, by_model in disagree:
        lines.append(f"  {e['title']} ({e['book']}): title {by_title}, model {by_model or 'none'}")

    lines.append("")
    lines.append(f"No type at all ({len(unlabeled)}):")
    for e in unlabeled:
        lines.append(f"  {e['title']} ({e['book']})")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--type", help="list every recipe of this dish type")
    parser.add_argument("--sample", type=int, default=5, help="titles shown per type")
    parser.add_argument("--key", action="store_true", help="score the labels against the hand-checked key")
    parser.add_argument("--holdout", action="store_true", help="score the labels against the hold-out set")
    args = parser.parse_args(argv)
    entries = load_index()
    if entries is None:
        print("No recipe index yet: run ingest.py or tools/build_recipe_index.py first.")
        return 1
    if args.key or args.holdout:
        labels_of = {(e["title"], e["book"]): e.get("dishes") for e in entries}
        key = load_key(KEY_PATH if args.key else HOLDOUT_PATH)
        print("\n".join(score_key(labels_of, key, load_overrides())))
        return 0
    print("\n".join(report(entries, model_labels(), load_types(), args.sample, args.type)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
