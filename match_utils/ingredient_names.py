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
# "Neutral oil for the pan", "Flour for rolling", "Egg wash for
# finishing". Cut from the name; _OPTIONAL_RE decides separately whether
# it's optional ("demerara sugar, for rolling" is what the cookies are
# rolled in, so rolling and finishing aren't).
_FOR_USE_RE = re.compile(
    r"\s+for\s+(?:the\s+\w+|serving|sprinkling|dusting|brushing|greasing|garnish|topping|frying"
    r"|rolling|finishing)\b.*$")
_PAREN_RE = re.compile(r"\([^()]*\)?")
# A pointer to another recipe in the book: "1 recipe Brioche Dough",
# "Flaky All-Butter Pie Dough (this page)", "One 9-inch pie crust (see
# Recommended Crusts)", "Pie dough for a double crust (see below)",
# "Full Batch of Classic Whipped Cream". Not bread with its crust cut
# off ("1 loaf brioche, crusts removed").
_SUB_RECIPE_RE = re.compile(r"\bbatch\b|\bpage\s+\d+|\brecipes?\b|\bthis page\b"
                            r"|\bsee below\b|\brecipe follows\b|\bcrusts?\b(?!\s+(?:removed|trimmed))")
_OPTIONAL_STEP_RE = re.compile(r"\b\w+ing\s+(?:it\s+|them\s+)?is\s+optional\b")
_OPTIONAL_RE = re.compile(r"\boptional\b|\bfor (?:serving|sprinkling|dusting|garnish|topping)\b"
                          r"|\bfor the (?:pan|pans|baking sheet|work surface)\b")

# A list at the start of a name that ends in "or"/"and": "gruyère,
# manchego, or parmesan", "honey, olive oil, and a lemon wedge".
# Each item runs comma to comma, so there's only one way to split a line
# into items: "\s*" before a lazy item gave many ways, and a long line of
# commas and spaces that didn't match took seconds to minutes to fail.
_COMMA_LIST_RE = re.compile(r"^([^,]+(?:,[^,]+)+),\s*(or|and/or|and)\s+([^,]+)")
# The same list ending at the first "or"/"and" after a comma, tried when
# the longest one has prep notes in it: "red, orange, or yellow bell
# pepper, cored, seeded, and thinly sliced" is a list of colours before
# its prep notes.
_FIRST_LIST_RE = re.compile(r"^([^,]+(?:,[^,]+)+?),\s*(or|and/or|and)\s+([^,]+)")
# A prep note among those commas ("vanilla bean, halved lengthwise,
# seeds scraped out, or 2 teaspoons vanilla extract") means they aren't
# a list of ingredients.
# Not inside a hyphenated name ("oil-cured olives", "sun-dried"), and not
# the "-ed" words that are part of what the ingredient is ("red bell
# pepper", "jarred roasted red peppers", "dried apricots").
_PREP_WORD_RE = re.compile(
    r"(?<!-)\b(?!(?:red|jarred|dried|canned|smoked|salted|unsalted|roasted|toasted|pickled|"
    r"cured|aged|seasoned|sweetened|unsweetened|bottled|boiled|cooked|refined|unbleached|bleached)\b)"
    r"(?:[a-z]+ed|cut|torn|split|preferably)\b")
# "Oil for frying, see page 189" points at a technique, not a recipe.
_SEE_PAGE_RE = re.compile(r",?\s*see page\s+\d+")
# "Golden syrup, such as Lyle's, or light corn syrup": a brand aside,
# which would otherwise read as one item of a list.
_SUCH_AS_RE = re.compile(r",?\s+such as\b.*$")
# The bread's unit left in front of its name ("1 loaf brioche bread").
_LOAF_RE = re.compile(r"^(?:[\w-]+\s+)?(?:loaf|loaves)\s+(?:of\s+)?")

