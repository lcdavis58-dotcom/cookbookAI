"""
Ingredient line styles: one parser per way a cookbook prints an amount.
A book module names its style (INGREDIENT_STYLE = "metric_slash") and
the engine uses that parser, so a new book printed the same way as one
already done needs no parsing code of its own.

Every parser takes one line and returns the same dict shape, or None if
the line isn't an ingredient in that style:

    raw               the line as given
    format            which parser read it ("count_only" for a bare count)
    metric_amount     the weight, if printed (grams, or BraveTart's ounces)
    metric_unit       "g", "kg", "ml", "l", "oz" or "lb"
    imperial_amount   the volume (or count) as a number
    imperial_unit     canonical volume unit, or None for a count
    imperial_display  the book's own wording of the volume ("¼ cup"), for
                      the unscaled side
    name              the ingredient name

Styles:
    metric_slash      "57 g / 2 ounces / 4 tablespoons unsalted butter"
                      (The Book On Pie; also Savory Baking, The Fearless
                      Baker per their layouts)
    volume_paren_metric
                      "¾ cup sugar (5.3 oz / 150g)" (Dessert Person)
    volume_pipe_weight
                      "2⅓ cups | 10½ ounces all-purpose flour" (BraveTart)
    metric_bracket_volume
                      "225 g butter" with "[16 tablespoons]" on the next
                      line, joined on by the book (Momofuku Milk Bar)

Deliberately has nothing to do with the LLM: a book's format is
consistent enough that a regex parses it reliably, a stronger guarantee
than trusting a small model to transcribe numbers.
"""

import re

from common.text_parsing import (AMOUNT, FRACTION_CHARS, UNIT_TSP, canonical_volume_unit,
                                 parse_amount, parse_typed_amount, volume_to_tsp)

# A numbered instruction step ("1. Whip the cream...") has a period right
# after the leading number, an ingredient amount never does ("235 g...").
NUMBERED_STEP_RE = re.compile(r"^\d+\.\s")


# ---------------------------------------------------------------------------
# metric_slash: "245 g / 1 cup whole milk"
# ---------------------------------------------------------------------------
# Metric amount + unit, a slash, then imperial amount + unit, then the
# name. Imperial amount/unit are optional since a few lines only give a
# count ("50 g / 1 large egg"). Some lines give TWO imperial measures
# ("57 g / 2 ounces / 4 tablespoons unsalted butter"), the optional imp2
# group catches the second one so it doesn't end up glued to the front of
# the ingredient name.
_IMP_UNIT = r"(?:packed\s+cups?|cups?|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz|pounds?|lbs?)\b"
METRIC_SLASH_RE = re.compile(
    rf"^(?P<metric_amt>\d+\.\d+|[\d{FRACTION_CHARS}]+)\s*(?P<metric_unit>g|kg|ml|l)\s*/\s*"
    rf"(?P<imp_amt>[\d{FRACTION_CHARS}]+)?\s*"
    rf"(?P<imp_unit>{_IMP_UNIT})?\s*"
    rf"(?:/\s*(?P<imp2_amt>[\d{FRACTION_CHARS}]+)\s*(?P<imp2_unit>{_IMP_UNIT})\s*)?"
    rf"(?P<name>.+)$",
    re.IGNORECASE,
)
_VOLUME_UNIT_WORD_RE = re.compile(r"cup|tablespoon|tbsp|teaspoon|tsp", re.IGNORECASE)
# Lines with no metric/imperial split, just a bare count: "2 large eggs".
_BARE_COUNT_RE = re.compile(rf"^(?P<amt>[\d{FRACTION_CHARS}]+)\s+(?P<name>.+)$")


