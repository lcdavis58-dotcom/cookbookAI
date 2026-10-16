"""
Dessert Person (Claire Saffitz): recipe-boundary detection, title
extraction, and ingredient parsing. See books/__init__.py for the
interface every book module provides.

Format, for reference:

    Spiced Pear Cake
    with Maple Glaze
    Season: Fall | Active Time: 40 minutes | Total Time: 2 hours, plus time to cool
    | Difficulty: 2 (Easy) | Dairy-Free
    <intro prose>
    Makes 1 round cake
    Special Equipment: 9-inch round cake pan, stand mixer
    CAKE
    ¾ cup sugar (5.3 oz / 150g)
    2 tablespoons plus ¼ cup tahini (2.4 oz / 68g) ①
    Make the batter: In a large bowl, whisk...
"""

import re
from fractions import Fraction

from common.text_parsing import FRACTION_CHARS, parse_amount
from common.word_list_loader import load_book_specific

# ---------------------------------------------------------------------------
# Recipe-boundary detection (ingest)
# ---------------------------------------------------------------------------
# Different anchor than Book on Pie: "Season:" is a rare, distinctive
# literal string that follows every recipe title, simpler and more reliable
# than the ALL-CAPS + MAKES pattern. Handles two observed wrap behaviors:
#   - The metadata block (Season/Active Time/Total Time/Difficulty) can
#     wrap across lines at an unpredictable point; an unclosed parenthetical
#     or a continuation starting with "|" or "(" signals there's more to
#     consume.
#   - The title itself is sometimes two lines, the dish name followed by a
#     "with X" subtitle (e.g. "Rice Pudding Cake" / "with Mango Caramel"),
#     detected by the specific "with [Capital]" pattern on the line
#     immediately before "Season:".

SEASON_LINE_RE = re.compile(r"^Season:", re.IGNORECASE)
DIFFICULTY_RE = re.compile(r"Difficulty", re.IGNORECASE)
WITH_SUBTITLE_RE = re.compile(r"^with\s+[A-Z]")


def _paren_balance(text):
    """Count of unmatched '(' in text (positive = still open)."""
    return text.count("(") - text.count(")")


def find_recipe_starts(lines):
    """Return (start_line_indices, consumed_line_indices) for every recipe
    title in Dessert Person. consumed covers the title line(s) plus the
    full Season/Difficulty metadata block so that find_section_starts does
    not mistake any part of them for a standalone section header.
    """
    starts = []
    consumed = set()
    n = len(lines)
    i = 0
    while i < n:
        stripped = lines[i].strip()
        if stripped and i + 1 < n and SEASON_LINE_RE.match(lines[i + 1].strip()):
            title_start = i

            # Two-line title: the line before "Season:" is a "with X"
            # subtitle, so the real title begins one line earlier.
            if WITH_SUBTITLE_RE.match(stripped) and i > 0 and lines[i - 1].strip():
                title_start = i - 1

            season_idx = i + 1
            j = season_idx
            found_difficulty_at = None
            while j < n and j < season_idx + 4:
                if DIFFICULTY_RE.search(lines[j]):
                    found_difficulty_at = j
                    break
                j += 1

            if found_difficulty_at is not None:
                end = found_difficulty_at
                # Consume continuation lines while either:
                # - An open parenthetical hasn't been closed yet (the
                #   difficulty label wraps mid-phrase), OR
                # - The next line starts a fresh field with "|" or "("
                #   even though nothing is currently open (a trailing
                #   tag like "| Dairy-Free" on its own line).
                guard = 0
                while guard < 5:
                    balance = _paren_balance(
                        "\n".join(lines[season_idx:end + 1])
                    )
                    looks_like_more = (
                        end + 1 < n
                        and lines[end + 1].strip()[:1] in ("|", "(")
                    )
                    if (balance > 0 or looks_like_more) and end + 1 < n:
                        end += 1
                        guard += 1
                    else:
                        break

                starts.append(title_start)
                for idx in range(title_start, end + 1):
                    consumed.add(idx)
                i = end
        i += 1
    return starts, consumed


# ---------------------------------------------------------------------------
# Title extraction (query/scale)
# ---------------------------------------------------------------------------

