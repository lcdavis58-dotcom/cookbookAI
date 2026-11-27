"""
Checks on an answer the model wrote from book excerpts (actions/ask.py),
before it's shown (1.2.1). The model is told to quote amounts exactly
and cite only the books and pages it was given; these check that it did:

    quantity    every number in the answer, with its unit when it has
                one ("3 cups", "350°F", "12 minutes"), is in one of the
                excerpts (or in her question). ½ and 1/2 and 0.5 are the
                same number. Numbers written as words ("two eggs") and
                list numbers at the start of a line aren't checked.
    page        every page cited ("page 112", "p. 112") is a confirmed
                page of one of the excerpts.
    book        every book of the library named in the answer is one
                the excerpts came from.

A problem is a dict {"kind", "what"}, so it can be saved with the
reply's model call (common/models.CALLS) and counted by tools/metrics.py.
"""

import re

from books import RECIPE_AWARE_BOOKS

_FRACTIONS = {"½": 1 / 2, "⅓": 1 / 3, "⅔": 2 / 3, "¼": 1 / 4, "¾": 3 / 4, "⅕": 1 / 5, "⅖": 2 / 5, "⅗": 3 / 5,
              "⅘": 4 / 5, "⅙": 1 / 6, "⅚": 5 / 6, "⅛": 1 / 8, "⅜": 3 / 8, "⅝": 5 / 8, "⅞": 7 / 8}
_GLYPHS = "".join(_FRACTIONS)

# A number: "1½", "1 ½", "½", "1 1/2", "1-1/2", "1/2", "2.5", "350".
# Not inside a word or a longer number ("x2", "1.5.3").
_NUMBER_RE = re.compile(
    rf"(?<![\w./])(?:(?P<whole>\d+)[ -]?)?(?P<glyph>[{_GLYPHS}])"
    rf"|(?<![\w./])(?P<mixed>\d+)[ -](?P<mnum>\d+)/(?P<mden>\d+)(?![\w/])"
    rf"|(?<![\w./])(?P<num>\d+)/(?P<den>\d+)(?![\w/])"
    rf"|(?<![\w./])(?P<plain>\d+(?:\.\d+)?)(?![\d{_GLYPHS}])"
)
# What can follow a number as its unit, by the name it's compared under.
_UNITS = {
    # Not "c" (cup or Celsius?) or "in" ("add 2 in the bowl").
    "cup": ("cup", "cups"),
    "tbsp": ("tablespoon", "tablespoons", "tbsp", "tbs", "tbsps"),
    "tsp": ("teaspoon", "teaspoons", "tsp", "tsps"),
    "g": ("g", "gram", "grams", "gr"),
    "kg": ("kg", "kilogram", "kilograms"),
    "ml": ("ml", "milliliter", "milliliters", "millilitre", "millilitres"),
    "l": ("l", "liter", "liters", "litre", "litres"),
    "oz": ("oz", "ounce", "ounces"),
    "lb": ("lb", "lbs", "pound", "pounds"),
    "qt": ("quart", "quarts", "qt"),
    "pt": ("pint", "pints", "pt"),
    "stick": ("stick", "sticks"),
    "inch": ("inch", "inches", '"'),
    "min": ("minute", "minutes", "min", "mins"),
    "hr": ("hour", "hours", "hr", "hrs"),
    "sec": ("second", "seconds", "sec", "secs"),
    "degf": ("°f", "°", "degrees", "degree", "f", "ºf", "º"),
    "degc": ("°c", "c°", "ºc"),
    "%": ("%", "percent"),
}
_UNIT_OF = {alias: unit for unit, aliases in _UNITS.items() for alias in aliases}
_UNIT_RE = re.compile(r"[\s-]?(°\s?[fc]\b|º\s?[fc]?\b|°|%|\"|[a-z]+\b)", re.I)
# Between the two ends of a range: "12 to 14 minutes", "2-3 cups".
_RANGE_RE = re.compile(r"\s*(?:to|-|–|—|or|and)\s*$", re.I)
# "1." or "2)" opening a line: a numbered list, not an amount.
_LIST_NUMBER_RE = re.compile(r"^\s*\d+[.)]\s", re.M)
# How a book's name is written, where str.title() gets it wrong.
_BOOK_NAMES = {"bravetart": "BraveTart"}
_PAGE_RE = re.compile(r"\b(?:pages?|pg\.?|p\.)\s*(\d+)", re.I)