def metric_slash(line):
    line = line.strip()
    if not line or NUMBERED_STEP_RE.match(line):
        return None

    m = METRIC_SLASH_RE.match(line)
    if m:
        imp_amt, imp_unit = m.group("imp_amt"), m.group("imp_unit")
        # With two imperial measures, keep the volume one (8 tablespoons
        # over 4 ounces): measurement_display.py can break a scaled volume
        # into real measuring tools, a scaled weight it can only round.
        if m.group("imp2_unit") and _VOLUME_UNIT_WORD_RE.search(m.group("imp2_unit")) \
                and not _VOLUME_UNIT_WORD_RE.search(imp_unit or ""):
            imp_amt, imp_unit = m.group("imp2_amt"), m.group("imp2_unit")
        return {
            "raw": line,
            "format": "metric_imperial",
            "metric_amount": parse_amount(m.group("metric_amt")),
            "metric_unit": m.group("metric_unit"),
            "imperial_amount": parse_amount(imp_amt) if imp_amt else None,
            "imperial_unit": imp_unit,
            "imperial_display": f"{imp_amt} {imp_unit.strip()}" if imp_amt and imp_unit else None,
            "name": m.group("name").strip(),
        }

    m = _BARE_COUNT_RE.match(line)
    if m:
        return {
            "raw": line,
            "format": "count_only",
            "metric_amount": None,
            "metric_unit": None,
            "imperial_amount": parse_amount(m.group("amt")),
            "imperial_unit": None,
            "name": m.group("name").strip(),
        }
    return None


# ---------------------------------------------------------------------------
# volume_paren_metric: "¾ cup sugar (5.3 oz / 150g)"
# ---------------------------------------------------------------------------
#   - Compound amounts with "plus": "3 tablespoons plus 1/3 cup almond butter"
#   - Footnote markers (circled numbers ①②③) appear inline and are stripped
#   - Bare counts ("2 large eggs") read as count-only

_FOOTNOTE_RE = re.compile(r"[①-⑳]")
# "(7 oz / 200g)", "(1½ oz / 43g)", or grams alone "(200g)". The ounce
# half is skipped over rather than parsed, the gram figure is what we keep.
_METRIC_PAREN_RE = re.compile(r"\(\s*(?:[^()]*?oz\s*/\s*)?([\d.,]+)\s*(k?g)\s*\)")
_PAREN_UNIT = r"(?:cups?|tablespoons?|teaspoons?|tbsp|tsp|sticks?)"
# The Cookie Book's liquids: "1 tablespoon (15 ml) real vanilla extract".
# Only right after an amount and a volume unit, so "1 (750 ml) bottle"
# stays a count.
# A range ("1 to 2 tablespoons (15 to 30 ml) milk") scales from its low
# end, and its wording is kept for display, as in volume_pipe_weight.
_RANGE_END = rf"(?:\s+to\s+{AMOUNT})?"
_ML_AFTER_UNIT_RE = re.compile(
    rf"^(?:{AMOUNT}){_RANGE_END}\s*{_PAREN_UNIT}(\s+\(\s*([\d.,]+)(?:\s+to\s+[\d.,]+)?\s*ml\s*\))",
    re.IGNORECASE)
_SINGLE_RE = re.compile(rf"^({AMOUNT})({_RANGE_END})\s*({_PAREN_UNIT})\s+", re.IGNORECASE)
_COMPOUND_RE = re.compile(
    rf"^({AMOUNT})\s*({_PAREN_UNIT})\s+plus\s+({AMOUNT})\s*({_PAREN_UNIT})\s+", re.IGNORECASE
)
# A count, then the name, or a size in parentheses first: "2 (3-inch)
# cinnamon sticks", "1 (750 ml) bottle dry rosé wine".
_PAREN_COUNT_RE = re.compile(rf"^({AMOUNT})\s+(?=[A-Za-z(])")


