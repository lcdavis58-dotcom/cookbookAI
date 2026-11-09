"""
Linking ingredient lines to the recipes in the same book that make
them, once, when the recipe index is built (build_index), so matching
can check a sub-recipe without re-reading anything.

Two kinds of link:
    references  lines that say they're another recipe ("recipe Graham
                Crust", "Pastry Cream (this page)", "Mile-High Batch of
                Meringue Topping"). Linked by title lookup in the same
                book (query_utils/title_lookup.py), or, when the line
                names a general kind instead ("9-inch pie crust (see
                Recommended Crusts)"), to every recipe of that kind in
                the book. A linked reference becomes a requirement of its
                own; one that can't be linked stays in "sub_recipes", as
                before, shown but not counted.
    buy or make plain ingredients whose name is a recipe in the book
                ("mayonnaise", "Roasted Garlic", "puff pastry"): the
                requirement keeps its options, so having the ingredient
                still covers it, and gains the recipes that make it.

Kinds (word_lists/universal/sub_recipe_kinds.json): a recipe is of a
kind when its title is, or ends with, one of the kind's names ("All-
Buttah Pie Dough" is a pie dough). Matching lets having any name of the
kind ("pie crust") cover it, with a note.

What the link pass adds to an index entry:
    kinds           the kinds this recipe is
    requirements in ingredients / optional gain
        "recipes"   recipe_ids that make it
        "how"       "title" (named it), "kind" (any recipe of the kind)
                    or "plain" (a plain ingredient the book also makes)
        "kinds"     the kinds that cover it
"""

import re
from collections import defaultdict

from common.word_list_loader import load_universal
from match_utils.ingredient_names import normalize, options
from query_utils.title_lookup import SOFT_WORDS, candidates_from_index, lookup, title_tokens, word_forms

# Words in an alternative that say where it comes from, not what it is:
# "thawed frozen store-bought puff pastry" is puff pastry.
_SOURCE_WORDS_RE = re.compile(r"\b(?:store-?bought|thawed|homemade|prepared|purchased)\s+", re.IGNORECASE)


# Wording that makes a line a reference to a recipe, not an ingredient
# with a page note ("all-purpose flour (see this page)").
_REFERENCE_RE = re.compile(r"^\s*(?:[\d½¼¾⅓⅔]+\s+)?(?:double |triple |half |full |regular |mile-high )?"
                           r"(?:recipes?|batch(?:es)?|portions?)\b|\brecipes? follows?\b", re.IGNORECASE)
# A plain ingredient line is short; longer ones are stray step text.
_PLAIN_MAX_WORDS = 8


def plain_ingredient(line):
    """The ingredient a line flagged as a reference really is, when it
    can't be linked and doesn't say it's a recipe: "all-purpose flour
    (see this page)" -> "all-purpose flour", "crème fraîche (page 113)
    or heavy cream" -> "crème fraîche or heavy cream". None for a real
    reference or a line of step text."""
    if _REFERENCE_RE.search(line) or re.search(r"[.;:](?:\s|$)", re.sub(r"\([^)]*\)", "", line)):
        return None
    name = normalize(line)[0]
    if not name or len(name.split()) > _PLAIN_MAX_WORDS:
        return None
    return name


def is_step_text(line):
    """A line flagged as a reference that's really part of a step or a
    note ("6-inch round cake pan for this recipe. You can substitute..."):
    a sentence, or too long to be a name. Never counted as missing."""
    bare = re.sub(r"\([^)]*\)", "", line)
    return bool(re.search(r"[.;:!?](?:\s|$)", bare)) or len(short_name(line).split()) > _REFERENCE_MAX_WORDS


# The longest a reference's name runs ("Sweet Corn Cereal Milk Ice Cream
# Filling" is 7).
_REFERENCE_MAX_WORDS = 8


def short_name(line):
    """A sub-recipe line without its amount, pan size and prep notes:
    "9-inch / 23-cm pie crust (see Recommended Crusts), parbaked and
    cooled" -> "pie crust", "recipe Brioche Dough" -> "Brioche Dough",
    "Mile-High Batch of Meringue Topping" -> "Meringue Topping"."""
    name = re.sub(r"\s*\([^)]*\)", "", line.split(",", 1)[0]).strip()
    name = re.sub(r"^(?:one\s+)?[\d½]+-inch(?:\s*/\s*[\d.]+[- ]?cm)?\s+", "", name, flags=re.IGNORECASE)
    return re.sub(r"^(?:[\d½¼¾⅓⅔]+\s+)?(?:double |triple )?(?:recipes?|(?:half |full |regular |mile-high |double )?"
                  r"batch(?:es)? of|(?:round |rectangular |square )?portions?(?: of)?)\s+", "",
                  name, flags=re.IGNORECASE)


def load_kinds():
    return load_universal("sub_recipe_kinds.json", {}).get("kinds", {})


def _key(words):
    """Words as a comparable set: plurals folded, soft words left out."""
    return frozenset(min(word_forms(w)) for w in words if w not in SOFT_WORDS)


def _ends_with(words, phrase):
    return len(phrase) <= len(words) and all(
        word_forms(a) & word_forms(b) for a, b in zip(words[-len(phrase):], phrase))


def kinds_of(text, kinds):
    """The kinds a title or ingredient name is: it is, or ends with, one
    of the kind's names."""
    words = title_tokens(text)
    return sorted(kind for kind, names in kinds.items()
                  if any(_ends_with(words, title_tokens(n)) for n in names))


