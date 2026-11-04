"""
BraveTart (Stella Parks): recipe-boundary detection from type size,
title extraction, and ingredient parsing. See books/__init__.py for the
interface every book module provides.

Format, for reference (sizes in points, as extracted):

    CHOPPED CHOCOLATE CHIP          25, ALL-CAPS, can wrap; a component
    COOKIES                         recipe has a 21pt Title Case title
                                    ("Sliced Summer Strawberries")
    <intro prose>                   15
    YIELD: thirteen 5-inch cookies | ACTIVE TIME: 30     11, wraps anywhere
    minutes
    Cookies:                        11 italic, a group label
    2⅓ cups | 10½ ounces all-purpose flour, such as Gold Medal
    1¼ teaspoons Diamond Crystal kosher salt (half as much if iodized)
    1 large egg, straight from the fridge
    Make the dough:                 15 bold, a step heading (some recipes
    Adjust oven rack to...          go straight into the steps)
    TROUBLESHOOTING / MAKE AHEAD    15 bold asides
    Mix it up!                      21 italic, variations follow

Most dessert chapters open with an essay set like a recipe title, often
with the same name ("SNICKERDOODLES"), but no YIELD line follows it
before the next heading, so it becomes an "other" chunk. Some pages are
scaled about 1% smaller (24.7 / 14.8 / 11.1), so sizes are compared
against thresholds, never exact values.
"""

import re

from common.text_parsing import (AMOUNT, UNIT_TSP, canonical_volume_unit,
                                 parse_typed_amount, volume_to_tsp)
from scale_utils.line_fallbacks import parse_fallback

# ---------------------------------------------------------------------------
# Recipe-boundary detection (ingest)
# ---------------------------------------------------------------------------
# Titles and essay headings are 21pt or larger, body text 15, ingredient
# lists 11. Italic lines that size are asides inside a recipe ("Mix it
# up!", "Let's get crazy!"), never headings.
HEADING_MIN_SIZE = 20
YIELD_RE = re.compile(r"^YIELD:")


def _is_heading(record):
    return record["size"] >= HEADING_MIN_SIZE and not record["italic"] and record["text"].strip()


def _headings(layout):
    """[(first, last)] line ranges of every heading; one heading's lines
    are consecutive heading-size lines on the same page."""
    ranges = []
    i = 0
    while i < len(layout):
        if _is_heading(layout[i]):
            j = i
            while (j + 1 < len(layout) and _is_heading(layout[j + 1])
                   and layout[j + 1]["page"] == layout[i]["page"]):
                j += 1
            ranges.append((i, j))
            i = j + 1
        else:
            i += 1
    return ranges


def find_recipe_starts(lines, layout=None):
    """Return (start_line_indices, consumed_line_indices). A recipe
    starts at a heading with a YIELD line after it and before the next
    heading. consumed covers its title and the YIELD block, so neither is
    read as a section of its own."""
    if layout is None:
        raise ValueError("BraveTart's recipes are found by type size, so it needs the layout")
    headings = _headings(layout)
    starts, consumed = [], set()
    for n, (first, last) in enumerate(headings):
        next_heading = headings[n + 1][0] if n + 1 < len(headings) else len(lines)
        yield_at = next((k for k in range(last + 1, next_heading) if YIELD_RE.match(lines[k].strip())), None)
        if yield_at is None:
            continue
        starts.append(first)
        consumed.update(range(first, last + 1))
        consumed.update(range(yield_at, yield_at + _yield_block_length(lines, yield_at)))
    return starts, consumed


def find_section_starts(lines, layout, consumed):
    """Every heading that doesn't start a recipe (an essay, a chapter
    opener, "SO WHY WEIGHT?") starts an "other" chunk. Headings are told
    by size, so ALL-CAPS lines inside a recipe (TROUBLESHOOTING) and
    headings with "?" or "®" in them need no special cases."""
    return [first for first, _ in _headings(layout) if first not in consumed]


# ---------------------------------------------------------------------------
# Title extraction (query/scale)
# ---------------------------------------------------------------------------

def _is_caps(line):
    return bool(line) and line == line.upper() and any(c.isalpha() for c in line)


def extract_title(text, include_subtitle=True):
    """A chunk that starts a recipe begins with its title: one or more
    ALL-CAPS lines, or a single Title Case line for a component recipe
    (every wrapped title in the book is ALL-CAPS). include_subtitle=False
    drops a "WITH ..." tail, so "LEMON MERINGUE PIE WITH MARSHMALLOW
    MERINGUE" matches as "LEMON MERINGUE PIE"."""
    lines = [line.strip() for line in text.splitlines()[:5] if line.strip()]
    if not lines:
        return ""
    if not _is_caps(lines[0]):
        title = lines[0]
    else:
        title_lines = []
        for line in lines:
            if not _is_caps(line) or YIELD_RE.match(line):
                break
            title_lines.append(line)
        title = " ".join(title_lines)
    if not include_subtitle:
        title = re.split(r"\s+WITH\s+", title, maxsplit=1)[0]
    return title


