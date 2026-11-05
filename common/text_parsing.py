"""
Small text-parsing building blocks used across books and scripts: unicode
fraction amounts, the ALL-CAPS line shape cookbooks use for titles and
section headers, telling a component label from a new section, and US
volume units.
"""

import re
from fractions import Fraction

FRACTIONS = {
    "¼": 0.25, "½": 0.5, "¾": 0.75,
    "⅓": 1 / 3, "⅔": 2 / 3,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}
FRACTION_CHARS = "".join(FRACTIONS.keys())

# A short ALL-CAPS line (letters, accented ones included, digits, spaces,
# and a small set of punctuation): component labels like "FILLING",
# "CRÈME BRÛLÉE" or "TOPPING (OPTIONAL)", and asides like "PIE PEP TALK".
_CAPS = "A-Z0-9À-ÖØ-Þ"
ALLCAPS_LINE_RE = re.compile(rf"^[{_CAPS}][{_CAPS} ,\-'/’&();“”\"]{{1,59}}$")

# How many non-blank lines after a heading to look at for an ingredient.
# More than one, since a component often opens with a line no parser can
# read ("Butter for the pan") before its first measured ingredient.
COMPONENT_LOOKAHEAD = 3


# Circled footnote markers some books print after a heading ("MARMALADE ②").
_FOOTNOTE_MARK_RE = re.compile(r"\s*[①-⑳]+\s*$")


def heading_text(line):
    """The ALL-CAPS heading on this line, without any trailing footnote
    marker, or None if the line isn't one."""
    text = _FOOTNOTE_MARK_RE.sub("", line.strip())
    return text if ALLCAPS_LINE_RE.match(text) else None


def is_component_label(lines, i, parse, stop_at=()):
    """Whether lines[i], a heading, labels one component's ingredients
    ("FILLING", "MANGO CARAMEL SAUCE", "CANDIED CLEMENTINES") rather than
    starting something new: true if one of the next COMPONENT_LOOKAHEAD
    non-blank lines parses as an ingredient with the book's own parser
    (parse, the book module's parse_ingredient_line). Component names are
    mostly unique to their recipe, so this works without a list of them.

    stop_at holds line indices that end the look-ahead early, such as the
    lines of the next recipe's title block.
    """
    seen = 0
    for j in range(i + 1, len(lines)):
        if j in stop_at:
            return False
        stripped = lines[j].strip()
        if not stripped:
            continue
        if parse(stripped):
            return True
        seen += 1
        if seen >= COMPONENT_LOOKAHEAD:
            return False
    return False


def parse_amount(text):
    """Convert a quantity string (possibly a unicode fraction, possibly a
    whole number glued to one like "1½") into a float. Returns None if it
    doesn't look like a number at all.
    """
    text = text.strip()
    if not text:
        return None

    # "1½", or "1 ½" with a space (Ratio, a few lines elsewhere).
    m = re.match(rf"^(\d+)?\s?({'|'.join(re.escape(c) for c in FRACTIONS)})?$", text)
    if m and (m.group(1) or m.group(2)):
        whole = float(m.group(1)) if m.group(1) else 0.0
        frac = FRACTIONS[m.group(2)] if m.group(2) else 0.0
        return whole + frac

    try:
        return float(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Typed fractions and US volume units, for books that print "1/3 cup" or
# "1 cup plus 2 tablespoons" (Dessert Person, BraveTart)
# ---------------------------------------------------------------------------

# An amount can be a plain or decimal number, a unicode fraction (with or
# without a whole number glued on, "1⅓"), or a typed fraction ("1/3",
# "1 1/2"). PDFs often encode typed fractions with U+2044 FRACTION SLASH
# rather than "/", so both count.
AMOUNT = (
    rf"(?:\d+\s+\d+[/⁄]\d+|\d+[/⁄]\d+|\d* ?[{FRACTION_CHARS}]|\d+(?:\.\d+)?)"
)
_TYPED_FRACTION_RE = re.compile(r"^(?:(\d+)\s+)?(\d+)[/⁄](\d+)$")
_SMALL_DENOMINATORS = {2, 3, 4, 8}

TSP_PER_TBSP = 3
TSP_PER_CUP = 48
# A stick of butter is 8 tablespoons. It's a real unit here (not just a
# word left in the ingredient name) so "1 stick plus 2 tablespoons" sums
# correctly and the display can say "2 sticks" instead of a bare "2".
TSP_PER_STICK = 8 * TSP_PER_TBSP
UNIT_TSP = {"teaspoon": 1, "tablespoon": TSP_PER_TBSP,
            "stick": TSP_PER_STICK, "cup": TSP_PER_CUP}


def parse_typed_amount(text):
    """parse_amount() plus typed fractions ("1/3", "1 1/2"), which
    Dessert Person and BraveTart use but Book on Pie's unicode-only
    format never needed."""
    m = _TYPED_FRACTION_RE.match(text.strip())
    if m:
        whole = int(m.group(1)) if m.group(1) else 0
        numerator, denominator = m.group(2), int(m.group(3))
        if denominator == 0:
            return None
        # "11/2" is 1 1/2 with the space lost in the PDF (How to Cook
        # Everything Vegetarian): recipes never print improper fractions.
        if (not whole and len(numerator) >= 2 and denominator in _SMALL_DENOMINATORS
                and int(numerator[-1]) < denominator):
            whole, numerator = int(numerator[:-1]), numerator[-1]
        return whole + int(numerator) / denominator
    return parse_amount(text)


def canonical_volume_unit(unit):
    """Collapse "cups"/"Tablespoons"/"tsp"/"sticks" etc. to one of the
    keys of UNIT_TSP."""
    unit = (unit or "").lower()
    if "stick" in unit:
        return "stick"
    if "teaspoon" in unit or unit == "tsp":
        return "teaspoon"
    if "tablespoon" in unit or unit == "tbsp":
        return "tablespoon"
    if "cup" in unit:
        return "cup"
    return None


def volume_to_tsp(amount, unit):
    """Convert a volume amount to teaspoons using exact integer ratios."""
    canonical = canonical_volume_unit(unit)
    if canonical is None or amount is None:
        return None
    return Fraction(amount).limit_denominator(1000) * UNIT_TSP[canonical]