def _pieces(line):
    """The alternatives of a reference line, as names to look up:
    "recipe Rough Puff Pastry (this page) or 1 sheet thawed frozen
    store-bought puff pastry" -> ["rough puff pastry", "frozen puff
    pastry"]."""
    out = []
    for option in options(normalize(line)[0]):
        name = _SOURCE_WORDS_RE.sub("", short_name(option)).strip()
        name = re.sub(r"^(?:\d+\s+)?(?:sheets?|packages?|boxes?)\s+(?:of\s+)?", "", name)
        if name and name not in out:
            out.append(name)
    return out


class BookLinker:
    """Links for the recipes of one book."""

    def __init__(self, entries, kinds):
        self.kinds = kinds
        self.candidates = candidates_from_index(entries)
        self.by_kind = defaultdict(list)
        self.by_words = defaultdict(list)
        for e in entries:
            e["kinds"] = kinds_of(e.get("match_title") or e["title"], kinds)
            for kind in e["kinds"]:
                self.by_kind[kind].append(e["recipe_id"])
        # Whole titles, "with ..." tail included: a plain "carrot" is not
        # "Carrots with Dates and Raisins".
        for c in self.candidates:
            for core, extra in c.variants:
                self.by_words[_key(core + extra)].append(c.key)

    def _kind_link(self, name, recipe_id):
        found = kinds_of(name, self.kinds)
        ids = [i for kind in found for i in self.by_kind[kind] if i != recipe_id]
        return list(dict.fromkeys(ids)), found

    def reference(self, line, recipe_id):
        """The requirement a reference line becomes, or None if it can't
        be linked."""
        others = [c for c in self.candidates if c.key != recipe_id]
        pieces = _pieces(line)
        ids, how, kinds = [], None, set()
        for piece in pieces:
            result = lookup(piece, others, loose=False)
            if result.kind == "match":
                ids += [c.key for c in result.matches]
            elif result.kind == "partial" and not kinds_of(piece, self.kinds):
                # (A general kind, "9-inch pie crust", is any recipe of
                # the kind, below, not the one title that contains it.)
                # A shortened title: "All-Purpose Drop Biscuit Dough" is
                # "All-Purpose Drop Biscuit or Shortcake Dough". Only when
                # one title holds every word of the reference and the
                # reference leaves out at most one of the title's main
                # words ("crème fraîche" isn't "Apple Granita with Crème
                # Fraîche Tapioca").
                words = _key(title_tokens(piece))
                holding = [c for c in others
                           if any(words <= _key(core + extra) and len(_key(core) - words) <= 1
                                  for core, extra in c.variants)]
                if words and len(holding) == 1:
                    ids.append(holding[0].key)
        if not ids:
            # A title with a comma of its own ("Fresh Cheese, the Easy
            # Way") is cut short by short_name; the whole line names it.
            whole = lookup(re.sub(r"\([^)]*\)", " ", line), others, loose=False)
            if whole.kind == "match" and len(whole.matches) == 1:
                ids.append(whole.matches[0].key)
        if ids:
            how = "title"
        if not ids:
            for piece in pieces:
                kind_ids, found = self._kind_link(piece, recipe_id)
                if kind_ids:
                    ids += kind_ids
                    kinds.update(found)
                    how = "kind"
        if not ids:
            return None
        ids = list(dict.fromkeys(ids))
        for piece in pieces:
            kinds.update(kinds_of(piece, self.kinds))
        return {"name": short_name(line), "options": pieces, "recipes": ids,
                "how": how, "kinds": sorted(kinds)}

    def plain(self, requirement, recipe_id):
        """recipe_ids that make a plain ingredient, and how, or ([], None).
        Strict: the name must be a title's very words ("mayonnaise" is
        "Mayonnaise"), or a kind's name ("puff pastry")."""
        ids = []
        for option in requirement["options"]:
            ids += [i for i in self.by_words.get(_key(title_tokens(option)), []) if i != recipe_id]
        if ids:
            return list(dict.fromkeys(ids)), "plain", []
        kind_ids, found = [], []
        for option in requirement["options"]:
            more, kinds = self._kind_link(option, recipe_id)
            kind_ids += more
            found += kinds
        return list(dict.fromkeys(kind_ids)), ("kind" if kind_ids else None), sorted(set(found))


def link_sub_recipes(entries, kinds=None):
    """Add the links described in the module docstring to every entry,
    in place. Entries are linked only within their own book."""
    kinds = load_kinds() if kinds is None else kinds
    by_book = defaultdict(list)
    for e in entries:
        by_book[e["book"]].append(e)
    for book_entries in by_book.values():
        linker = BookLinker(book_entries, kinds)
        for e in book_entries:
            unlinked = []
            e["unread_lines"] = []
            optional_lines = set(e.get("optional_sub_recipes", []))
            for line in e["sub_recipes"]:
                target = e["optional"] if line in optional_lines else e["ingredients"]
                requirement = linker.reference(line, e["recipe_id"])
                if requirement is None:
                    name = plain_ingredient(line)
                    if name is not None:
                        requirement = {"name": name, "options": options(name)}
                    elif is_step_text(line):
                        e["unread_lines"].append(line)
                        continue
                    else:
                        # A real reference that couldn't be linked still
                        # has to be made or had: it counts as missing
                        # unless the person lists it.
                        unlinked.append(line)
                        requirement = {"name": short_name(line), "options": _pieces(line), "how": "unlinked"}
                if all(r.get("name") != requirement["name"] for r in target):
                    target.append(requirement)
            e["sub_recipes"] = unlinked
            for requirement in e["ingredients"] + e["optional"]:
                if "recipes" in requirement or requirement.get("how") == "unlinked":
                    continue
                ids, how, found = linker.plain(requirement, e["recipe_id"])
                if ids:
                    requirement.update({"recipes": ids, "how": how, "kinds": found})
    return entries