def extract_title(text, include_subtitle=True):
    """Dessert Person titles are Title Case, not ALL-CAPS, so the anchor
    is the same one ingest uses: everything before the "Season:" line.
    That's one line, or two when there's a "with X" subtitle ("Rice
    Pudding Cake" / "with Mango Caramel"). A chunk that doesn't have
    "Season:" within its first few lines isn't the start of a recipe (e.g.
    a later part of a split one), so it has no title.
    """
    lines = [line.strip() for line in text.splitlines()[:3]]
    for i, line in enumerate(lines):
        if SEASON_LINE_RE.match(line):
            title_lines = [l for l in lines[:i] if l]
            if not include_subtitle:
                title_lines = title_lines[:1]
            return " ".join(title_lines)
    return ""


# ---------------------------------------------------------------------------
# Ingredient parsing (scale)
# ---------------------------------------------------------------------------
# Format differences from Book on Pie:
#   - Imperial first, metric weight in parentheses: "¾ cup sugar (5.3 oz / 150g)"
#   - Compound amounts with "plus": "3 tablespoons plus 1/3 cup almond butter"
#   - Footnote markers (circled numbers ①②③) appear inline and must be stripped
#   - Metric parenthetical uses "oz / Ng" format, not "Ng / N unit" like BOP
#   - Bare counts ("2 large eggs") need the same count-only fallback as BOP

_FOOTNOTE_RE = re.compile(r"[①-⑳]")
# "(7 oz / 200g)", "(1½ oz / 43g)", or grams alone "(200g)". The ounce
# half is skipped over rather than parsed, the gram figure is what we keep.
_METRIC_PAREN_RE = re.compile(r"\(\s*(?:[^()]*?oz\s*/\s*)?([\d.,]+)\s*g\s*\)")
# An amount can be a plain or decimal number, a unicode fraction (with or
# without a whole number glued on, "1⅓"), or a typed fraction ("1/3",
# "1 1/2"). PDFs often encode typed fractions with U+2044 FRACTION SLASH
# rather than "/", so both count.
_NUM = (
    rf"(?:\d+\s+\d+[/⁄]\d+|\d+[/⁄]\d+|\d*[{FRACTION_CHARS}]|\d+(?:\.\d+)?)"
)
_UNIT = r"(?:cups?|tablespoons?|teaspoons?|tbsp|tsp|sticks?)"
_SINGLE_RE = re.compile(rf"^({_NUM})\s*({_UNIT})\s+", re.IGNORECASE)
_COMPOUND_RE = re.compile(
    rf"^({_NUM})\s*({_UNIT})\s+plus\s+({_NUM})\s*({_UNIT})\s+", re.IGNORECASE
)
_COUNT_RE = re.compile(rf"^({_NUM})\s+(?=[A-Za-z])")
_INSTRUCTION_RE = re.compile(r"^\d+\.\s")
_TYPED_FRACTION_RE = re.compile(r"^(?:(\d+)\s+)?(\d+)[/⁄](\d+)$")

_TSP_PER_TBSP = 3
_TSP_PER_CUP = 48
# A stick of butter is 8 tablespoons. It's a real unit here (not just a
# word left in the ingredient name) so "1 stick plus 2 tablespoons" sums
# correctly and the display can say "2 sticks" instead of a bare "2".
_TSP_PER_STICK = 8 * _TSP_PER_TBSP
_UNIT_TSP = {"teaspoon": 1, "tablespoon": _TSP_PER_TBSP,
             "stick": _TSP_PER_STICK, "cup": _TSP_PER_CUP}

# Components of one recipe (Cake, Glaze, Filling), all of which get made.
GROUPS_ARE = "components"


def _parse_amount(text):
    """parse_amount() plus typed fractions ("1/3", "1 1/2"), which this
    book uses but Book on Pie's unicode-only format never needed."""
    m = _TYPED_FRACTION_RE.match(text.strip())
    if m:
        whole = int(m.group(1)) if m.group(1) else 0
        denominator = int(m.group(3))
        if denominator == 0:
            return None
        return whole + int(m.group(2)) / denominator
    return parse_amount(text)


def _canonical_unit(unit):
    """Collapse "cups"/"Tablespoons"/"tsp"/"sticks" etc. to one of the
    keys of _UNIT_TSP."""
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


def _to_tsp(amount, unit):
    """Convert a volume amount to teaspoons using exact integer ratios."""
    canonical = _canonical_unit(unit)
    if canonical is None or amount is None:
        return None
    return Fraction(amount).limit_denominator(1000) * _UNIT_TSP[canonical]