# "X or Y", "X and/or Y" inside a normalized name, and choices set off
# by semicolons: "distilled vinegar; 1/4 cup freshly squeezed lemon or
# lime juice; or 2 teaspoons nigari" (HTCEV).
_ALTERNATIVE_SPLIT_RE = re.compile(r"\s+(?:and/)?or\s+|\s*;\s*(?:or\s+|(?=[\d½¼¾⅓⅔⅛]))")
# An amount left in front of an alternative: "lemon juice or 1 g / ¼
# teaspoon citric acid", "black tea or 1 teaspoon instant espresso",
# "whole cherries or 5 cups | 28 ounces frozen cherries".
_AMOUNT_CHARS = r"[\d.¼½¾⅓⅔⅛]+"
_AMOUNT_UNITS = r"(?:g|ml|cups?|tablespoons?|teaspoons?|ounces?|pounds?)\b"
_ALTERNATIVE_AMOUNT_RE = re.compile(
    rf"^{_AMOUNT_CHARS}\s*(?:{_AMOUNT_UNITS})?\s*"
    rf"(?:[/|]\s*{_AMOUNT_CHARS}\s*(?:{_AMOUNT_UNITS})?\s*)?(?=\S)")
# A name that is only a unit, left by a line the parser split oddly
# ("Scant 1 cup" in a table): not an ingredient at all.
_UNIT_ONLY_RE = re.compile(r"^(?:cup|tablespoon|teaspoon|ounce|pound|gram|g|ml|oz|lb)$")
# "lemon zest plus 1 teaspoon juice", "egg plus 1 large yolk", "lemon
# zest and 2 teaspoons juice": two ingredients on one line. "and" only
# before an amount, so "salt and pepper" isn't split here.
_PLUS_RE = re.compile(r"\s+(?:plus|and(?=\s+[\d½¼¾⅓⅔⅛]))\s+")
# The second of those, when it only names a part of the first: "juice"
# is the lemon's, "yolk" the egg's.
_PART_WORDS = {"juice", "zest", "yolk", "white"}
# A side of a choice that only says what form the other side comes in:
# "thyme or ¼ teaspoon dried" means dried thyme, "ground or grated
# nutmeg" ground nutmeg. Size and prep words ("large or 2 medium onions",
# "chopped or grated mozzarella") say nothing the other side doesn't.
_FORM_WORDS = {"dried", "ground", "toasted", "roasted", "smoked", "canned", "cooked", "raw"}
_SIZE_WORDS = {"small", "medium", "large"}
# The amount of a later choice, which isn't part of its name: "thyme or
# ¼ teaspoon dried", "kosher salt or 1/2 teaspoon fine sea salt".
_CHOICE_AMOUNT_RE = re.compile(
    rf"(\b(?:and/)?or\s+)(?:a\s+)?(?:pinch\s+(?:of\s+)?|{_AMOUNT_CHARS}\s*(?:{_AMOUNT_UNITS})?\s*"
    rf"(?:[/|]\s*{_AMOUNT_CHARS}\s*(?:{_AMOUNT_UNITS})?\s*)?(?=[a-z]))")


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
    # "peeling is optional" makes a prep step optional, not the ingredient.
    if _OPTIONAL_RE.search(_OPTIONAL_STEP_RE.sub("", re.split(r",?\s+plus\b", text, maxsplit=1)[0])):
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
    joined = _COMMA_LIST_RE.sub(_join_list, text, count=1)
    if joined == text:
        joined = _FIRST_LIST_RE.sub(_join_list, text, count=1)
    text = joined.split(",", 1)[0]
    # "minced fresh chile, or to taste, or hot red pepper flakes": not a
    # choice.
    text = re.sub(r"\s+or\s+(?:more\s+)?to\s+taste\b", "", text)
    # "1 clove or more garlic": the garlic. Not "butter or more oil",
    # which is a choice.
    if (m := re.match(r"(\S+)\s+or\s+more\s+(?=[a-z])", text)) and m.group(1) in LEADING_WORDS:
        text = text[m.end():]
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
    # "chamomile buds or 2 or 3 tea bags" would leave "or or".
    words = re.sub(r"\bor(?:\s+or\b)+", "or", _CHOICE_AMOUNT_RE.sub(r"\1", " ".join(words))).split()
    if words:
        words[-1] = singular(words[-1])
    text = " ".join(words)
    text = EQUIVALENTS.get(text, text)
    if _UNIT_ONLY_RE.match(text):
        return "", flags

    if re.search(r"\bor\b", text):
        flags.add("alternative")
    if text in IGNORE:
        flags.add("ignored")
    return text, flags


