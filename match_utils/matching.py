"""
Matching what someone has against the recipe index: which recipes they
can make now, and which are missing just one thing.

A recipe ingredient (one entry in the index, possibly an "X or Y" choice)
counts as on hand when any of its options is:
  - something the person listed, exactly
  - a part of something they listed ("lemon juice" when they have
    lemons, word_lists/universal/ingredient_parts.json). Never the other
    way round: leftover yolks are not eggs.
  - a variety of a general name they listed ("unsalted butter" when they
    said "butter"), reported as an assumption, since the variety matters
    in baking and only the person knows which one they have
  - a pantry staple, or a part of one (word_lists/universal/
    pantry_staples.json)

Optional ingredients never stop a recipe from being makeable. Recipes
that use none of the listed ingredients aren't returned at all, results
center on what the person said they have.
"""

import re

from common.word_list_loader import load_universal
from match_utils.ingredient_names import normalize, pieces


def load_staples():
    return set(load_universal("pantry_staples.json", {}).get("staples", []))


def load_parts():
    return load_universal("ingredient_parts.json", {}).get("parts", {})


def load_not_varieties():
    return load_universal("ingredient_varieties.json", {}).get("not_varieties", {})


def is_variety(option, general, not_varieties):
    """Whether option is a variety of the general name someone listed:
    "unsalted butter" of "butter", but not "peanut butter" (word_lists/
    universal/ingredient_varieties.json)."""
    return (option.endswith(" " + general)
            and not any(option == other or option.endswith(" " + other)
                        for other in not_varieties.get(general, [])))


def parse_have(text):
    """What someone typed ("pecans, cream cheese and 2 lemons") -> the
    normalized names, in the order given."""
    have = []
    for item in re.split(r"[,;\n]", text):
        item = re.sub(r"^\s*(?:and|&)\s+|^\s*[\d½¼¾⅓⅔]+\s+", "", item.strip())
        if not item:
            continue
        name = normalize(item)[0]
        for piece in pieces(name, unmeasured=True):
            if piece and piece not in have:
                have.append(piece)
    return have


def _with_parts(names, parts):
    """names plus every part they cover, as {name: the whole it came from}."""
    covered = {name: name for name in names}
    for name in names:
        for part in parts.get(name, []):
            covered.setdefault(part, name)
    return covered


class Matcher:
    """Holds what someone has, expanded with parts and staples, so many
    recipes can be checked against it."""

    def __init__(self, have, staples=None, parts=None, not_varieties=None):
        parts = load_parts() if parts is None else parts
        self.not_varieties = load_not_varieties() if not_varieties is None else not_varieties
        self.have = list(have)
        self.covered = _with_parts(self.have, parts)
        self.staples = _with_parts(load_staples() if staples is None else staples, parts)

    def check_option(self, option):
        """How one option is on hand: ("have", listed item, assumption or
        None), ("staple", name, None), or None if it isn't."""
        if option in self.covered:
            return "have", self.covered[option], None
        # A general name covers its varieties: "butter" -> "unsalted
        # butter", "milk" -> "whole milk".
        # No note when the variety is a staple anyway: it's on hand either way.
        for item in self.have:
            if is_variety(option, item, self.not_varieties):
                note = None if option in self.staples else f"assuming your {item} is {option}"
                return "have", item, note
        if option in self.staples:
            return "staple", option, None
        return None

    def check_recipe(self, entry):
        """A match result for one index entry, or None if it uses none of
        the listed ingredients."""
        uses, assumptions, missing, staples_used = [], [], [], []
        for ingredient in entry["ingredients"]:
            found = None
            # Prefer an option the person listed over a staple, so a
            # listed staple ("eggs") still counts as using their eggs.
            for option in ingredient["options"]:
                result = self.check_option(option)
                if result and (found is None or (result[0] == "have" and found[0] == "staple")):
                    found = result
            if found is None:
                missing.append(ingredient["name"])
            elif found[0] == "have":
                if found[1] not in uses:
                    uses.append(found[1])
                if found[2]:
                    assumptions.append(found[2])
            else:
                staples_used.append(found[1])
        if not uses:
            return None
        optional_on_hand = [i["name"] for i in entry["optional"]
                            if any(self.check_option(o) for o in i["options"])]
        return {
            "entry": entry,
            "uses": uses,
            "assumptions": assumptions,
            "missing": missing,
            "staples_used": staples_used,
            "optional_on_hand": optional_on_hand,
        }


def find_matches(index, have, max_missing=1):
    """Every recipe that uses at least one listed ingredient and is missing
    at most max_missing required ones, best first: fewest missing, then
    most of the listed ingredients used, then fewest assumptions."""
    matcher = Matcher(have)
    results = [r for r in (matcher.check_recipe(e) for e in index)
               if r and len(r["missing"]) <= max_missing]
    return sorted(results, key=lambda r: (len(r["missing"]), -len(r["uses"]),
                                          len(r["assumptions"]), r["entry"]["title"].lower()))
