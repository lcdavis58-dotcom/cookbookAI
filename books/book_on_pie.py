"""
The Book On Pie: recipe-boundary detection, title extraction, and
ingredient parsing. See books/__init__.py for the interface every
book module provides.

Format, for reference:

    SPICED APPLE HAND PIES
    MAKES TWELVE 4-INCH / 10-CM HAND PIES | DIFFICULTY:
    EASY
    <intro prose>
    57 g / 2 ounces / 4 tablespoons unsalted butter, at room temperature
    67 g / ⅓ cup granulated sugar
    1. Preheat the oven to 400°F...
"""

import re

from common.text_parsing import ALLCAPS_LINE_RE, FRACTION_CHARS, parse_amount

# ---------------------------------------------------------------------------
# Recipe-boundary detection (ingest)
# ---------------------------------------------------------------------------
# A recipe title in this book is 1-2 short ALL-CAPS lines (letters, digits,
# spaces, and a small set of punctuation), immediately followed by a line
# starting with "MAKES". Subsections within a recipe (HALF BATCH, VARIATION,
# etc.) are also short ALL-CAPS lines, but are NOT followed by a MAKES line,
# which is exactly what lets us tell "new recipe" apart from "subsection of
# the current recipe."
MAKES_LINE_RE = re.compile(r"^MAKES\b")
DIFFICULTY_RE = re.compile(r"DIFFICULTY", re.IGNORECASE)
# The difficulty rating itself can land alone on its own line if the
# MAKES/DIFFICULTY text happens to wrap there (e.g. "...DIFFICULTY:" on one
# line, "EASY" on the next). Without accounting for this, that orphaned
# rating word gets mistaken for an unrelated section header, silently
# truncating the recipe right before its actual ingredients/instructions.
DIFFICULTY_WORD_RE = re.compile(r"^[A-Z]{2,15}$")


def find_recipe_starts(lines):
    """Return (start_line_indices, consumed_line_indices) for every
    detected recipe title. consumed_line_indices covers every line that's
    part of a title block, its MAKES/DIFFICULTY line(s), and a possible
    wrapped difficulty rating, this is used downstream to stop the
    section-header detector from getting confused by any of those, which
    would otherwise look like a standalone header and wrongly split the
    recipe apart from its own body text.
    """
    starts = []
    consumed = set()
    i, n = 0, len(lines)
    while i < n:
        stripped = lines[i].strip()
        if stripped and ALLCAPS_LINE_RE.match(stripped):
            title_end = i
            j = i + 1
            title_lines_seen = 1
            while j < n and title_lines_seen < 2:
                nxt = lines[j].strip()
                if not nxt:
                    j += 1
                    continue
                if ALLCAPS_LINE_RE.match(nxt):
                    title_end = j
                    title_lines_seen += 1
                    j += 1
                else:
                    break

            k = title_end + 1
            while k < n and not lines[k].strip():
                k += 1
            if k < n and MAKES_LINE_RE.match(lines[k].strip()):
                starts.append(i)
                end = k

                # The MAKES line usually contains "DIFFICULTY" itself, but
                # if the yield text is long it can wrap, search a few lines
                # ahead for wherever "DIFFICULTY" actually lands.
                if not DIFFICULTY_RE.search(lines[k]):
                    for lookahead in range(k + 1, min(k + 4, n)):
                        if DIFFICULTY_RE.search(lines[lookahead]):
                            end = lookahead
                            break

                # If the difficulty RATING itself wrapped onto its own line
                # (e.g. "EASY" alone right after "...DIFFICULTY:"), consume
                # that line too so it doesn't get mistaken for a new
                # section header.
                nxt_idx = end + 1
                if nxt_idx < n:
                    nxt_stripped = lines[nxt_idx].strip()
                    if nxt_stripped and DIFFICULTY_WORD_RE.match(nxt_stripped):
                        end = nxt_idx

                for idx in range(i, end + 1):
                    consumed.add(idx)
                i = end
        i += 1
    return starts, consumed


# ---------------------------------------------------------------------------
# Title extraction (query/scale)
# ---------------------------------------------------------------------------

def extract_title(text, include_subtitle=True):
    """The same ALL-CAPS-lines-before-a-non-title-line logic used during
    ingestion. Stops as soon as it hits a line that isn't part of the
    title (typically the MAKES line). This book has no separate subtitle
    line, so include_subtitle has no effect."""
    title_lines = []
    for line in text.splitlines()[:3]:
        stripped = line.strip()
        if stripped and ALLCAPS_LINE_RE.match(stripped):
            title_lines.append(stripped)
        else:
            break
    return " ".join(title_lines)


