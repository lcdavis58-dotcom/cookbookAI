"""
Small text-parsing building blocks used across books and scripts: unicode
fraction amounts, and the ALL-CAPS line shape cookbooks use for titles
and section headers.
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