def volume_paren_metric(line):
    """Volume amounts keep their ORIGINAL unit (cup stays cup) rather than
    being normalized to teaspoons, since measurement_display.py decides
    between cup-fraction and tbsp/tsp output based on that unit. A
    compound "3 tablespoons plus 1/3 cup" is summed exactly and expressed
    in the larger of its two units; its original wording is kept in
    imperial_display."""
    original = line.strip()
    if not original or NUMBERED_STEP_RE.match(original):
        return None

    line = _FOOTNOTE_RE.sub("", original).strip()

    metric_amount = None
    metric_unit = "g"
    m = _METRIC_PAREN_RE.search(line)
    ml = None if m else _ML_AFTER_UNIT_RE.match(line)
    if ml:
        metric_unit = "ml"
        try:
            metric_amount = float(ml.group(2).replace(",", ""))
        except ValueError:
            metric_amount = None
        line = line[:ml.start(1)] + line[ml.end(1):]
    elif m:
        try:
            metric_amount = float(m.group(1).replace(",", ""))
        except ValueError:
            metric_amount = None
        metric_unit = m.group(2).lower()  # "(1.2kg)" as well as "(150g)"
        line = (line[:m.start()] + line[m.end():])
        line = re.sub(r"\s+", " ", line).strip()
        line = re.sub(r"\s+,", ",", line)

    imperial_display = None
    compound = _COMPOUND_RE.match(line)
    if compound:
        amt1, unit1, amt2, unit2 = compound.groups()
        tsp1 = volume_to_tsp(parse_typed_amount(amt1), unit1)
        tsp2 = volume_to_tsp(parse_typed_amount(amt2), unit2)
        if tsp1 is None or tsp2 is None:
            return None
        imperial_unit = max(
            (canonical_volume_unit(unit1), canonical_volume_unit(unit2)),
            key=lambda u: UNIT_TSP[u],
        )
        imperial_amount = float((tsp1 + tsp2) / UNIT_TSP[imperial_unit])
        imperial_display = line[:compound.end()].strip()
        name = line[compound.end():].strip()
    else:
        single = _SINGLE_RE.match(line)
        if single:
            amt, range_end, unit = single.groups()
            imperial_amount = parse_typed_amount(amt)
            if range_end:
                imperial_display = line[:single.end()].strip()
            imperial_unit = canonical_volume_unit(unit)
            if imperial_amount is None:
                return None
            name = line[single.end():].strip()
        else:
            fallback = _PAREN_COUNT_RE.match(line)
            if not fallback:
                return None
            imperial_amount = parse_typed_amount(fallback.group(1))
            if imperial_amount is None:
                return None
            imperial_unit = None
            name = line[fallback.end():].strip()

    return {
        "raw": original,
        "format": "dessert_person",
        "metric_amount": metric_amount,
        "metric_unit": metric_unit if metric_amount is not None else None,
        "imperial_amount": imperial_amount,
        "imperial_unit": imperial_unit,
        "imperial_display": imperial_display,
        "name": name,
    }


# ---------------------------------------------------------------------------
# volume_pipe_weight: "2⅓ cups | 10½ ounces all-purpose flour"
# ---------------------------------------------------------------------------
#     1 cup plus 2 tablespoons | 8 ounces sugar
#     ¼ cup packed | 2 ounces light brown sugar
#     6 heaping cups | 2 pounds whole ripe strawberries
#     ½ to ¾ cup | 3 to 5 ounces sugar
# or a volume alone ("1 tablespoon vanilla extract"), a weight alone, or
# a count ("1 large egg"). BraveTart has no grams anywhere, so the weight
# goes in the metric slot in ounces (or pounds) as printed rather than
# being converted.

_VOLUME_UNIT = r"(?:cups?|tablespoons?|teaspoons?|sticks?)"
# "1 packed cup", "1 cup firmly packed", "6 heaping cups", "1 rounded cup".
_VOLUME_WORD = r"(?:(?:firmly|gently)\s+)?(?:packed|heaping|rounded|level|scant|generous)"
_VOLUME = (
    rf"(?P<amt>{AMOUNT})(?:\s+(?P<join>plus|to)\s+(?P<amt2>{AMOUNT}))?\s+"
    rf"(?:{_VOLUME_WORD}\s+)?(?P<unit>{_VOLUME_UNIT})\b(?:\s+{_VOLUME_WORD})?"
    rf"(?:\s+(?P<op>plus|minus)\s+(?P<plus_amt>{AMOUNT})\s+(?P<plus_unit>{_VOLUME_UNIT})\b)?"
)
# The volume side of "volume | weight", which can end in a note: "3 cups
# (finely chopped) | 15 ounces milk chocolate".
_VOLUME_RE = re.compile(rf"^{_VOLUME}(?:\s*\([^()]*\))?$", re.IGNORECASE)
# A volume with the name after it, for lines with no weight.
_VOLUME_NAME_RE = re.compile(rf"^{_VOLUME}\s+(?P<name>.+)$", re.IGNORECASE)
_WEIGHT_RE = re.compile(
    rf"^(?P<amt>{AMOUNT})(?:\s+to\s+{AMOUNT})?\s+(?P<unit>ounces?|pounds?)\b,?\s*(?P<name>.*)$",
    re.IGNORECASE)
