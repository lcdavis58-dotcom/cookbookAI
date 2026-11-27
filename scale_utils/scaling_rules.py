"""
Loads the two ingredient exception lists (non_scalable.json,
storage_sensitive.json) and checks a parsed ingredient name against them.

These are read fresh each time check_ingredient_flags() is called via
load_ingredient_rules(), rather than cached at import time, so you can edit
the JSON files and see the effect on the next run without restarting
anything, or without needing to re-ingest, these aren't part of the
cookbook data at all.
"""

import json
import os
import re

from common.config import PROJECT_ROOT

NON_SCALABLE_PATH = os.path.join(PROJECT_ROOT, "ingredient_rules", "non_scalable.json")
STORAGE_SENSITIVE_PATH = os.path.join(PROJECT_ROOT, "ingredient_rules", "storage_sensitive.json")


def load_ingredient_rules(path):
    """Load a rules file, returning [] if it's missing or empty rather than
    crashing, a missing exception list shouldn't break recipe scaling."""
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("ingredients", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: couldn't load {path} ({e}), continuing without these rules.")
        return []


def check_ingredient_flags(ingredient_name):
    """Check one ingredient name against both exception lists.

    Returns a list of (flag_type, note) tuples, flag_type is either
    "non_scalable" or "storage_sensitive". An ingredient can match both
    lists, or neither, or (in theory) multiple entries within one list,
    all matches are returned rather than stopping at the first.
    """
    non_scalable_rules = load_ingredient_rules(NON_SCALABLE_PATH)
    storage_rules = load_ingredient_rules(STORAGE_SENSITIVE_PATH)

    # Only the ingredient itself, not its prep notes after the first comma:
    # "pie crust (see Recommended Crusts), brushed with egg wash" is a
    # crust, not an egg.
    name_lower = ingredient_name.lower().split(",", 1)[0]
    flags = []

    for rule in non_scalable_rules:
        if _keyword_matches(rule["keyword"], name_lower):
            flags.append(("non_scalable", rule["note"]))

    for rule in storage_rules:
        if _keyword_matches(rule["keyword"], name_lower):
            flags.append(("storage_sensitive", rule["note"]))

    return flags


WHOLE_ITEMS_PATH = os.path.join(PROJECT_ROOT, "ingredient_rules", "whole_items.json")
_COUNT_EXCEPT = ("cup", "tablespoon", "teaspoon", "tbsp", "tsp", "oz", "ounce", "lb", "pound", "gallon", "quart",
                 "pint")


def whole_item(ing):
    """For a counted ingredient that only comes whole
    (ingredient_rules/whole_items.json): ("not_scaled", note) for a crust,
    ("whole", None) for a can, ("exact", tip) for an egg (always noted
    when rounded, with how to measure part of one),
    ("rough", None) for a pinch; None for anything else, including
    anything measured by volume. A line with a weight too ("100 g / 2
    large eggs") rounds only its count; a crust with a weight is scaled."""
    unit = (ing.get("imperial_unit") or "").lower()
    if not ing.get("imperial_amount") or any(u in unit for u in _COUNT_EXCEPT):
        return None
    try:
        with open(WHOLE_ITEMS_PATH) as f:
            rules = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Warning: couldn't load {WHOLE_ITEMS_PATH} ({e}), continuing without these rules.")
        return None
    text = f"{unit} {ing['name'].lower().split(',', 1)[0]}"
    not_scaled = rules.get("not_scaled", {})
    if not ing.get("metric_amount") and any(_keyword_matches(k, text) for k in not_scaled.get("keywords", [])):
        return "not_scaled", not_scaled.get("note", "Not scaled.")
    if any(_keyword_matches(k, text) for k in rules.get("whole_units", [])):
        return "whole", None
    if any(_keyword_matches(k, text) for k in rules.get("always_noted_units", [])):
        return "exact", rules.get("always_noted_tip")
    if any(_keyword_matches(k, text) for k in rules.get("rough_units", [])):
        return "rough", None
    return None


def _keyword_matches(keyword, name):
    """Whole-word match, plural allowed: "egg" matches "large eggs" and
    "egg whites" but not "eggplant"."""
    return re.search(rf"\b{re.escape(keyword.lower())}(?:s|es)?\b", name) is not None


if __name__ == "__main__":
    # Quick manual check, run from app/:
    #   python3 -m scale_utils.scaling_rules "large eggs"
    import sys
    if len(sys.argv) < 2:
        print('Usage: python3 -m scale_utils.scaling_rules "ingredient name"')
        sys.exit(1)

    name = " ".join(sys.argv[1:])
    flags = check_ingredient_flags(name)
    if not flags:
        print(f'"{name}": no flags')
    else:
        for flag_type, note in flags:
            print(f'"{name}": [{flag_type}] {note}')