def parse_ingredient_line(line):
    """Parse one Dessert Person ingredient line. Returns the same dict
    shape as the Book on Pie parser so all downstream code (scaling,
    measurement display, exception flags) is shared unchanged.

    Volume amounts keep their ORIGINAL unit (cup stays cup) rather than
    being normalized to teaspoons, since measurement_display.py decides
    between cup-fraction and tbsp/tsp output based on that unit. A
    compound "3 tablespoons plus 1/3 cup" is summed exactly and expressed
    in the larger of its two units; its original wording is kept in
    "imperial_display" so the "before" side of a scaled ingredient shows
    what the book actually says, not "0.52 cup".
    """
    original = line.strip()
    if not original or _INSTRUCTION_RE.match(original):
        return None

    line = _FOOTNOTE_RE.sub("", original).strip()

    metric_amount = None
    m = _METRIC_PAREN_RE.search(line)
    if m:
        try:
            metric_amount = float(m.group(1).replace(",", ""))
        except ValueError:
            metric_amount = None
        line = (line[:m.start()] + line[m.end():])
        line = re.sub(r"\s+", " ", line).strip()
        line = re.sub(r"\s+,", ",", line)

    imperial_display = None
    compound = _COMPOUND_RE.match(line)
    if compound:
        amt1, unit1, amt2, unit2 = compound.groups()
        tsp1 = _to_tsp(_parse_amount(amt1), unit1)
        tsp2 = _to_tsp(_parse_amount(amt2), unit2)
        if tsp1 is None or tsp2 is None:
            return None
        imperial_unit = max(
            (_canonical_unit(unit1), _canonical_unit(unit2)),
            key=lambda u: _UNIT_TSP[u],
        )
        imperial_amount = float((tsp1 + tsp2) / _UNIT_TSP[imperial_unit])
        imperial_display = line[:compound.end()].strip()
        name = line[compound.end():].strip()
    else:
        single = _SINGLE_RE.match(line)
        if single:
            amt, unit = single.groups()
            imperial_amount = _parse_amount(amt)
            imperial_unit = _canonical_unit(unit)
            if imperial_amount is None:
                return None
            name = line[single.end():].strip()
        else:
            fallback = _COUNT_RE.match(line)
            if not fallback:
                return None
            imperial_amount = _parse_amount(fallback.group(1))
            if imperial_amount is None:
                return None
            imperial_unit = None
            name = line[fallback.end():].strip()

    return {
        "raw": original,
        "format": "dessert_person",
        "metric_amount": metric_amount,
        "metric_unit": "g" if metric_amount is not None else None,
        "imperial_amount": imperial_amount,
        "imperial_unit": imperial_unit,
        "imperial_display": imperial_display,
        "name": name,
    }


# Where the ingredient list starts: right after the yield line ("Makes 1
# round cake", or "Serves 8" for cakes and pies). Everything before it
# (title, the Season/Difficulty block, intro prose) is skipped, the
# metadata block in particular wraps unpredictably and can put a line
# like "20 minutes (for a parbaked crust) | ..." at the start of a
# line, which looks exactly like a count-only ingredient. Intro prose has
# to be skipped too: a sentence like "So here's my secret: A good crust..."
# has the same shape as STEP_RE and would end the list before it starts.
_YIELD_RE = re.compile(r"^(?:Makes|Serves)\b")
# Every instruction step in this book opens with a short bolded heading
# and a colon ("Make the glaze: In a small saucepan..."). The first
# one ends the ingredient list, so a wrapped instruction line that
# happens to start with a number ("½ inch apart, then bake...") is
# never mistaken for an ingredient. "Special Equipment:" has the same
# shape but sits before the ingredients, so it's skipped.
STEP_RE = re.compile(r"^[A-Z][^:]{2,80}:\s")
SKIP_RE = re.compile(r"^Special Equipment:", re.IGNORECASE)


def ingredient_start(lines):
    """Index of the first line that can be an ingredient: just after the
    "Makes"/"Serves" line, or, if a recipe has neither, just after the
    Difficulty line that ends its metadata block (searched only near the
    top, so a later mention of difficulty in prose doesn't count)."""
    for i, line in enumerate(lines):
        if _YIELD_RE.match(line.strip()):
            return i + 1
    for i, line in enumerate(lines[:8]):
        if DIFFICULTY_RE.search(line):
            return i + 1
    return 0


def _load_section_labels():
    """ALL-CAPS component labels (CAKE, GLAZE, FILLING, etc.), loaded from
    the book-specific word list so the list stays editable without
    touching this file."""
    data = load_book_specific("Dessert Person", "recipe_subsection_labels.json", {"labels": []})
    return {label.upper() for label in data.get("labels", [])}


def section_label(line):
    """A component label (CAKE, GLAZE, FILLING) starts a new ingredient
    group, returns its display name, or None."""
    label = line.upper()
    return label.title() if label in _load_section_labels() else None