# A count, then the name, or a size first: "1 medium, 6-ounce russet
# potato", "1 3- or 4-ounce block white chocolate".
_PIPE_COUNT_RE = re.compile(rf"^(?P<amt>{AMOUNT})\s+(?P<name>(?:[A-Za-z(“\"]|\d+-).*)$")
# A line naming another recipe by page: "Caramelized White Chocolate
# (page 60)". A step can mention a page too, but it's a sentence.
PAGE_REF_RE = re.compile(r"\bpages? \d+")


def names_sub_recipe(line):
    return bool(PAGE_REF_RE.search(line)) and not re.search(r"\.(?:\s|$)", line)


def _split_pipe(line):
    """(volume side, weight side) at the first "|" outside parentheses,
    or None. "1 envelope (2¼ teaspoons | ¼ ounce) gelatin" has none."""
    depth = 0
    for i, ch in enumerate(line):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "|" and depth == 0:
            return line[:i].strip(), line[i + 1:].strip()
    return None


def _volume(m):
    """(amount, canonical unit, display) from a volume match. "1 cup
    plus 2 tablespoons" (or "minus") is worked out exactly in the larger
    unit; a range ("½ to ¾ cup") scales from its low end."""
    unit = canonical_volume_unit(m.group("unit"))
    amount = parse_typed_amount(m.group("amt"))
    if amount is None or unit is None:
        return None
    if m.group("join") == "plus":
        amount += parse_typed_amount(m.group("amt2")) or 0
    if m.group("plus_amt"):
        plus_unit = canonical_volume_unit(m.group("plus_unit"))
        extra = volume_to_tsp(parse_typed_amount(m.group("plus_amt")), plus_unit)
        tsp = volume_to_tsp(amount, unit) + (-extra if m.group("op").lower() == "minus" else extra)
        unit = max((unit, plus_unit), key=lambda u: UNIT_TSP[u])
        amount = float(tsp / UNIT_TSP[unit])
    text = m.group(0) if "name" not in m.groupdict() else m.string[:m.start("name")]
    return amount, unit, text.strip()


def _weight_unit(unit):
    return "lb" if unit.lower().startswith("pound") else "oz"


def _pipe_result(raw, name, weight=None, weight_unit=None, volume=None):
    amount, unit, display = volume or (None, None, None)
    return {
        "raw": raw,
        "format": "bravetart",
        "metric_amount": weight,
        "metric_unit": weight_unit if weight is not None else None,
        "imperial_amount": amount,
        "imperial_unit": unit,
        "imperial_display": display,
        "name": name.strip(),
    }


