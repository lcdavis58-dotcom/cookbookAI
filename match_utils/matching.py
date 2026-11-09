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

A requirement linked to recipes in the same book (match_utils/
sub_recipes.py: "recipe Graham Crust", "9-inch pie crust", or a plain
"mayonnaise" the book also makes) is also on hand when:
  - the person listed a general form of it: any name of its kind ("pie
    crust" for All-Buttah Pie Dough, word_lists/universal/
    sub_recipe_kinds.json), reported as an assumption, like a variety
  - one of the linked recipes can be made from what they have, checked
    the same way, sub-recipes of its own included. The result lists it
    under "makes", and the ingredients it uses count as used.
When none can be made, a reference to the book's own recipe ("Graham
Crust") counts the closest one's missing ingredients ("graham crackers,
for Graham Crust"); something that can also be bought ("pie crust",
"mayonnaise") counts as one missing thing by its own name, and so does
a reference that couldn't be linked ("Brioche Dough").

A result also says which sub-recipes it makes from pantry staples alone
("from_scratch": match.py lists those recipes in a section of their
own) and which general forms stand in for something more specific
("stand_ins": "your pie crust for pie dough", shown with the recipe).

Optional ingredients never stop a recipe from being makeable. Recipes
that use none of the listed ingredients aren't returned at all, results
center on what the person said they have.
"""

import re

from common.word_list_loader import load_universal
from match_utils.ingredient_names import normalize, pieces
from match_utils.sub_recipes import load_kinds
from query_utils.title_lookup import title_tokens, word_forms

# How deep sub-recipes are followed (a cake's filling's sauce is 3).
MAX_SUB_RECIPE_DEPTH = 4


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
        # One ingredient, however it's typed, and how the books spell it.
        item = re.sub(r"\bhalf\s+and\s+half\b", "half-and-half", item, flags=re.I)
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


def _same_words(a, b):
    wa, wb = title_tokens(a), title_tokens(b)
    return bool(wa) and len(wa) == len(wb) and all(word_forms(x) & word_forms(y) for x, y in zip(wa, wb))


def _add_new(target, items):
    for item in items:
        if item not in target:
            target.append(item)


class Matcher:
    """Holds what someone has, expanded with parts and staples, so many
    recipes can be checked against it. index (the recipe index entries)
    is needed to follow sub-recipe links; without it, a linked
    requirement is checked by its own names only."""

    def __init__(self, have, staples=None, parts=None, not_varieties=None, index=None, kinds=None):
        parts = load_parts() if parts is None else parts
        self.not_varieties = load_not_varieties() if not_varieties is None else not_varieties
        self.have = list(have)
        self.covered = _with_parts(self.have, parts)
        self.staples = _with_parts(load_staples() if staples is None else staples, parts)
        self.kinds = load_kinds() if kinds is None else kinds
        self.by_id = {e["recipe_id"]: e for e in index or []}
        self._made = {}

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

    def check_kind(self, requirement):
        """("have", listed item, note) when something listed is a name of
        one of the requirement's kinds ("pie crust" for a pie dough)."""
        for kind in requirement.get("kinds", []):
            for item in self.have:
                if any(_same_words(item, name) for name in self.kinds.get(kind, [])):
                    note = (None if _same_words(item, requirement["name"])
                            else f"assuming your {item} works for {requirement['name']}")
                    return "have", item, note
        return None

    def _evaluate(self, entry, stack=()):
        """What making one recipe takes from what's on hand: {"uses",
        "assumptions", "missing", "staples_used", "makes"}, with
        sub-recipes followed. A recipe already on the way down (stack)
        isn't used again, so a sauce that calls for another version of
        itself doesn't loop. Kept per recipe, since many recipes share
        the same doughs and creams."""
        rid = entry["recipe_id"]
        if rid in self._made:
            return self._made[rid]
        out = {"uses": [], "assumptions": [], "missing": [], "staples_used": [], "makes": [],
               "from_scratch": [], "stand_ins": []}
        for requirement in entry["ingredients"]:
            self._check_requirement(requirement, out, stack + (rid,))
        self._made[rid] = out
        return out

    def _check_requirement(self, requirement, out, stack):
        found = None
        # Prefer an option the person listed over a staple, so a listed
        # staple ("eggs") still counts as using their eggs.
        for option in requirement["options"]:
            result = self.check_option(option)
            if result and (found is None or (result[0] == "have" and found[0] == "staple")):
                found = result
        if found is None or found[0] == "staple":
            kind = self.check_kind(requirement)
            if kind:
                # A general form standing in for something more specific
                # belongs with the recipe it's for, not in the list of
                # assumptions at the top: "your pie crust for the pie
                # crust" reads oddly out of context.
                found = ("have", kind[1], None)
                if kind[2]:
                    _add_new(out["stand_ins"], [f"your {kind[1]} for {requirement['name']}"])
        if found is not None:
            if found[0] == "have":
                _add_new(out["uses"], [found[1]])
                if found[2]:
                    _add_new(out["assumptions"], [found[2]])
            else:
                out["staples_used"].append(found[1])
            return

        best = self._closest_sub_recipe(requirement, stack)
        if best is not None:
            sub_entry, sub = best
            if not sub["missing"]:
                _add_new(out["uses"], sub["uses"])
                _add_new(out["assumptions"], sub["assumptions"])
                _add_new(out["stand_ins"], sub["stand_ins"])
                out["staples_used"] += sub["staples_used"]
                _add_new(out["makes"], sub["makes"] + [sub_entry["title"]])
                # Made from pantry staples alone: possible, but real work
                # the person didn't mention (a pie dough from scratch).
                _add_new(out["from_scratch"], sub["from_scratch"] + ([] if sub["uses"] else [sub_entry["title"]]))
                return
            if requirement.get("how") == "title":
                # The book's own recipe, not something to buy: what it
                # lacks is what this recipe lacks.
                _add_new(out["uses"], sub["uses"])
                _add_new(out["missing"], [m if ", for " in m else f"{m}, for {sub_entry['title']}"
                                          for m in sub["missing"]])
                return
        out["missing"].append(requirement["name"])

    def _closest_sub_recipe(self, requirement, stack):
        """(entry, evaluation) of the linked recipe closest to makeable:
        fewest missing, then most of the listed ingredients used, then
        fewest assumptions. None without links, or too deep."""
        if not requirement.get("recipes") or len(stack) >= MAX_SUB_RECIPE_DEPTH:
            return None
        options = []
        for rid in requirement["recipes"]:
            entry = self.by_id.get(rid)
            if entry is None or rid in stack:
                continue
            sub = self._evaluate(entry, stack)
            options.append(((len(sub["missing"]), -len(sub["uses"]), len(sub["assumptions"]), entry["title"]),
                            entry, sub))
        if not options:
            return None
        _, entry, sub = min(options, key=lambda o: o[0])
        return entry, sub

    def check_recipe(self, entry):
        """A match result for one index entry, or None if it uses none of
        the listed ingredients."""
        evaluation = self._evaluate(entry)
        if not evaluation["uses"]:
            return None
        optional_on_hand = [i["name"] for i in entry["optional"]
                            if any(self.check_option(o) for o in i["options"]) or self.check_kind(i)]
        return {
            "entry": entry,
            "uses": list(evaluation["uses"]),
            "assumptions": list(evaluation["assumptions"]),
            "missing": list(evaluation["missing"]),
            "staples_used": list(evaluation["staples_used"]),
            "makes": list(evaluation["makes"]),
            "from_scratch": list(evaluation["from_scratch"]),
            "stand_ins": list(evaluation["stand_ins"]),
            "optional_on_hand": optional_on_hand,
        }


def find_matches(index, have, max_missing=1):
    """Every recipe that uses at least one listed ingredient and is missing
    at most max_missing required ones, best first: fewest missing, then
    most of the listed ingredients used, then fewest assumptions."""
    matcher = Matcher(have, index=index)
    results = [r for r in (matcher.check_recipe(e) for e in index)
               if r and len(r["missing"]) <= max_missing]
    return sorted(results, key=lambda r: (len(r["missing"]), -len(r["uses"]),
                                          len(r["assumptions"]), r["entry"]["title"].lower()))
