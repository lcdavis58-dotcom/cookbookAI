"""
The shared recipe-finding rules every book module can lean on, so a new
book is mostly settings (see books/__init__.py for the full interface).

Every one of the 16 books is an ebook conversion set on one type scale:
body text at 15pt, headings at 16.9 / 21.2 / 25 / 27.5 / 30. Which of
those a book uses for its recipe titles differs (16.9 in Salt Fat Acid
Heat, 30 in The Cookie Book), and many books use two (main recipes and
component recipes), but in all 16 a recipe title is a short run of lines
at heading size followed, before the next heading, by the book's yield
line ("Makes ...", "YIELD: ...", "Season: ..."). That is the rule here.

Headings are told by size alone, so a book's settings say only:

    TITLE_MIN_SIZE      the smallest size its recipe titles use (anything
                        that size or bigger is a heading: a recipe title,
                        a chapter or an essay)
    YIELD_RE            the line every recipe has between its title and
                        the next heading
    TITLE_ITALIC        True if its titles are italic (Ratio); otherwise
                        italic lines that size are asides ("Mix it up!")
    MAX_TITLE_LINES     longer runs at heading size are prose, not a title
                        (some books set headnotes at 16.9)
    TITLE_BOLD          True if only bold lines are headings (Savory
                        Baking sets pull quotes at its title size)
    TITLE_MAX_GAP       a heading line further below the one above than
                        this (points) starts a heading of its own (a
                        section name right above a recipe title)
    TITLE_THEN_INGREDIENTS
                        True if a title with no yield line, followed
                        right away by an ingredient line, is a recipe
                        too: a sauce printed after the recipe that uses
                        it ("Salted Caramel Sauce" / "298 g / 1½ cups
                        granulated sugar", The Fearless Baker)
    COMPONENT_TITLE_MIN_SIZE
                        the smallest size of a bold line, below title
                        size, that starts a recipe when a yield line comes
                        right after it: a component printed inside another
                        recipe ("Caesar Salad Dressing" / "MAKES ABOUT 1½
                        CUPS", The Food Lab). None by default.

Sizes are compared against thresholds, never exact values: some books
scale a page about 1% smaller (BraveTart's 24.7 / 14.8).
"""

import re

from books.line_styles import NUMBERED_STEP_RE, STYLES
from common.text_parsing import heading_text, is_component_label
from scale_utils.line_fallbacks import parse_fallback

# How far below the setting a size can be and still count, for the
# slightly scaled pages.
SIZE_TOLERANCE = 0.5


class Headings:
    """The heading line ranges of a book's layout, per its settings."""

    def __init__(self, layout, min_size, italic=False, max_lines=6, bold=False, max_gap=None):
        self.min_size = min_size - SIZE_TOLERANCE
        self.italic = italic
        self.max_lines = max_lines
        self.bold = bold
        self.max_gap = max_gap
        self.ranges = self._find(layout)

    def _is_heading_line(self, record):
        return (record["size"] >= self.min_size and record["italic"] == self.italic
                and (record["bold"] or not self.bold) and bool(record["text"].strip()))

    def _continues(self, first, record):
        """Whether a heading line goes on the heading that started with
        first: on the same page, and close enough below when the book
        sets a TITLE_MAX_GAP."""
        return (record["page"] == first["page"]
                and (self.max_gap is None or (record["gap"] or 0) <= self.max_gap))

    def _find(self, layout):
        """[(first, last)] line ranges of every heading: consecutive
        heading lines on one page, whatever their exact sizes ("Chapter 1"
        over "COOKIES & CANDY" is one heading). A run longer than
        max_lines is prose set large, not a heading."""
        ranges = []
        i = 0
        while i < len(layout):
            if not self._is_heading_line(layout[i]):
                i += 1
                continue
            j = i
            while (j + 1 < len(layout) and self._is_heading_line(layout[j + 1])
                   and self._continues(layout[i], layout[j + 1])):
                j += 1
            if j - i + 1 <= self.max_lines:
                ranges.append((i, j))
            i = j + 1
        return ranges