def volume_pipe_weight(line):
    line = line.strip()
    if not line:
        return None

    # "Shy ½ teaspoon": just under the amount, the same as "scant".
    if line.lower().startswith("shy "):
        parsed = volume_pipe_weight(line[4:])
        return {**parsed, "raw": line, "qualifier": "scant"} if parsed else None

    sides = _split_pipe(line)
    if sides:
        volume_m = _VOLUME_RE.match(sides[0])
        weight_m = _WEIGHT_RE.match(sides[1])
        if volume_m and weight_m and weight_m.group("name"):
            volume = _volume(volume_m)
            if volume:
                return _pipe_result(line, weight_m.group("name"), parse_typed_amount(weight_m.group("amt")),
                                    _weight_unit(weight_m.group("unit")), volume)
        return None

    m = _VOLUME_NAME_RE.match(line)
    if m:
        volume = _volume(m)
        if volume:
            return _pipe_result(line, m.group("name"), volume=volume)
    m = _WEIGHT_RE.match(line)
    if m and m.group("name"):
        return _pipe_result(line, m.group("name"), parse_typed_amount(m.group("amt")),
                            _weight_unit(m.group("unit")))
    m = _PIPE_COUNT_RE.match(line)
    if m:
        amount = parse_typed_amount(m.group("amt"))
        if amount is not None:
            return {**_pipe_result(line, m.group("name")), "format": "count_only", "imperial_amount": amount}
    # Other recipes offered with no amount, too long for the shared
    # fallback: "Powdered or granulated sugar or Cinnamon Sugar (page 44)
    # or Vanilla Sugar Sprinkle (page 46), to taste".
    if names_sub_recipe(line) and line[:1].isupper():
        return {**_pipe_result(line, line), "format": "fallback", "unmeasured": True}
    return None


# ---------------------------------------------------------------------------
# metric_bracket_volume: "225 g butter, at room temperature [16 tablespoons]"
# ---------------------------------------------------------------------------
# Momofuku Milk Bar prints the volume on a line of its own under the
# weighed one; the book module joins that "[...]" line on, so this reads
#     225 g butter, at room temperature [16 tablespoons (2 sticks)]
#     300 g mini pretzels [about ¾ (16-ounce) bag (6 cups)]
#     ½ recipe Cornflake Crunch [180 g (2 cups)]
#     1 egg
# The bracket is optional; one that isn't a plain volume ("about ¾ bag")
# is left in the name's raw text but not read.

_BRACKET_RE = re.compile(r"\s*\[([^\[\]]*)\]\s*$")
# "190 g graham cracker crumbs 1½ cups]": the PDF lost the "[".
_UNOPENED_BRACKET_RE = re.compile(rf"\s+((?:about\s+)?{AMOUNT}\s+[^\[\]\d]+)\]\s*$", re.IGNORECASE)
_METRIC_FIRST_RE = re.compile(rf"^(?P<amt>{AMOUNT})\s*(?P<unit>kg|g|ml|l)\s+(?P<name>\S.*)$", re.IGNORECASE)
# "[180 g (2 cups)]" under a sub-recipe: its weight.
_BRACKET_METRIC_RE = re.compile(rf"^(?P<amt>{AMOUNT})\s*(?P<unit>kg|g|ml|l)\b", re.IGNORECASE)


def metric_bracket_volume(line):
    original = line.strip()
    if not original or NUMBERED_STEP_RE.match(original):
        return None
    line, bracket = original, None
    m = _BRACKET_RE.search(line) or (None if "[" in line else _UNOPENED_BRACKET_RE.search(line))
    if m:
        line, bracket = line[:m.start()].strip(), m.group(1).strip()

    volume = None
    if bracket:
        volume_m = _VOLUME_RE.match(bracket)
        if volume_m:
            volume = _volume(volume_m)

    m = _METRIC_FIRST_RE.match(line)
    if m:
        return {**_pipe_result(original, m.group("name"), parse_typed_amount(m.group("amt")),
                               m.group("unit").lower(), volume),
                "format": "metric_bracket"}
    m = _PIPE_COUNT_RE.match(line)
    if m:
        amount = parse_typed_amount(m.group("amt"))
        if amount is None:
            return None
        weight = _BRACKET_METRIC_RE.match(bracket) if bracket else None
        result = {**_pipe_result(original, m.group("name")), "format": "count_only",
                  "imperial_amount": amount}
        if weight:
            result["metric_amount"] = parse_typed_amount(weight.group("amt"))
            result["metric_unit"] = weight.group("unit").lower()
        return result
    return None


STYLES = {
    "metric_slash": metric_slash,
    "volume_paren_metric": volume_paren_metric,
    "volume_pipe_weight": volume_pipe_weight,
    "metric_bracket_volume": metric_bracket_volume,
}
