"""
Flour Water Salt Yeast (Ken Forkish): settings for the shared engine
(books/engine.py). See books/__init__.py for the interface.

Format, for reference (sizes in points, as extracted):

    THE SATURDAY WHITE BREAD        30, ALL CAPS, wraps
    <headnote>                      15
    THIS RECIPE MAKES 2 LOAVES, ... 8.7 bold (pizzas: "MAKES ONE 12-INCH PIZZA")
    BULK FERMENTATION: About 5 hours
    PROOF TIME: ... / SAMPLE SCHEDULE: ...
    Levain                          11.2, a table's name (also Poolish,
                                    Biga, Final Dough)
    INGREDIENT / QUANTITY / BAKER'S PERCENTAGE      8.7, column headers
    White flour                     11.2, the table one cell per line:
    1,000 g                         name, grams, volume, then the
    7¾ cups                         baker's percentage (the Final Dough
    100%                            table adds levain and total columns)
    1. Autolyse Combine the ...     15, numbered steps

The pizzas and sauces list ingredients the ordinary way ("1½
tablespoons extra-virgin olive oil"). A table row's cells are joined
back onto its name (is_continuation) and read by parse_ingredient_line:
the first gram amount is what goes into that stage's mix.
"""

import re

from books.line_styles import STYLES, _VOLUME_RE, _volume  # noqa: F401
from common.text_parsing import UNIT_TSP, canonical_volume_unit, parse_typed_amount, volume_to_tsp

TITLE_MIN_SIZE = 29
YIELD_RE = re.compile(r"^(?:THIS RECIPE )?MAKES\b")
HEADER_FIELD_RE = re.compile(
    r"^(?:BULK FERMENTATION|PROOF TIME|SAMPLE SCHEDULE|LEVAIN[- ]FEEDING SCHEDULE|"
    r"FERMENTATION|FINAL DOUGH)\b[^:]*:")
INGREDIENT_STYLE = "volume_paren_metric"
# Steps are numbered ("1. Autolyse ...") or, for the levain breads'
# feeding schedule, lettered ("A. Feed the levain ...").
STEP_RE = re.compile(r"^(?:\d+[a-z]?|[A-Z])\.\s")

# The tables' column headers, between and inside rows.
SKIP_RE = re.compile(
    r"^(?:INGREDIENT|QUANTITY(?: IN)?|BAKER’S(?: PERCENTAGE)?|PERCENTAGE|TOTAL RECIPE|"
    r"QUANTITY IN (?:LEVAIN|POOLISH|BIGA)|LEVAIN|POOLISH|BIGA|FINAL DOUGH MIX|"
    r"Baker’s Formula)$")

# The final dough's table is a group of its own. The pre-ferment's table
# ("Levain", "Poolish", "Biga") is the list's first group; those words
# aren't labels, since the final dough table has a row of that name ("Levain
# 360 g 1⅓ cups 20%").
_STAGE_RE = re.compile(r"^(Final Dough)$")
_PREFERMENT_RE = re.compile(r"^(?:Levain|Poolish|Biga)$")

# One cell of a table row: "1,000 g", "720 g, 90ºF to 95ºF", "7¾ cups",
# "⅓ cup + 1½ tbsp", "100%", "0".
_AMT = r"[\d,.¼½¾⅓⅔⅛⅜⅝⅞]+"
# Also the bits a cell can wrap into: "g**", "+ 1 tbsp", "cup", "50%*".
_CELL_RE = re.compile(
    rf"^(?:(?:scant\s+)?{_AMT}\s*(?:g\b.*|%.*|cups?\b.*|tbsp\b.*|tsp\b.*|\+.*)|0|[+*].*|g\b.*|cups?|tbsp|tsp)$",
    re.IGNORECASE)

# A joined row: "White flour 1,000 g 7¾ cups 100%".
_ROW_RE = re.compile(r"^(?P<name>[A-Za-z][^\d]*?)\s+(?P<grams>\d[\d,]*(?:\.\d+)?)\s*g\b(?P<rest>.*)$")
_ROW_VOLUME_RE = re.compile(
    rf"(?P<amt>{_AMT})\s*(?P<unit>cups?|tbsp|tsp)\b"
    rf"(?:\s*\+\s*(?:scant\s+)?(?P<amt2>{_AMT})\s*(?:scant\s+)?(?P<unit2>cups?|tbsp|tsp)\b)?")


def section_label(line):
    m = _STAGE_RE.match(line.strip())
    return m.group(1) if m else None


def is_continuation(pending, last_line, line):
    """A table cell joins the row it belongs to, as long as the row
    started with an ingredient name (pizza lists start with amounts)."""
    return pending[:1].isalpha() and bool(_CELL_RE.match(line.strip()))


# A row whose final-mix cell is "0": the ingredient goes only into the
# levain or pre-ferment ("Whole wheat flour 0 0 40 g 40 g 4%").
_ZERO_ROW_RE = re.compile(r"^(?P<name>[A-Za-z][^\d]*?)\s+0\b")


def parse_ingredient_line(line):
    # A cell on its own ("500 g", "Scant ⅛ tsp") is part of a row, never
    # an ingredient.
    if _CELL_RE.match(line.strip()):
        return None
    zero = _ZERO_ROW_RE.match(line.strip())
    if zero:
        return {"raw": line.strip(), "format": "baker_table", "metric_amount": 0.0,
                "metric_unit": "g", "imperial_amount": None, "imperial_unit": None,
                "imperial_display": None, "name": zero.group("name").strip()}
    m = _ROW_RE.match(line.strip())
    if not m:
        return STYLES[INGREDIENT_STYLE](line)
    imperial_amount = imperial_unit = display = None
    vol = _ROW_VOLUME_RE.search(m.group("rest"))
    if vol:
        unit = canonical_volume_unit(_unit_word(vol.group("unit")))
        amount = parse_typed_amount(vol.group("amt"))
        if unit and amount is not None:
            tsp = volume_to_tsp(amount, unit)
            if vol.group("amt2"):
                unit2 = canonical_volume_unit(_unit_word(vol.group("unit2")))
                amount2 = parse_typed_amount(vol.group("amt2"))
                if unit2 and amount2 is not None:
                    tsp += volume_to_tsp(amount2, unit2)
            imperial_unit = unit
            imperial_amount = float(tsp / UNIT_TSP[unit])
            display = vol.group(0)
    return {
        "raw": line.strip(),
        "format": "baker_table",
        "metric_amount": float(m.group("grams").replace(",", "")),
        "metric_unit": "g",
        "imperial_amount": imperial_amount,
        "imperial_unit": imperial_unit,
        "imperial_display": display,
        "name": m.group("name").strip(),
    }


def _unit_word(unit):
    return {"tbsp": "tablespoon", "tsp": "teaspoon"}.get(unit, unit)


def ingredient_start(lines):
    """After the yield block, at the first table name, column header or
    ingredient (the headers are skipped when the list is read)."""
    first = next((i for i, line in enumerate(lines) if YIELD_RE.match(line.strip())), None)
    if first is None:
        return len(lines)
    from books.engine import yield_block_length
    for i in range(first + yield_block_length(lines, first, HEADER_FIELD_RE), len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        if STEP_RE.match(line):
            break
        if (section_label(line) or _PREFERMENT_RE.match(line) or SKIP_RE.match(line)
                or parse_ingredient_line(line)):
            return i
    return len(lines)