# ---------------------------------------------------------------------------
# Ingredient parsing (scale)
# ---------------------------------------------------------------------------
# Volume first, then weight in ounces, split by "|":
#     2⅓ cups | 10½ ounces all-purpose flour
#     1 cup plus 2 tablespoons | 8 ounces sugar
#     ¼ cup packed | 2 ounces light brown sugar
#     6 heaping cups | 2 pounds whole ripe strawberries
#     ½ to ¾ cup | 3 to 5 ounces sugar
# or a volume alone ("1 tablespoon vanilla extract"), a weight alone, or
# a count ("1 large egg", "½ recipe (2 cups | 8 ounces) Make-Ahead
# Whipped Cream (page 89)"). There are no grams anywhere, so the weight
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
_COUNT_RE = re.compile(rf"^(?P<amt>{AMOUNT})\s+(?P<name>(?:[A-Za-z(“\"]|\d+-).*)$")

# No numbered steps in this book; ingredient_end finds where the list
# stops instead, so STEP_RE never matches.
STEP_RE = re.compile(r"(?!)")
SKIP_RE = None
# Every group ("Cookies:", "Cinnamon Sugar:", "For the Filling:") is a
# component that always gets made, there are no alternative batch sizes.
BATCH_LABEL_RE = None


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
    unit; a range ("½ to ¾ cup") scales from its low end. The display is
    always the book's own wording ("2⅓ cups", "¼ cup packed"), for the
    unscaled side."""
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


def _result(raw, name, weight=None, weight_unit=None, volume=None):
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


def parse_ingredient_line(line):
    """Parse one BraveTart ingredient line, or return None. Same dict
    shape as the other books' parsers."""
    line = line.strip()
    if not line:
        return None

    # "Shy ½ teaspoon": just under the amount, the same as "scant".
    if line.lower().startswith("shy "):
        parsed = parse_ingredient_line(line[4:])
        return {**parsed, "raw": line, "qualifier": "scant"} if parsed else None

    sides = _split_pipe(line)
    if sides:
        volume_m = _VOLUME_RE.match(sides[0])
        weight_m = _WEIGHT_RE.match(sides[1])
        if volume_m and weight_m and weight_m.group("name"):
            volume = _volume(volume_m)
            if volume:
                return _result(line, weight_m.group("name"), parse_typed_amount(weight_m.group("amt")),
                               _weight_unit(weight_m.group("unit")), volume)
        return None

    m = _VOLUME_NAME_RE.match(line)
    if m:
        volume = _volume(m)
        if volume:
            return _result(line, m.group("name"), volume=volume)
    m = _WEIGHT_RE.match(line)
    if m and m.group("name"):
        return _result(line, m.group("name"), parse_typed_amount(m.group("amt")), _weight_unit(m.group("unit")))
    m = _COUNT_RE.match(line)
    if m:
        amount = parse_typed_amount(m.group("amt"))
        if amount is not None:
            return {**_result(line, m.group("name")), "format": "count_only", "imperial_amount": amount}
    # Other recipes offered with no amount, too long for the shared
    # fallback: "Powdered or granulated sugar or Cinnamon Sugar (page 44)
    # or Vanilla Sugar Sprinkle (page 46), to taste".
    if _names_sub_recipe(line) and line[:1].isupper():
        return {**_result(line, line), "format": "fallback", "unmeasured": True}
    return None


# The YIELD block: "YIELD: ... | ACTIVE TIME: ... | DOWNTIME: ...", wrapped
# at any point, so its later lines can be "minutes", "| DOWNTIME: 2 hours",
# "refrigeration, plus 1 hour to cool" or "cupcakes | ACTIVE TIME: 1 hour".
# "ACTIVE" and "TIME:" can land on separate lines.
_YIELD_FIELD_RE = re.compile(r"\b(?:TIME|DOWNTIME):|^\|")


def _yield_block_length(lines, i):
    """How many lines the YIELD block starting at lines[i] takes up: it
    goes on while the next line carries one of its fields, continues a
    lowercase fragment, or finishes something left hanging ("plus 30-")."""
    n = 1
    while i + n < len(lines):
        line = lines[i + n].strip()
        prev = lines[i + n - 1].rstrip()
        if not line:
            break
        if (_YIELD_FIELD_RE.search(line) or line[:1].islower()
                or re.search(r"(?:-|\bto|\bplus|,|\(|:|ACTIVE)$", prev)):
            n += 1
            continue
        break
    return n


def ingredient_start(lines):
    """The line after the YIELD block, or the end of the chunk if it has
    none (a later part of a split recipe, which never has ingredients)."""
    for i, line in enumerate(lines):
        if YIELD_RE.match(line.strip()):
            return i + _yield_block_length(lines, i)
    return len(lines)