def find_recipe_starts_by_size(lines, layout, settings):
    """(start_line_indices, consumed_line_indices, headings) for a book
    whose settings module has TITLE_MIN_SIZE and YIELD_RE. A recipe
    starts at a heading with a yield line after it and before the next
    heading; consumed is its title lines, so they're never read as a
    section of their own."""
    if layout is None:
        raise ValueError("this book's recipes are found by type size, so it needs the layout")
    headings = Headings(layout, settings.TITLE_MIN_SIZE,
                        italic=getattr(settings, "TITLE_ITALIC", False),
                        max_lines=getattr(settings, "MAX_TITLE_LINES", 6),
                        bold=getattr(settings, "TITLE_BOLD", False),
                        max_gap=getattr(settings, "TITLE_MAX_GAP", None))
    yield_re = settings.YIELD_RE
    starts, consumed = [], set()
    ranges = headings.ranges
    for n, (first, last) in enumerate(ranges):
        next_heading = ranges[n + 1][0] if n + 1 < len(ranges) else len(lines)
        if (any(yield_re.match(lines[k].strip()) for k in range(last + 1, next_heading))
                or (getattr(settings, "TITLE_THEN_INGREDIENTS", False)
                    and _ingredients_follow(lines, last + 1, next_heading, settings))):
            starts.append(first)
            consumed.update(range(first, last + 1))
    component_size = getattr(settings, "COMPONENT_TITLE_MIN_SIZE", None)
    if component_size is not None:
        for i in range(len(layout) - 1):
            if i not in consumed and _is_component_title(layout[i], component_size, settings.TITLE_MIN_SIZE) \
                    and yield_re.match(lines[i + 1].strip()):
                starts.append(i)
                consumed.add(i)
        starts.sort()
    return starts, consumed, headings


def _ingredients_follow(lines, start, end, settings):
    """Whether the first line after a title is an ingredient, read by the
    book's own parser (not the fallbacks). An ALL-CAPS line is a table of
    contents or a cover ("650 RECIPES FOR..."), never one."""
    first = next((lines[k].strip() for k in range(start, end) if lines[k].strip()), "")
    # A book module passed as is (Cooking For Two) names its style only.
    parse = getattr(settings, "parse_ingredient_line", None) or STYLES[settings.INGREDIENT_STYLE]
    return bool(first) and first != first.upper() and bool(parse(first))


# A component's title: short, starting with a capital, not a sentence.
_COMPONENT_TITLE_RE = re.compile(r"^[A-Z][^.:;!?]{1,60}$")


def _is_component_title(record, min_size, title_size):
    return (record.get("bold") and min_size - SIZE_TOLERANCE <= record["size"] < title_size - SIZE_TOLERANCE
            and bool(_COMPONENT_TITLE_RE.match(record["text"].strip())))


def section_starts_by_size(headings, consumed):
    """Every heading that doesn't start a recipe (an essay, a chapter
    opener) starts an "other" chunk."""
    return [first for first, _ in headings.ranges if first not in consumed]


# ---------------------------------------------------------------------------
# The yield block and where the ingredient list starts (scale)
# ---------------------------------------------------------------------------
# A line left hanging, so the next one continues it: "plus 30-",
# "DIFFICULTY:", "ACTIVE TIME: 30 minutes |".
_HANGING_END_RE = re.compile(r"(?:-|\bto|\bplus|,|\(|:|\|)$")
_COUNTED_SIZE_RE = re.compile(r"^(?:one|two|three|four|five|six|an?)\s+\d", re.IGNORECASE)
# The ALL-CAPS wrap of an ALL-CAPS yield line opens with a joining word
# ("INTO LARGE OR SMALL BARS"); a group label right after the yield
# ("ICE CREAM") doesn't.
_CAPS_WRAP_RE = re.compile(r"^(?:INTO|OR|AND|WITH|FOR|OF|TO|PLUS|ABOUT|EACH|PER|IN|ON)\b[A-Z0-9 ,&;'’()\-]*$")


