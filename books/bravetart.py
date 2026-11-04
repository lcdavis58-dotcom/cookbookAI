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

from books.line_styles import PAGE_REF_RE, names_sub_recipe, volume_pipe_weight
from scale_utils.line_fallbacks import parse_fallback

# ---------------------------------------------------------------------------
# Settings (see books/engine.py)
# ---------------------------------------------------------------------------
# Titles and essay headings are 21pt or larger, body text 15, ingredient
# lists 11. Italic lines that size are asides inside a recipe ("Mix it
# up!", "Let's get crazy!"), never headings.
TITLE_MIN_SIZE = 21
YIELD_RE = re.compile(r"^YIELD:")
# The YIELD block: "YIELD: ... | ACTIVE TIME: ... | DOWNTIME: ...", wrapped
# at any point, so "ACTIVE" and "TIME:" can land on separate lines.
HEADER_FIELD_RE = re.compile(r"\b(?:TIME|DOWNTIME):")
INGREDIENTS_RIGHT_AFTER = True
parse_ingredient_line = volume_pipe_weight

# No numbered steps in this book; ingredient_end finds where the list
# stops instead, so STEP_RE never matches.
STEP_RE = re.compile(r"(?!)")


# ---------------------------------------------------------------------------
# Where the ingredient list ends, and its group labels (scale)
# ---------------------------------------------------------------------------
# "Cookies:", "Cinnamon Sugar:", "For the Filling:", "To finish:" and the
# step headings "Make the dough:", "Dust and bake the cookies:" all look
# like this; only what follows tells them apart.
_COLON_LINE_RE = re.compile(r"^[A-Z][^:|]{0,45}:$")
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
    return names_sub_recipe(line) or (parsed is not None and bool(_UNMEASURED_PURPOSE_RE.search(line)))


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
            and (len(line) <= UNMEASURED_MAX_CHARS or bool(PAGE_REF_RE.search(line))))


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
