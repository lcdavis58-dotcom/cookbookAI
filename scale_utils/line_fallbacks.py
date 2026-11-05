"""
Book-independent ways to read an ingredient line the book's own parser
rejected. Every book has the same few kinds of line that don't start
with a plain amount:

    Scant 1 g / ¼ teaspoon ground cloves             qualifier, then a normal line
    Pinch of fine sea salt                            pinch / dash as the amount
    One 2-inch / 5-cm piece fresh turmeric            amount spelled out
    ½-inch piece fresh ginger                         a size, no count
    Grated zest of 1 lime                             part of a counted ingredient
    Egg wash: 57 g / 1 large egg, beaten with ...     a name, then a normal line
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
    rf"^(scant|about|up to|generous|heaping|roughly|approximately|a pinch plus|<)\s*(?=[\d{FRACTION_CHARS}])",
    re.IGNORECASE)

_PINCH_RE = re.compile(r"^(?:an?\s+)?(?:(small|large|generous|big|hefty)\s+)?(pinch|dash)(?:es)?"
                       r"\s+of\s+(.+)$", re.IGNORECASE)

# "A 2-inch / 5-cm piece fresh turmeric": one piece of that size.
_ARTICLE_COUNT_RE = re.compile(r"^an?\s+(?=\d)", re.IGNORECASE)
# "½-inch piece fresh ginger": a size with no count, read as one piece
# ("1 (½-inch) piece fresh ginger"), so it scales to "2 (½-inch) ...".
_SIZE_FIRST_RE = re.compile(rf"^([\d{FRACTION_CHARS}]+-inch)\s+(?=pieces?\b)", re.IGNORECASE)

_FOOTNOTE_MARKS_RE = re.compile(r"\s*[①-⑳]+")

# "Egg wash: 57 g / 1 large egg, beaten with 15 g / 1 tablespoon water":
# what it makes, then its main ingredient's amount. Read as that many of
# the named thing ("Egg wash"), the rest kept in raw.
_NAMED_AMOUNT_RE = re.compile(rf"^(?P<label>[A-Z][A-Za-z’' -]{{1,30}}):\s+(?=[\d{FRACTION_CHARS}])")

_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
}
# An item's size: "3-inch", "12- to 16-pound", "28-ounce".
_SIZE_RE = re.compile(rf"^[\d{FRACTION_CHARS}./]+-?(?:\s*to\s*[\d{FRACTION_CHARS}./]+)?\s?-(?:inch|pound|ounce|quart)\b",
                      re.IGNORECASE)
# A count in digits before a size: "1 2-pound salmon filet", "2 1-inch
# strips of lemon zest".
_DIGIT_COUNT_RE = re.compile(r"^(\d+)\s+(?=\d)")
_CUT_SHAPE_RE = re.compile(
    r"(?:-(?:thick|wide|long)\b|\s*/|\s+(?:dice|cubes?|chunks?|pieces?|slices?|rounds?|"
    r"strips?|matchsticks?|lengths?|thick|wide|long|rectangles?|squares?)\b(?!\s+of\b))", re.IGNORECASE)
# "Optional: 1-ounce chunk of Parmesan": the rest is the ingredient.
_OPTIONAL_PREFIX_RE = re.compile(r"^optional:\s*", re.IGNORECASE)
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
_WEB_ADDRESS_RE = re.compile(r"\S+\.(?:com|net|org)", re.IGNORECASE)
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
            and not _PRIVATE_USE_RE.search(line)
            # A page footer the PDF carries ("OceanofPDF.com").
            and not _WEB_ADDRESS_RE.fullmatch(line))


def parse_fallback(line, parse):
    """Read a line the book's parser (parse) rejected, or return None."""
    line = line.strip()

    m = _OPTIONAL_PREFIX_RE.match(line)
    if m and line[m.end():]:
        rest = line[m.end():]
        parsed = parse(rest) or parse_fallback(rest, parse)
        if parsed:
            # The name carries the word, so matching treats it as optional.
            return {**parsed, "raw": line, "name": f"{parsed['name']} (optional)"}

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
        rest = line[m.end():].lstrip()
        parsed = parse(f"{number} {rest}")
        if parsed:
            return {**parsed, "raw": line}
        # "One 12- to 16-pound (5.4 to 7.3kg) turkey": a count, then the
        # item's size, which no book parser reads after a number.
        if _SIZE_RE.match(rest):
            return _result(line, rest, imperial=float(number))

    m = _SIZE_FIRST_RE.match(line)
    if m:
        parsed = parse(f"1 ({m.group(1)}) {line[m.end():]}")
        if parsed:
            return {**parsed, "raw": line}

    # "1 2-pound salmon filet": a digit count, then the item's size.
    m = _DIGIT_COUNT_RE.match(line)
    if m and _SIZE_RE.match(line[m.end():]):
        return _result(line, line[m.end():], imperial=float(m.group(1)))
    # "4-pound chicken", "1-inch knob of ginger": a size, so one of them.
    # Not the wrapped end of a cutting note ("cut into" / "1/2-inch dice",
    # "1-inch / 2.5-cm-thick rectangle").
    m = _SIZE_RE.match(line)
    if m and not _CUT_SHAPE_RE.match(line[m.end():]):
        return _result(line, line, imperial=1.0)

    m = _NAMED_AMOUNT_RE.match(line)
    if m:
        parsed = parse(line[m.end():])
        if parsed:
            return {**parsed, "raw": line, "name": m.group("label")}

    m = _PART_OF_RE.match(line)
    if m:
        amount = parse_amount(m.group("amt"))
        if amount:
            rest = _FOOTNOTE_MARKS_RE.sub("", m.group("rest")).strip()
            return _result(line, f"{rest}, {m.group('part').strip().lower()}", imperial=amount)

    if _looks_unmeasured(line):
        return _result(line, line, unmeasured=True)
    return None