def yield_block_length(lines, i, field_re=None):
    """How many lines the yield block starting at lines[i] takes up: it
    goes on while the next line carries one of the book's header fields
    (field_re: "ACTIVE TIME:", "DIFFICULTY:"), starts with "|" or a
    lowercase letter, closes a parenthesis left open, or finishes a line
    left hanging. An ALL-CAPS yield line goes on onto an ALL-CAPS line
    that opens with a joining word ("MAKES ONE 9-INCH (23CM) SQUARE PAN,
    WHICH CAN BE CUT" / "INTO LARGE OR SMALL BARS"), which would otherwise
    read as a group label."""
    n = 1
    while i + n < len(lines):
        line = lines[i + n].strip()
        block = " ".join(lines[i:i + n])
        prev = lines[i + n - 1].rstrip()
        if not line:
            break
        if ((field_re is not None and field_re.search(line)) or line.startswith("|")
                or line[:1].islower() or block.count("(") > block.count(")")
                or _HANGING_END_RE.search(prev)
                or (prev.isupper() and _CAPS_WRAP_RE.match(line))):
            n += 1
            continue
        break
    return n


def end_of_unmarked_list(lines, start, parse, max_unmeasured_chars, purpose_re, continues=None):
    """Where an ingredient list ends when nothing marks the steps (The
    Cookie Book's plain paragraphs, Savory Baking's few unnumbered
    steps): the first line from start that isn't an ingredient, the wrap
    of one (a parenthesis left open, a lowercase or "(" start) or an
    ALL-CAPS group label. A line with no amount counts as an ingredient
    only when it's short ("Sprinkles, optional") or says what it's for
    (purpose_re); a step's first line runs the width of the column.
    parse is the book's ingredient parser; continues(pending, line), if
    given, is one more way a line can wrap the ingredient above (Milk
    Bar's "[2 cups]")."""
    pending = None
    for i in range(start, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        if pending is not None and (pending.count("(") > pending.count(")")
                                    or line[:1].islower() or line.startswith("(")
                                    or (continues is not None and continues(pending, line))):
            pending = f"{pending} {line}"
            continue
        if heading_text(line):
            pending = None
            continue
        if _is_listed(line, parse, max_unmeasured_chars, purpose_re):
            pending = line
            continue
        return i
    return len(lines)


def _is_listed(line, parse, max_unmeasured_chars, purpose_re):
    if parse(line):
        return True
    parsed = parse_fallback(line, parse)
    if parsed is None:
        return False
    if not parsed.get("unmeasured"):
        return True
    return len(line) <= max_unmeasured_chars or bool(purpose_re.search(line))


# ---------------------------------------------------------------------------
# A book's profile: its module, with these defaults for what it leaves out
# ---------------------------------------------------------------------------
# The functions a book module can define to replace the engine's.
INTERFACE = {
    "find_recipe_starts", "find_section_starts", "extract_title", "parse_ingredient_line",
    "ingredient_start", "ingredient_end", "is_continuation", "starts_new_line", "section_label",
    "list_end_lines",
}
_SUBTITLE_RE = re.compile(r"^with\s+\S")
_WAYS_TAIL_RE = re.compile(r",\s*(?:\d+|[A-Za-z]+)\s+Ways$", re.IGNORECASE)
_WITH_TAIL_RE = re.compile(r"\s+with\s+", re.IGNORECASE)


_ENDS_PARAGRAPH_RE = re.compile(r"[.!?)”\"’]$|^\s*variations?\s*:?$", re.IGNORECASE)
# A name starting with one of these is an instruction, not a dish.
_INSTRUCTION_WORDS = frozenset("""a an the to for if in on omit add mix make use using replace substitute
    proceed follow stir bake cook roll keep store how you this it when once instead after before
    try serve note click""".split())
_ING_FOODS = frozenset({"pudding", "dumpling", "stuffing", "icing", "filling", "topping", "frosting",
                        "spring", "herring", "whiting"})
_NAME_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ’'\-]+")
MAX_VARIATION_NAME_WORDS = 9


def _is_variation_name(name, title):
    """A short name that isn't an instruction, and either shares a word
    with the recipe's title ("Meyer Lemon Curd" in "Lemon Curd") or is
    capitalized like a dish's name ("Greek Salad", "APPLE SLAW"): a
    bare change like "Mint" or "Whole grain" names no dish of its own."""
    words = _NAME_WORD_RE.findall(name)
    if not words or len(words) > MAX_VARIATION_NAME_WORDS or words[0].lower() in _INSTRUCTION_WORDS:
        return False
    if any(c.isdigit() for c in name):
        return False
    # "Preparing Butternut Squash", "Coring Apples": a how-to sidebar.
    first = words[0].lower()
    if first.endswith("ing") and first not in _ING_FOODS:
        return False
    title_words = {w.lower() for w in _NAME_WORD_RE.findall(title)}
    shares = any(w.lower() in title_words or w.lower().rstrip("s") in title_words for w in words
                 if len(w) > 2 and w.lower() not in _INSTRUCTION_WORDS | {"and", "with", "or", "of"})
    capitalized = len(words) > 1 and all(w[0].isupper() for w in words
                                         if w.lower() not in {"and", "with", "or", "of", "the", "a", "in"})
    return shares or capitalized


class Profile:
    """Everything the main scripts ask of a book (see books/__init__.py):
    the module's own settings and functions where it has them, the
    engine's defaults otherwise.

    Settings a module can give (UPPER_CASE names), besides the title ones
    at the top of this file:
        INGREDIENT_STYLE      a books/line_styles.py style name, unless the
                              module defines parse_ingredient_line itself
        HEADER_FIELD_RE       later lines of the yield block ("DIFFICULTY:")
        INGREDIENTS_AFTER_RE  the line the ingredient list follows, when it
                              isn't the yield line (Dessert Person's
                              "Makes", since its YIELD_RE is "Season:")
        INGREDIENTS_RIGHT_AFTER
                              True when the list starts right after that
                              line; otherwise intro prose may come between,
                              and the list starts at the first ingredient
                              or group label
        STEP_RE, SKIP_RE, BATCH_LABEL_RE
                              see books/__init__.py
        ASIDE_RE              the book's own ALL-CAPS asides inside a
                              recipe that end the ingredient list, like the
                              shared DO AHEAD / NOTES / VARIATIONS
                              (scale_utils/ingredients.py)
        TITLE_ALIASES         printed title -> list of extra titles to
                              find the recipe by, for titles that leave
                              out what the chapter supplies (The Cookie
                              Book's "Favorite Thin and Crispy", in the
                              chocolate chip chapter). Stored in the
                              recipe index; see query_utils/title_lookup.py
        VARIATIONS_HEADING_RE the line a recipe's variations follow
                              ("VARIATIONS"), or None for a book whose
                              variations can't be told apart (prose)
        VARIATION_NAME_RE     a variation's name, as group 1, at the start
                              of a line that starts a paragraph: "Name:
                              ..." by default; see variation_names
    """

    TITLE_ITALIC = False
    MAX_TITLE_LINES = 6
    TITLE_BOLD = False
    TITLE_MAX_GAP = None
    STEP_RE = NUMBERED_STEP_RE
    SKIP_RE = None
    BATCH_LABEL_RE = None
    ASIDE_RE = None
    HEADER_FIELD_RE = None
    INGREDIENTS_AFTER_RE = None
    INGREDIENTS_RIGHT_AFTER = False
    TITLE_ALIASES = {}
    TITLE_THEN_INGREDIENTS = False
    VARIATIONS_HEADING_RE = re.compile(r"^\s*variations?\s*:?\s*$", re.IGNORECASE)
    VARIATION_NAME_RE = re.compile(r"^([A-Z][^:.\n]{1,70}?):\s")

    def __init__(self, module):
        self.module = module
        for name, value in vars(module).items():
            if name.isupper() or name in INTERFACE:
                setattr(self, name, value)
        if "parse_ingredient_line" not in vars(module):
            self.parse_ingredient_line = STYLES[module.INGREDIENT_STYLE]

    def __repr__(self):
        return f"<Profile {self.module.__name__}>"

    # ingest ---------------------------------------------------------------

    def headings(self, layout):
        return Headings(layout, self.TITLE_MIN_SIZE, italic=self.TITLE_ITALIC,
                        max_lines=self.MAX_TITLE_LINES, bold=self.TITLE_BOLD,
                        max_gap=self.TITLE_MAX_GAP)

    def find_recipe_starts(self, lines, layout=None):
        """(start_line_indices, title_line_indices): see
        find_recipe_starts_by_size."""
        starts, consumed, _ = find_recipe_starts_by_size(lines, layout, self)
        return starts, consumed

    def find_section_starts(self, lines, layout, consumed):
        return section_starts_by_size(self.headings(layout), consumed)

    def list_end_lines(self, lines, layout):
        """Line indices that start a recipe's method right after its
        ingredient list, for a book whose lines can't tell (ingest puts a
        blank line before each; see ingest_utils/chunking.py). None by
        default."""
        return set()

    # query / scale --------------------------------------------------------

    def extract_title(self, text, include_subtitle=True):
        """A recipe chunk's title: its first line, since ingest joins a
        title's wrapped lines into one (ingest_utils/chunking.py), plus a
        "with ..." subtitle on the next line (Dessert Person's "Rice
        Pudding Cake" / "with Mango Caramel") when include_subtitle is
        on. Off, a "with ..." tail is dropped, so "LEMON MERINGUE PIE WITH
        MARSHMALLOW MERINGUE" matches as "LEMON MERINGUE PIE"."""
        lines = [line.strip() for line in text.splitlines()[:3] if line.strip()]
        if not lines:
            return ""
        title = lines[0]
        if not include_subtitle:
            return _WITH_TAIL_RE.split(title, maxsplit=1)[0]
        if len(lines) > 1 and _SUBTITLE_RE.match(lines[1]):
            title = f"{title} {lines[1]}"
        return title

    def title_aliases(self, title):
        """The extra titles TITLE_ALIASES gives a recipe, looked up by its
        printed title regardless of case and spacing (the book prints
        "FAVORITE THIN AND CRISPY"). A title ending in ", 11 Ways" or
        ", Three Ways" (HTCEV's "Béchamel Sauce, 11 Ways") can also be
        found without that tail, which other recipes leave out
        ("1 recipe Béchamel")."""
        key = " ".join((title or "").lower().split())
        aliases = [alias for printed, aliases in self.TITLE_ALIASES.items()
                   if " ".join(printed.lower().split()) == key for alias in aliases]
        if m := _WAYS_TAIL_RE.search(title or ""):
            aliases.append(title[:m.start()].strip())
        return aliases

    def variation_names(self, text):
        """The names of the variations printed after a recipe's
        VARIATIONS heading ("Brown Butter Cream Cheese Frosting" in
        Dessert Person's Classic Cream Cheese Frosting), as printed. A
        name starts a paragraph: the line after the heading, or after a
        line that ends a sentence, so a wrapped line ("Poached Eggs.")
        isn't one. Instructions ("Mix the dough by hand:") and names that
        are only a change ("Mint:", "Nuts:" in a brownie recipe) are left
        out; see _is_variation_name."""
        if self.VARIATIONS_HEADING_RE is None:
            return []
        lines = (text or "").splitlines()
        title = lines[0] if lines else ""
        names = []
        for i, line in enumerate(lines):
            if not self.VARIATIONS_HEADING_RE.match(line):
                continue
            previous = line
            for later in lines[i + 1:]:
                starts_paragraph = (_ENDS_PARAGRAPH_RE.search(previous.strip())
                                    or later.lstrip().startswith("•"))
                m = self.VARIATION_NAME_RE.match(later.strip()) if starts_paragraph else None
                if m:
                    name = " ".join(m.group(1).split()).strip(" ,")
                    if _is_variation_name(name, title) and name not in names:
                        names.append(name)
                previous = later
            break
        return names

    def ingredient_start(self, lines):
        """Where the ingredient list begins: after the yield block (or the
        INGREDIENTS_AFTER_RE line), at the first line that's an
        ingredient or a group label, or right there with
        INGREDIENTS_RIGHT_AFTER. The end of the chunk when there's no
        such line (a later part of a split recipe)."""
        anchor = self.INGREDIENTS_AFTER_RE or self.YIELD_RE
        at = next((i for i, line in enumerate(lines) if anchor.match(line.strip())), None)
        if at is None:
            # A recipe with no yield line (TITLE_THEN_INGREDIENTS): the
            # list starts right under its title. A later part of a split
            # recipe starts with step text, not a title then an ingredient.
            if (self.TITLE_THEN_INGREDIENTS and len(lines) > 1 and not self.parse_ingredient_line(lines[0].strip())
                    and self.parse_ingredient_line(lines[1].strip())):
                return 1
            return len(lines)
        after = at + yield_block_length(lines, at, self.HEADER_FIELD_RE)
        if self.INGREDIENTS_RIGHT_AFTER:
            return after
        for i in range(after, len(lines)):
            stripped = lines[i].strip()
            if not stripped:
                continue
            # A recipe with no list of its own (Savory Baking's "Stuffed"
            # Pretzels give amounts in the steps): the list can't start
            # after a step. A header field ("DIFFICULTY: 2 (Easy)") can look
            # like What's For Dessert's steps.
            if self.STEP_RE.match(stripped) and not (
                    self.HEADER_FIELD_RE is not None and self.HEADER_FIELD_RE.match(stripped)):
                break
            if self.starts_ingredients(lines, i):
                return i
        return len(lines)

    def starts_ingredients(self, lines, i):
        """Whether lines[i] can be the first line of the ingredient list:
        an ingredient, a group label of the book's own, a batch label, or
        an ALL-CAPS heading with an ingredient right after it."""
        stripped = lines[i].strip()
        if self.parse_ingredient_line(stripped) or self.section_label(stripped):
            return True
        # A spelled-out count before a size, which only the fallbacks read
        # ("One 12- to 16-pound (5.4 to 7.3kg) turkey"). Other fallback
        # shapes ("about ...") turn up in prose too.
        if _COUNTED_SIZE_RE.match(stripped):
            fallback = parse_fallback(stripped, self.parse_ingredient_line)
            if fallback and not fallback.get("unmeasured"):
                return True
        if self.BATCH_LABEL_RE is not None and self.BATCH_LABEL_RE.match(stripped):
            return True
        return bool(heading_text(stripped)) and is_component_label(lines, i, self.parse_ingredient_line)

    def ingredient_end(self, lines, start):
        """Where the list ends, for a book whose STEP_RE can't tell; by
        default the steps are found by STEP_RE as the list is read."""
        return len(lines)

    def is_continuation(self, pending, last_line, line):
        """More ways a line can be the wrap of the ingredient line before
        it, beyond the shared ones; none by default."""
        return False

    def starts_new_line(self, line):
        """Whether a line the shared rules would take for a wrap (it starts
        lowercase) is an ingredient of its own; never by default."""
        return False

    def section_label(self, line):
        """A group label of the book's own shape; ALL-CAPS component
        labels are found by the shared engine."""
        return None
