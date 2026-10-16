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

# A trailing "for the pan" / "for serving" with no comma before it, e.g.
# "Neutral oil for the pan". Marks the ingredient as not part of the
# recipe proper.
_FOR_USE_RE = re.compile(
    r"\s+for\s+(?:the\s+\w+|serving|sprinkling|dusting|brushing|greasing|garnish|topping)\b.*$")
_PAREN_RE = re.compile(r"\([^()]*\)?")
# A pointer to another recipe in the book: "1 recipe Brioche Dough",
# "Flaky All-Butter Pie Dough (this page)", "One 9-inch pie crust (see
# Recommended Crusts)", "Pie dough for a double crust (see below)",
# "Full Batch of Classic Whipped Cream".
_SUB_RECIPE_RE = re.compile(r"\bbatch\b|\bpage\s+\d+|\brecipes?\b|\bthis page\b"
                            r"|\bsee below\b|\brecipe follows\b|\bcrusts?\b")
_OPTIONAL_RE = re.compile(r"\boptional\b|\bfor (?:serving|sprinkling|dusting|garnish|topping)\b"
                          r"|\bfor the (?:pan|pans|baking sheet|work surface)\b")

# "X or Y", "X and/or Y" inside a normalized name.
_ALTERNATIVE_SPLIT_RE = re.compile(r"\s+(?:and/)?or\s+")
# An amount left in front of an alternative: "lemon juice or 1 g / ¼
# teaspoon citric acid", "black tea or 1 teaspoon instant espresso".
_ALTERNATIVE_AMOUNT_RE = re.compile(
    r"^[\d.¼½¾⅓⅔⅛]+\s*(?:g|ml)?\s*(?:/\s*[\d.¼½¾⅓⅔⅛]+\s*)?"
    r"(?:cups?|tablespoons?|teaspoons?|ounces?|pounds?)?\s+")


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


def normalize(name):
    """Parsed ingredient name -> (normalized name, flags). Flags are any of
    "optional" (garnish, pan grease, explicitly optional), "sub_recipe"
    (a reference to another recipe, not a purchasable ingredient),
    "alternative" (an "X or Y" choice) and "ignored" (on the ignore
    list)."""
    flags = set()
    text = name.lower().strip()
    # "butter, at room temperature, plus more for the pan" still needs the
    # butter, only the "plus more" part is pan prep, so look for optional
    # wording before any "plus" clause.
    if _OPTIONAL_RE.search(re.split(r",?\s+plus\b", text, maxsplit=1)[0]):
        flags.add("optional")
    if _SUB_RECIPE_RE.search(text):
        flags.add("sub_recipe")

    text = _PAREN_RE.sub(" ", text)
    text = text.split(",", 1)[0]
    text = _FOR_USE_RE.sub("", text)
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
        if len(words) > 1 and words[0] in LEADING_WORDS:
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