# ---------------------------------------------------------------------------
# Ingredient parsing (scale)
# ---------------------------------------------------------------------------
# Deliberately has nothing to do with the LLM, the format this book uses
# ("245 g / 1 cup whole milk") is consistent enough that a regex parses it
# reliably, which is a stronger guarantee than trusting a small model to
# transcribe numbers correctly.

# A numbered instruction step ("1. Whip the cream...") has a period right
# after the leading number, an ingredient amount never does ("235 g...").
# Checking this first avoids misreading instructions as ingredients.
STEP_RE = re.compile(r"^\d+\.\s")
SKIP_RE = None

# The common case: metric amount + unit, a slash, then imperial amount +
# unit, then the ingredient name. Imperial amount/unit are optional since
# a few lines only give a count (e.g. "50 g / 1 large egg"). Some
# lines give TWO imperial measures ("57 g / 2 ounces / 4 tablespoons
# unsalted butter"), the optional imp2 group catches the second one so it
# doesn't end up glued to the front of the ingredient name.
_IMP_UNIT = r"(?:packed\s+cups?|cups?|tablespoons?|tbsp|teaspoons?|tsp|ounces?|oz)\b"
INGREDIENT_LINE_RE = re.compile(
    rf"^(?P<metric_amt>[\d{FRACTION_CHARS}]+)\s*(?P<metric_unit>g|kg|ml|l)\s*/\s*"
    rf"(?P<imp_amt>[\d{FRACTION_CHARS}]+)?\s*"
    rf"(?P<imp_unit>{_IMP_UNIT})?\s*"
    rf"(?:/\s*(?P<imp2_amt>[\d{FRACTION_CHARS}]+)\s*(?P<imp2_unit>{_IMP_UNIT})\s*)?"
    rf"(?P<name>.+)$",
    re.IGNORECASE,
)
_VOLUME_UNIT_RE = re.compile(r"cup|tablespoon|tbsp|teaspoon|tsp", re.IGNORECASE)

# Fallback for lines with no metric/imperial split, just a bare count,
# e.g. "3 garlic cloves" or "2 large eggs".
FALLBACK_LINE_RE = re.compile(rf"^(?P<amt>[\d{FRACTION_CHARS}]+)\s+(?P<name>.+)$")

# Batch-size subsections in this book are short ALL-CAPS labels ending in
# "BATCH" (HALF BATCH, FULL BATCH, MILE-HIGH BATCH). Matching the pattern
# rather than an exact list catches variants we haven't seen yet, without
# also catching unrelated subsections like VARIATION or NOTE.
BATCH_LABEL_RE = re.compile(r"^[A-Z][A-Z\- ]*\bBATCH$")

# Batches are alternative sizes of the same recipe, only one gets made.
GROUPS_ARE = "batches"


def parse_ingredient_line(line):
    """Parse one line of text as an ingredient, or return None if it
    doesn't look like one (e.g. it's an instruction step, a title, or
    ordinary prose).
    """
    line = line.strip()
    if not line or STEP_RE.match(line):
        return None

    m = INGREDIENT_LINE_RE.match(line)
    if m:
        imp_amt, imp_unit = m.group("imp_amt"), m.group("imp_unit")
        # With two imperial measures, keep the volume one (8 tablespoons
        # over 4 ounces): measurement_display.py can break a scaled volume
        # into real measuring tools, a scaled weight it can only round.
        if m.group("imp2_unit") and _VOLUME_UNIT_RE.search(m.group("imp2_unit")) \
                and not _VOLUME_UNIT_RE.search(imp_unit or ""):
            imp_amt, imp_unit = m.group("imp2_amt"), m.group("imp2_unit")
        return {
            "raw": line,
            "format": "metric_imperial",
            "metric_amount": parse_amount(m.group("metric_amt")),
            "metric_unit": m.group("metric_unit"),
            "imperial_amount": parse_amount(imp_amt) if imp_amt else None,
            "imperial_unit": imp_unit,
            "name": m.group("name").strip(),
        }

    m = FALLBACK_LINE_RE.match(line)
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


def ingredient_start(lines):
    """This book has no "Makes" line to anchor on (its yield is the
    ALL-CAPS MAKES ... | DIFFICULTY header, which can wrap) and the intro
    prose sits between that header and the ingredients. Its ingredient
    lines are very regular though, every one starts "<n> g /", so the
    block starts at the first such line, or at a batch label like HALF
    BATCH, which comes just before its own ingredients."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if BATCH_LABEL_RE.match(stripped) or INGREDIENT_LINE_RE.match(stripped):
            return i
    return len(lines)


def section_label(line):
    """HALF BATCH / FULL BATCH / MILE-HIGH BATCH start a new group."""
    return line.title() if BATCH_LABEL_RE.match(line) else None

