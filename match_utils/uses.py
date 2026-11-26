"""
Whether a recipe uses an ingredient, and where: for filtering a list
("do any of these use half and half", "a pumpkin pie without half and
half") from the recipe index, with no model call.

An ingredient counts when an option of one of the recipe's lines is it,
a part of it (eggs -> egg yolk, lemons -> lemon juice), or a kind of it:
the name has its words, in order ("chocolate" -> "bittersweet chocolate",
"chocolate chips"; "cream" -> "heavy cream"). This is looser than
matching what someone has (matching.is_variety), on purpose: a filter
leans towards showing more. What's never a kind of it is in
word_lists/universal/ingredient_varieties.json ("chocolate" is never
"white chocolate", "cream" never "sour cream").

Linked sub-recipes are followed ("uses butter, in the crust"). Optional
lines count, marked optional. A line with other choices ("heavy cream or
half-and-half") counts too, with those choices kept, so "without half and
half" can still show it: it can be made with heavy cream instead. A
title naming it counts even when no line does: "Chocolate Whipped Cream"
uses cocoa powder, but asking for a whipped cream with chocolate means it.
A word naming a group ("nuts", "dairy", word_lists/universal/
ingredient_groups.json) counts any of its members: "without nuts" leaves
out the walnut recipes too.
"""

from dataclasses import dataclass, field

from common.word_list_loader import load_universal
from match_utils.matching import MAX_SUB_RECIPE_DEPTH, load_not_varieties, load_parts
from query_utils.title_lookup import title_tokens, word_forms


@dataclass
class Use:
    """How a recipe uses the ingredient asked about. option is the
    ingredient as the recipe names it, where the sub-recipe it's in ("" for
    the recipe itself), instead the line's other choices. in_title: only
    the title names it, no line does."""
    option: str
    where: str = ""
    optional: bool = False
    instead: list = field(default_factory=list)
    in_title: bool = False

    @property
    def needed(self):
        """It can't be made without it."""
        return not self.optional and not self.instead

    def note(self, name):
        """A short note for a list: "bittersweet chocolate, in the crust,
        optional". Empty when it's just the ingredient asked about."""
        if self.in_title:
            return ""
        bits = [] if _same(self.option, name) else [self.option]
        if self.where:
            bits.append(f"in {self.where}")
        if self.optional:
            bits.append("optional")
        if self.instead:
            bits.append("or " + " or ".join(self.instead))
        return ", ".join(bits)


def load_groups():
    return load_universal("ingredient_groups.json", {}).get("groups", {})


def _same(a, b):
    wa, wb = title_tokens(a), title_tokens(b)
    return bool(wa) and len(wa) == len(wb) and all(word_forms(x) & word_forms(y) for x, y in zip(wa, wb))


def _contains(option_words, name_words):
    """name's words appear in option, in order, next to each other."""
    n = len(name_words)
    return n > 0 and any(all(word_forms(a) & word_forms(b) for a, b in zip(option_words[i:i + n], name_words))
                         for i in range(len(option_words) - n + 1))


class Uses:
    """Checks recipes from the index for one ingredient at a time. index
    (all entries) is needed to follow sub-recipe links."""

    def __init__(self, index, parts=None, not_varieties=None, groups=None):
        self.by_id = {e["recipe_id"]: e for e in index}
        self.parts = load_parts() if parts is None else parts
        self.not_varieties = load_not_varieties() if not_varieties is None else not_varieties
        self.groups = load_groups() if groups is None else groups
        self._seen = {}

    def matches(self, option, name):
        """Whether a recipe's option is the ingredient name, a part of it,
        or a kind of it, or a member of the group it names."""
        if any(self.matches(option, member) for member in self.groups.get(name, []) if member != name):
            return True
        if option == name or option in self.parts.get(name, []):
            return True
        option_words = title_tokens(option)
        if any(_contains(option_words, title_tokens(other)) for other in self.not_varieties.get(name, [])):
            return False
        return _contains(option_words, title_tokens(name)) or any(
            _contains(option_words, title_tokens(part)) for part in self.parts.get(name, []))

    def matches_title(self, entry, name):
        if self.groups.get(name):
            return any(self.matches_title(entry, member) for member in self.groups[name] if member != name)
        title_words = title_tokens(entry.get("title", ""))
        return _contains(title_words, title_tokens(name)) and not any(
            _contains(title_words, title_tokens(other)) for other in self.not_varieties.get(name, []))

    def find(self, entry, name, stack=()):
        """How entry uses name (a Use), or None if it doesn't. When several
        lines have it, one it can't do without wins, then one in the recipe
        itself over one in a sub-recipe."""
        key = (entry["recipe_id"], name)
        if key in self._seen:
            return self._seen[key]
        stack = stack + (entry["recipe_id"],)
        found = []
        for optional, requirements in ((False, entry.get("ingredients", [])), (True, entry.get("optional", []))):
            for requirement in requirements:
                use = self._line(requirement, name, optional, stack)
                if use:
                    found.append(use)
        best = min(found, key=lambda u: (not u.needed, bool(u.where))) if found else None
        if best is None and len(stack) == 1 and self.matches_title(entry, name):
            best = Use(name, in_title=True)
        if len(stack) == 1:
            self._seen[key] = best
        return best

    def _line(self, requirement, name, optional, stack):
        choices = requirement.get("options") or [requirement["name"]]
        hits = [o for o in choices if self.matches(o, name)]
        if hits:
            return Use(hits[0], "", optional, [o for o in choices if o not in hits])
        if not requirement.get("recipes") or len(stack) >= MAX_SUB_RECIPE_DEPTH:
            return None
        subs = [(self.by_id[r], self.find(self.by_id[r], name, stack))
                for r in requirement["recipes"] if r in self.by_id and r not in stack]
        with_it = [(e, u) for e, u in subs if u]
        if not with_it:
            return None
        sub_entry, use = min(with_it, key=lambda eu: not eu[1].needed)
        instead = list(use.instead)
        # Another of the linked recipes doesn't need it, or the line can
        # be bought ("mayonnaise" the book also makes): it can be swapped.
        if len(with_it) < len(subs) or (requirement.get("how") == "plain"):
            instead.append(f"another {requirement['name']}" if requirement.get("how") != "plain"
                           else f"store-bought {requirement['name']}")
        return Use(use.option, use.where or sub_entry["title"], optional or use.optional, instead)
