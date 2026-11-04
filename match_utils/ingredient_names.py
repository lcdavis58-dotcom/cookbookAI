"""
Turning a parsed ingredient name into the name matching works with.

Normalization is deliberately light: it only removes what doesn't change
WHICH ingredient it is (amounts, parentheticals, prep notes after a
comma, size/state/unit words like "large", "melted" or "ounces",
plurals). Varieties stay distinct, salted butter is not unsalted butter,
light brown sugar is not dark brown sugar. The rules live in
word_lists/universal/ingredient_normalization.json.
"""

import re

from common.word_list_loader import load_universal

RULES = load_universal("ingredient_normalization.json", {})
LEADING_WORDS = set(RULES.get("leading_words", []))
LEADING_PHRASES = [re.compile(p) for p in RULES.get("leading_phrases", [])]
EQUIVALENTS = RULES.get("equivalents", {})
IGNORE = set(RULES.get("ignore", []))
PLURAL_EXCEPTIONS = RULES.get("plural_exceptions", {})
TRAILING_PHRASES = [re.compile(p) for p in RULES.get("trailing_phrases", [])]
COMMA_DESCRIPTORS = set(RULES.get("comma_descriptors", []))

# A trailing "for the pan" / "for serving" with no comma before it, e.g.
# "Neutral oil for the pan". Marks the ingredient as not part of the
# recipe proper.
_FOR_USE_RE = re.compile(
    r"\s+for\s+(?:the\s+\w+|serving|sprinkling|dusting|brushing|greasing|garnish|topping|frying)\b.*$")
_PAREN_RE = re.compile(r"\([^()]*\)?")
# A pointer to another recipe in the book: "1 recipe Brioche Dough",
# "Flaky All-Butter Pie Dough (this page)", "One 9-inch pie crust (see
# Recommended Crusts)", "Pie dough for a double crust (see below)",
# "Full Batch of Classic Whipped Cream". Not bread with its crust cut
# off ("1 loaf brioche, crusts removed").
_SUB_RECIPE_RE = re.compile(r"\bbatch\b|\bpage\s+\d+|\brecipes?\b|\bthis page\b"
                            r"|\bsee below\b|\brecipe follows\b|\bcrusts?\b(?!\s+(?:removed|trimmed))")
_OPTIONAL_RE = re.compile(r"\boptional\b|\bfor (?:serving|sprinkling|dusting|garnish|topping)\b"
                          r"|\bfor the (?:pan|pans|baking sheet|work surface)\b")

# A list at the start of a name that ends in "or"/"and": "gruyère,
# manchego, or parmesan", "honey, olive oil, and a lemon wedge".
_COMMA_LIST_RE = re.compile(r"^([^,]+(?:,\s*[^,]+?)+),\s*(or|and/or|and)\s+([^,]+)")
# A prep note among those commas ("vanilla bean, halved lengthwise,
# seeds scraped out, or 2 teaspoons vanilla extract") means they aren't
# a list of ingredients.
_PREP_WORD_RE = re.compile(r"\b(?:[a-z]+ed|cut|torn|split)\b")
# "Oil for frying, see page 189" points at a technique, not a recipe.
_SEE_PAGE_RE = re.compile(r",?\s*see page\s+\d+")
# "Golden syrup, such as Lyle's, or light corn syrup": a brand aside,
# which would otherwise read as one item of a list.
_SUCH_AS_RE = re.compile(r",?\s+such as\b.*$")
# The bread's unit left in front of its name ("1 loaf brioche bread").
_LOAF_RE = re.compile(r"^(?:[\w-]+\s+)?(?:loaf|loaves)\s+(?:of\s+)?")

# "X or Y", "X and/or Y" inside a normalized name.
_ALTERNATIVE_SPLIT_RE = re.compile(r"\s+(?:and/)?or\s+")
# An amount left in front of an alternative: "lemon juice or 1 g / ¼
# teaspoon citric acid", "black tea or 1 teaspoon instant espresso",
# "whole cherries or 5 cups | 28 ounces frozen cherries".
_AMOUNT_CHARS = r"[\d.¼½¾⅓⅔⅛]+"
_AMOUNT_UNITS = r"(?:g|ml|cups?|tablespoons?|teaspoons?|ounces?|pounds?)\b"
_ALTERNATIVE_AMOUNT_RE = re.compile(
    rf"^{_AMOUNT_CHARS}\s*(?:{_AMOUNT_UNITS})?\s*"
    rf"(?:[/|]\s*{_AMOUNT_CHARS}\s*(?:{_AMOUNT_UNITS})?\s*)?(?=\S)")


def singular(word):
    if word in PLURAL_EXCEPTIONS:
        return PLURAL_EXCEPTIONS[word]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"          # cherries, anchovies
    if word.endswith("oes"):
        return word[:-2]                # tomatoes, potatoes
    if word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]                # peaches, radishes
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]                # eggs, pecans, yolks
    return word


