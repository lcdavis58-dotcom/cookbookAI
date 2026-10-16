"""
Small text-parsing building blocks used across books and scripts: unicode
fraction amounts, the ALL-CAPS line shape cookbooks use for titles and
section headers, and telling a component label from a new section.
"""

import re

FRACTIONS = {
    "¼": 0.25, "½": 0.5, "¾": 0.75,
    "⅓": 1 / 3, "⅔": 2 / 3,
    "⅛": 0.125, "⅜": 0.375, "⅝": 0.625, "⅞": 0.875,
}
FRACTION_CHARS = "".join(FRACTIONS.keys())

# A short ALL-CAPS line (letters, digits, spaces, and a small set of
# punctuation): Book on Pie's recipe titles, and standalone section
# headers like 'PIE PEP TALK' in any book.
ALLCAPS_LINE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 ,\-'/’]{1,59}$")

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

    m = re.match(rf"^(\d+)?({'|'.join(re.escape(c) for c in FRACTIONS)})?$", text)
    if m and (m.group(1) or m.group(2)):
        whole = float(m.group(1)) if m.group(1) else 0.0
        frac = FRACTIONS[m.group(2)] if m.group(2) else 0.0
        return whole + frac

    try:
        return float(text)
    except ValueError:
        return None