# "Cookies:", "Cinnamon Sugar:", "For the Filling:", "To finish:" and the
# step headings "Make the dough:", "Dust and bake the cookies:" all look
# like this; only what follows tells them apart.
_COLON_LINE_RE = re.compile(r"^[A-Z][^:|]{0,45}:$")
# A sub-recipe line can have no amount: "Caramelized White Chocolate
# (page 60)", "Vanilla Variation (pages 335-37)".
_PAGE_REF_RE = re.compile(r"\bpages? \d+")
# "About six 7-inch carrots": a hedge in front of a spelled-out count.
_HEDGED_WORD_COUNT_RE = re.compile(r"^(?:about|roughly)\s+(?=[a-z]+\s)", re.IGNORECASE)
# An unmeasured line that says what it's for or that it's optional
# ("Powdered sugar, for dusting").
_UNMEASURED_PURPOSE_RE = re.compile(r",\s*(?:for|to)\b|\(optional\)", re.IGNORECASE)
# Ingredient lines only wrap once they fill the column, about 78
# characters; a shorter line is never followed by its own wrap.
WRAP_WIDTH = 75
# A plain unmeasured line ("Assorted extracts") is short, and so is a
# step heading without a colon ("Make the marshmallow base").
UNMEASURED_MAX_CHARS = 50


def _names_sub_recipe(line):
    """A line naming another recipe by page. A step can mention a page
    too ("Temper chocolate according to the directions on pages
    292-93."), but it's a sentence."""
    return bool(_PAGE_REF_RE.search(line)) and not re.search(r"\.(?:\s|$)", line)


def _is_ingredient(line):
    """Whether a line reads as an ingredient on its own: it parses, or a
    fallback reads an amount from it, or it names a sub-recipe or what
    an unmeasured ingredient is for."""
    if parse_ingredient_line(line):
        return True
    line = _HEDGED_WORD_COUNT_RE.sub("", line)
    parsed = parse_fallback(line, parse_ingredient_line)
    if parsed and not parsed.get("unmeasured"):
        return True
    return _names_sub_recipe(line) or (parsed is not None and bool(_UNMEASURED_PURPOSE_RE.search(line)))


def _is_short_unmeasured(line):
    parsed = parse_fallback(line, parse_ingredient_line)
    return parsed is not None and parsed.get("unmeasured") and len(line) <= UNMEASURED_MAX_CHARS


def is_continuation(pending, last_line, line):
    """Whether line is the wrap of the ingredient line before it: the
    shared signals (scale_utils/ingredients.py) plus the ones this book
    needs, a line left hanging ("and/or", "plus more for") or one that
    filled the column ("such as Cacao Barry" / "Extra Brute"), as long as
    the line doesn't start an ingredient of its own. After a full line,
    a capitalized one is only a wrap when it's short or names a page; the
    first line of a step runs the width of the column too."""
    if _COLON_LINE_RE.match(line) or parse_ingredient_line(line):
        return False
    if (pending.count("(") > pending.count(")") or line[:1].islower() or line[:1] in "(|"
            or re.search(r"(?:-|\bor|\band|\bplus|\bfor|,)$", pending)):
        return True
    return (len(last_line) >= WRAP_WIDTH and not _is_ingredient(line)
            and (len(line) <= UNMEASURED_MAX_CHARS or bool(_PAGE_REF_RE.search(line))))


def ingredient_end(lines, start):
    """Where the steps begin: the first line from start that isn't an
    ingredient, the wrap of one, or a group label. A "Something:" line is
    a label when an ingredient follows it and a step heading otherwise.
    Short unmeasured lines ("Assorted extracts") count when what comes
    after them is still the list, which a step heading's prose isn't."""
    nonblank = [i for i in range(start, len(lines)) if lines[i].strip()]

    def ends_list_at(n):
        """Whether nonblank[n] is past the list (None past the end)."""
        if n >= len(nonblank):
            return False
        line = lines[nonblank[n]].strip()
        if _COLON_LINE_RE.match(line) or _is_ingredient(line):
            return False
        if _is_short_unmeasured(line):
            return ends_list_at(n + 1)
        return True

    pending = last = None  # the ingredient so far, and its last line
    for n, i in enumerate(nonblank):
        line = lines[i].strip()
        if _COLON_LINE_RE.match(line):
            following = lines[nonblank[n + 1]].strip() if n + 1 < len(nonblank) else ""
            if following and (_is_ingredient(following) or _is_short_unmeasured(following)):
                pending = last = None
                continue
            return i
        if pending is not None and is_continuation(pending, last, line):
            pending = f"{pending} {line}"
            last = line
            continue
        if _is_ingredient(line) or (_is_short_unmeasured(line) and not ends_list_at(n + 1)):
            pending = last = line
            continue
        return i
    return len(lines)


def section_label(line):
    """A group label ("Cookies:", "For the Filling:") as the group's
    name, without the colon or a leading "For the"."""
    if not _COLON_LINE_RE.match(line):
        return None
    return re.sub(r"^For the\s+", "", line[:-1].strip(), flags=re.IGNORECASE)