def _join_list(m):
    """A _COMMA_LIST_RE match as one "X or Y or Z" name, unless the items
    after the first are prep notes ("vanilla bean, halved lengthwise,
    ..."): then it's left alone, and the cut at the first comma keeps
    just the ingredient. A prep word in the first item is a list of ways
    to cut one thing ("chopped, torn, or small whole basil leaves"), so
    that still joins."""
    items, joiner = m.group(1), m.group(2)
    first, rest = items.split(",", 1)
    if _PREP_WORD_RE.search(rest) and not _PREP_WORD_RE.search(first):
        return m.group(0)
    return re.sub(r",\s*", f" {joiner} ", items) + f" {joiner} {m.group(3)}"


def normalize(name):
    """Parsed ingredient name -> (normalized name, flags). Flags are any of
    "optional" (garnish, pan grease, explicitly optional), "sub_recipe"
    (a reference to another recipe, not a purchasable ingredient),
    "alternative" (an "X or Y" choice) and "ignored" (on the ignore
    list)."""
    flags = set()
    text = _SEE_PAGE_RE.sub("", name.lower().strip())
    # "butter, at room temperature, plus more for the pan" still needs the
    # butter, only the "plus more" part is pan prep, so look for optional
    # wording before any "plus" clause.
    if _OPTIONAL_RE.search(re.split(r",?\s+plus\b", text, maxsplit=1)[0]):
        flags.add("optional")
    if _SUB_RECIPE_RE.search(text):
        flags.add("sub_recipe")

    text = _SUCH_AS_RE.sub("", _PAREN_RE.sub(" ", text)).strip()
    # "loaf unseeded, unsliced rye bread" is rye bread.
    text = _LOAF_RE.sub("", text)
    # "cold, unsalted butter" is unsalted butter.
    while (m := re.match(r"([\w-]+),\s*", text)) and m.group(1) in COMMA_DESCRIPTORS:
        text = text[m.end():]
    # "gruyère, manchego, or parmesan" is one choice, and "flaky salt,
    # pepper, and lemon" one list, so join those commas before cutting
    # the prep notes off at the first remaining one.
    text = _COMMA_LIST_RE.sub(_join_list, text, count=1)
    text = text.split(",", 1)[0]
    text = _FOR_USE_RE.sub("", text)
    for phrase in TRAILING_PHRASES:
        text = phrase.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" .;:-")

    # Phrases and words alternate until neither removes anything, since a
    # phrase can sit behind a unit word ("ounces fresh or frozen ...").
    # Every change shortens the name, so this always ends.
    words = text.split()
    while True:
        before = words
        joined = " ".join(words)
        for phrase in LEADING_PHRASES:
            stripped = phrase.sub("", joined).strip()
            if stripped:
                joined = stripped
        words = joined.split()
        # Not when the word is one side of a choice ("chopped or torn ...").
        if len(words) > 1 and words[0] in LEADING_WORDS and words[1] not in ("or", "and", "and/or"):
            words = words[1:]
        if words == before:
            break
    if words:
        words[-1] = singular(words[-1])
    text = " ".join(words)
    text = EQUIVALENTS.get(text, text)

    if re.search(r"\bor\b", text):
        flags.add("alternative")
    if text in IGNORE:
        flags.add("ignored")
    return text, flags


_AND_RE = re.compile(r"\s+and\s+")


def pieces(normalized, unmeasured):
    """The separate ingredients a normalized name stands for. A line with
    no amount can name two ingredients ("Kosher salt and freshly ground
    black pepper"), both needed. A measured line is one ingredient, and
    splitting it would break names like "half-and-half"."""
    parts = _AND_RE.split(normalized) if unmeasured else [normalized]
    if len(parts) == 1:
        return parts
    return [p for p in (normalize(part)[0] for part in parts) if p]


def options(normalized):
    """The ingredients a normalized name accepts, as a list: one name, or
    each side of an "X or Y" choice.

    A one-word side before the last can be a variety of what follows
    ("light or dark brown sugar", "white or black chia seed") or a whole
    ingredient of its own ("walnuts or macadamia nuts", "water or
    pineapple juice"), and the text alone can't say which. So it's kept
    both ways: on its own, and with the last side's words after its first
    ("light" and "light brown sugar"). A wrong reading ("water juice")
    never matches anything a person has, so keeping it is harmless."""
    pieces = [p.strip() for p in _ALTERNATIVE_SPLIT_RE.split(normalized) if p.strip()]
    if len(pieces) < 2:
        return [normalized]
    pieces = [normalize(_ALTERNATIVE_AMOUNT_RE.sub("", p))[0] for p in pieces]
    shared = " ".join(pieces[-1].split()[1:])
    found = []
    for p in pieces[:-1]:
        found.append(p)
        if shared and len(p.split()) == 1:
            found.append(f"{p} {shared}")
    found.append(pieces[-1])
    unique = []
    for p in found:
        if p and p not in unique:
            unique.append(p)
    return unique
