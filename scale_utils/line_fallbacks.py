"""
Book-independent ways to read an ingredient line the book's own parser
rejected. Every book has the same few kinds of line that don't start
with a plain amount:

    Scant 1 g / ¼ teaspoon ground cloves             qualifier, then a normal line
    Pinch of fine sea salt                            pinch / dash as the amount
    One 2-inch / 5-cm piece fresh turmeric            amount spelled out
    Grated zest of 1 lime                             part of a counted ingredient
    Butter for the pan                                no amount at all

parse_fallback tries them in that order. Each result has the same shape
as a book parser's (see books/), plus two optional keys: "qualifier"
("scant", "about", "up to", ...), shown on both sides when scaling, and
"unmeasured" (True for a line with no amount, never scaled).
"""

import re

from common.text_parsing import FRACTION_CHARS, heading_text, parse_amount

# A word in front of a normal amount that hedges it. Scaling keeps the
# word and scales the amount ("scant 1 g" -> "scant 2 g").
_QUALIFIER_RE = re.compile(
    rf"^(scant|about|up to|generous|heaping|roughly|approximately)\s+(?=[\d{FRACTION_CHARS}])",
    re.IGNORECASE)

_PINCH_RE = re.compile(r"^(?:an?\s+)?(?:(small|large|generous|big|hefty)\s+)?(pinch|dash)(?:es)?"
                       r"\s+of\s+(.+)$", re.IGNORECASE)

# "A 2-inch / 5-cm piece fresh turmeric": one piece of that size.
_ARTICLE_COUNT_RE = re.compile(r"^an?\s+(?=\d)", re.IGNORECASE)

_FOOTNOTE_MARKS_RE = re.compile(r"\s*[①-⑳]+")

_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
}
_NUMBER_WORD_RE = re.compile(rf"^({'|'.join(_NUMBER_WORDS)})\b", re.IGNORECASE)

# "Grated zest of 1 lime", "Grated zest and juice of 1 lemon", "Seeds
# scraped from ½ vanilla bean": the amount counts the whole ingredient.
_PART_OF_RE = re.compile(
    rf"^(?P<part>.*?\b(?:zest|juice|seeds)\b.*?)\s+(?:of|from)\s+"
    rf"(?P<amt>\d+[{FRACTION_CHARS}]?|[{FRACTION_CHARS}])\s+(?P<rest>[A-Za-z].*)$",
    re.IGNORECASE)

# A line with no amount is only taken as an ingredient when it looks like
# one: short, starts with a capital, isn't a sentence or a heading.
UNMEASURED_MAX_CHARS = 80
# Private-use characters, which PDFs emit for glyphs in fonts they
# couldn't map ("Mak Ahea" for a decorative heading).
_PRIVATE_USE_RE = re.compile("[-]")


def _result(line, name, metric=None, metric_unit=None, imperial=None, imperial_unit=None, **extra):
    return {
        "raw": line,
        "format": "fallback",
        "metric_amount": metric,
        "metric_unit": metric_unit,
        "imperial_amount": imperial,
        "imperial_unit": imperial_unit,
        "name": name,
        **extra,
    }


def _looks_unmeasured(line):
    return (len(line) <= UNMEASURED_MAX_CHARS
            and line[:1].isupper()
            and not line.endswith(".")
            and ":" not in line
            and line.count("(") == line.count(")")
            # A heading, including ones with parentheses the ALL-CAPS
            # shape doesn't allow ("TANGERINE (OR ORANGE) CURD").
            and not heading_text(line) and line != line.upper()
            and not _PRIVATE_USE_RE.search(line))


def parse_fallback(line, parse):
    """Read a line the book's parser (parse) rejected, or return None."""
    line = line.strip()

    m = _QUALIFIER_RE.match(line)
    if m:
        parsed = parse(line[m.end():])
        if parsed:
            return {**parsed, "raw": line, "qualifier": m.group(1).lower()}

    m = _PINCH_RE.match(line)
    if m:
        # The size is part of the unit: "1 small pinch" -> "2 small pinches".
        size, unit, name = m.groups()
        unit = f"{size.lower()} {unit.lower()}" if size else unit.lower()
        return _result(line, name.strip(), imperial=1.0, imperial_unit=unit)

    m = _NUMBER_WORD_RE.match(line) or _ARTICLE_COUNT_RE.match(line)
    if m:
        number = _NUMBER_WORDS.get(m.group(1).lower(), "1") if m.groups() else "1"
        parsed = parse(f"{number} {line[m.end():].lstrip()}")
        if parsed:
            return {**parsed, "raw": line}

    m = _PART_OF_RE.match(line)
    if m:
        amount = parse_amount(m.group("amt"))
        if amount:
            rest = _FOOTNOTE_MARKS_RE.sub("", m.group("rest")).strip()
            return _result(line, f"{rest}, {m.group('part').strip().lower()}", imperial=amount)

    if _looks_unmeasured(line):
        return _result(line, line, unmeasured=True)
    return None