def _value(m):
    if m.group("glyph"):
        return int(m.group("whole") or 0) + _FRACTIONS[m.group("glyph")]
    if m.group("mixed"):
        den = int(m.group("mden"))
        return int(m.group("mixed")) + int(m.group("mnum")) / den if den else None
    if m.group("num"):
        den = int(m.group("den"))
        return int(m.group("num")) / den if den else None
    return float(m.group("plain"))


def _unit_after(text, end):
    """(the unit after a number, where it ends), or (None, end)."""
    m = _UNIT_RE.match(text, end)
    unit = _UNIT_OF.get(re.sub(r"\s", "", m.group(1).lower())) if m else None
    return (unit, m.end()) if unit else (None, end)


def quantities(text, skip_lists=True):
    """[(value, unit or None, as written with its unit)] for every number in text, page
    numbers left out, and list numbers too unless skip_lists is False.
    The first end of a range takes the unit of the second ("12 to 14
    minutes" is 12 minutes and 14 minutes)."""
    skip = {m.start(1) for m in _PAGE_RE.finditer(text)}
    if skip_lists:
        skip |= {m.start() + len(m.group()) - len(m.group().lstrip()) for m in _LIST_NUMBER_RE.finditer(text)}
    found = []
    for m in _NUMBER_RE.finditer(text):
        if m.start() in skip:
            continue
        value = _value(m)
        if value is None:
            continue
        unit, end = _unit_after(text, m.end())
        found.append([round(value, 3), unit, text[m.start():end].strip(), m.start(), m.end()])
    for first, second in zip(reversed(found[:-1]), reversed(found[1:])):
        if first[1] is None and second[1] and _RANGE_RE.match(text[first[4]:second[3]]):
            first[1] = second[1]
    return [(value, unit, written) for value, unit, written, _, _ in found]


def _book_named(answer, book):
    """Whether the answer names a library book. Ratio is also a word,
    so it counts only capitalized and not starting a sentence."""
    if book == "ratio":
        return bool(re.search(r"(?<![.!?\n]\s)(?<!^)\bRatio\b", answer))
    return re.search(rf"\b{re.escape(book)}\b", answer.lower().replace("’", "'")) is not None


def check(answer, sources, question=""):
    """The problems with an answer, as [{"kind", "what"}], [] when it
    passes. sources: the excerpts it was given ({"book", "page",
    "page_confirmed", "text"}, actions/ask.py)."""
    problems = []
    source_text = "\n".join(s.get("text", "") for s in sources) + "\n" + question
    have = quantities(source_text, skip_lists=False)
    values = {v for v, _, _ in have}
    pairs = {(v, u) for v, u, _ in have if u}
    seen = set()
    for value, unit, written in quantities(answer):
        ok = (value, unit) in pairs if unit else value in values
        if not ok and written not in seen:
            seen.add(written)
            problems.append({"kind": "quantity", "what": written})

    pages = {int(s["page"]) for s in sources if s.get("page_confirmed")}
    for m in _PAGE_RE.finditer(answer):
        page = int(m.group(1))
        if page not in pages and f"page {page}" not in seen:
            seen.add(f"page {page}")
            problems.append({"kind": "page", "what": f"page {page}"})

    given = {s["book"].lower().replace("’", "'") for s in sources}
    for book in RECIPE_AWARE_BOOKS:
        if book not in given and _book_named(answer, book):
            problems.append({"kind": "book", "what": _BOOK_NAMES.get(book, book.title())})
    return problems


def for_the_model(problems):
    """What to tell the model when asking it to answer again."""
    lines = []
    for p in problems:
        if p["kind"] == "quantity":
            lines.append(f"- {p['what']} is not in the excerpts. Quote amounts exactly as the excerpts write "
                         f"them, or leave them out.")
        elif p["kind"] == "page":
            lines.append(f"- {p['what']} is not a page of any excerpt. Cite only pages given as numbers.")
        else:
            lines.append(f"- {p['what']} is not one of the books the excerpts came from. Cite only those books.")
    return ("Your answer has these problems:\n" + "\n".join(lines)
            + "\nAnswer the question again, using only the excerpts.")


def for_her(problems):
    """The note shown under an answer that still has problems after it
    was asked again."""
    amounts = [p["what"] for p in problems if p["kind"] == "quantity"]
    cited = [p["what"] for p in problems if p["kind"] != "quantity"]
    parts = []
    if amounts:
        parts.append(f"I couldn't find {', '.join(amounts)} in the book text I read")
    if cited:
        parts.append(f"I didn't read {' or '.join(cited)} for this")
    return f"(Check this against the recipe: {'; '.join(parts)}.)" if parts else ""