_AND_RE = re.compile(r"\s+and\s+")


def _plus_pieces(name):
    """A "X plus N Y" name as its two ingredients: "lemon zest plus 1
    teaspoon juice" is lemon zest and lemon juice, "butter plus 3
    tablespoons olive oil" butter and olive oil. A second side that only
    says how the first is cut ("thyme plus ½ teaspoon chopped") is the
    same ingredient. Left whole when "plus" is inside a choice ("flour or
    2 cups all-purpose plus 2 cups whole wheat"), where both sides of the
    plus are one option."""
    split = _PLUS_RE.split(name, maxsplit=1)
    if len(split) < 2 or re.search(r"\bor\b", split[0]):
        return [name]
    first, rest = split
    if not rest:
        return [name]
    first = normalize(first)[0]
    second = normalize(_ALTERNATIVE_AMOUNT_RE.sub("", rest))[0]
    if not second or second in LEADING_WORDS:
        return [first]
    if second in _PART_WORDS and first:
        second = f"{first.split()[0]} {second}"
    return [p for p in (first, second) if p]


def pieces(normalized, unmeasured):
    """The separate ingredients a normalized name stands for. A line with
    no amount can name two ingredients ("Kosher salt and freshly ground
    black pepper"), both needed. A measured line is one ingredient, and
    splitting it at "and" would break names like "half-and-half"; it's
    only split at "plus" (see _plus_pieces)."""
    parts = _AND_RE.split(normalized) if unmeasured else [normalized]
    if len(parts) > 1:
        parts = [p for p in (normalize(part)[0] for part in parts) if p]
    found = []
    for part in parts:
        for piece in _plus_pieces(part):
            if piece not in found:
                found.append(piece)
    return found


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
    # "coconut milk or 1½ cups coconut milk plus 1½ cups water": each
    # option is what comes before its "plus".
    pieces = [normalize(_ALTERNATIVE_AMOUNT_RE.sub("", _PLUS_RE.split(p, maxsplit=1)[0]))[0]
              for p in pieces]
    # A bare count left by "small or 1 or 2 large eggplant".
    pieces = [p for p in pieces if p and not p.isdigit()]
    if not pieces:
        return [normalized]
    last = pieces[-1]
    shared = " ".join(last.split()[1:])
    found = []
    for i, p in enumerate(pieces):
        if len(p.split()) == 1 and p in LEADING_WORDS and len(pieces) > 1:
            # "large or 2 medium onions": just the onion. A size can also
            # be a grade ("medium or coarse cornmeal", "medium- or
            # long-grain rice"), so that reading is kept.
            if i < len(pieces) - 1 and shared and p in _SIZE_WORDS:
                found.append(f"{p} {shared}")
            continue
        if len(p.split()) == 1 and p in _FORM_WORDS and len(pieces) > 1:
            # "thyme or dried": dried thyme. "cooked or canned
            # chickpeas": cooked chickpeas. "ground or grated nutmeg":
            # ground nutmeg.
            other = pieces[0] if i > 0 else (shared or last)
            found.append(normalize(f"{p} {other}")[0])
            continue
        found.append(p)
        if i < len(pieces) - 1 and shared and len(p.split()) == 1:
            found.append(f"{p} {shared}")
    unique = []
    for p in found:
        if p and p not in unique:
            unique.append(p)
    return unique
