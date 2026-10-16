"""
Shared ingredient-block engine: finds a recipe's ingredient list and
splits it into groups, using the book's own format rules from
books/.

Every book's ingredient list has the same overall shape: some header
material, then ingredient lines (optionally split into labeled groups),
then instruction steps, then maybe notes/variations. What differs per
book is only how to recognize each of those (ingredient_start, STEP_RE,
section_label, BATCH_LABEL_RE, SKIP_RE, parse_ingredient_line on the
book's module), so this engine, including line-wrap joining and finding
component labels, is shared by every book.
"""

import re

from books import profile_for
from common.text_parsing import heading_text, is_component_label
from scale_utils.line_fallbacks import parse_fallback

# Asides at the end of a recipe ("DO AHEAD", "NOTES", "VARIATION 2"). Once
# one starts, nothing after it belongs in the scaled list: a variation's
# ingredients are an alternative, not an addition, and a variation can
# carry its own component labels that would otherwise restart the list.
ASIDE_LABEL_RE = re.compile(r"^(?:DO AHEAD|NOTES?|TIPS?|VARIATIONS?)(?:\s+\d+)?$")

# A batch label's one-line description right under it, e.g. "(for
# a thick layer over the whole pie)" under FULL BATCH.
_DESCRIPTION_RE = re.compile(r"^\(.*\)$")


class IngredientGroups(dict):
    """{group_name: [ingredients]} in the order they appear, plus what
    each group is:
      kinds         group_name -> "batch" (one of several alternative
                    sizes, only one gets made), "optional" (a component
                    the recipe can do without) or "component" (always
                    made). "default", the ingredients before any label,
                    is a component.
      descriptions  group_name -> the line describing a batch, if any.
    """

    def __init__(self):
        super().__init__()
        self.kinds = {}
        self.descriptions = {}

    @property
    def batches(self):
        return [name for name in self if self.kinds.get(name) == "batch"]


_SMALL_WORDS = {"a", "an", "and", "as", "for", "in", "of", "on", "or", "the", "to", "with"}


def label_title(heading):
    """An ALL-CAPS heading as a display name: "RICE PUDDING CAKE AND
    ASSEMBLY" -> "Rice Pudding Cake and Assembly", "BEEF-AND MUSHROOM
    FILLING" -> "Beef-and Mushroom Filling"."""
    words = []
    for i, word in enumerate(heading.lower().split()):
        parts = word.split("-")
        parts = [p if (i or j) and p in _SMALL_WORDS else p[:1].upper() + p[1:]
                 for j, p in enumerate(parts)]
        words.append("-".join(parts))
    return " ".join(words)


def group_kind(label, book):
    """"batch", "optional" or "component" for a label as printed."""
    upper = label.upper()
    if book.BATCH_LABEL_RE is not None and book.BATCH_LABEL_RE.match(upper):
        return "batch"
    if "OPTIONAL" in upper:
        return "optional"
    return "component"


def _is_wrapped_continuation(pending, line):
    """Whether `line` is the PDF's line-wrap of the ingredient line before
    it rather than a new line of its own. Any of three signals is enough:
      - the previous line left a parenthesis open, e.g. "coarsely chopped
        (2.1 oz /" followed by "60g)". This one wins even when the next
        line starts with a digit.
      - the line starts lowercase ("to liquefy", "bananas", "temperature").
        Ingredient lines start with an amount, and the few that don't
        ("Neutral oil for the pan", "Flaky salt, for sprinkling") start
        with a capital, so a lowercase start can only be a continuation.
      - the line starts with "(", an aside about the line above, like
        "(optional)" or "(about 3 medium)". A batch label's own "(for
        ...)" description is taken before this is ever asked.
    """
    return (pending.count("(") > pending.count(")") or line[:1].islower()
            or line.startswith("("))


def extract_ingredient_groups(chunk_text, strategy, trace=None):
    """Split a recipe's ingredient block into named groups using the
    book's format rules. Wrapped ingredient lines are joined back into one
    line before parsing, so the name and the metric amount aren't lost
    when the PDF breaks a long ingredient across two lines.

    A line the book's own parser rejects gets a second try with the
    book-independent fallbacks in scale_utils/line_fallbacks.py ("Pinch
    of salt", "Scant 1 g / ...", "Butter for the pan").

    A group label is either one the book itself recognizes (its
    section_label, e.g. Book on Pie's "FULL BATCH"), or any ALL-CAPS
    heading followed within a few lines by an ingredient
    (is_component_label, the same rule ingest uses to keep components
    inside their recipe).

    Returns an IngredientGroups: {group_name: [ingredients]}, "default"
    for ingredients before any label, plus each group's kind (batch,
    component or optional) and any batch descriptions. Empty groups are
    dropped (a label with nothing parsed under it isn't a real choice to
    offer, or a heading worth printing).

    trace, if given, is called as trace(kind, text) for every line, saying
    what was decided about it ("before start", "label", "step", "parsed",
    "rejected", ...). Only diagnostics pass it (testing/one_off/
    ingredient_trace.py), it never changes the result.
    """
    book = profile_for(strategy)
    if trace is None:
        def trace(kind, text):
            pass
    groups = IngredientGroups()
    groups["default"] = []
    groups.kinds["default"] = "component"
    current = "default"
    in_ingredients = True
    in_aside = False
    describing = None
    pending = None

    def flush():
        nonlocal pending
        if pending is not None:
            parsed = (book.parse_ingredient_line(pending)
                      or parse_fallback(pending, book.parse_ingredient_line))
            if parsed:
                groups[current].append(parsed)
            trace("parsed" if parsed else "rejected", pending)
            pending = None

    lines = chunk_text.splitlines()
    start = book.ingredient_start(lines)
    for line in lines[:start]:
        trace("before start", line)
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            flush()
            continue
        if in_aside:
            trace("after aside", stripped)
            continue
        heading = heading_text(stripped)
        if heading and ASIDE_LABEL_RE.match(heading):
            flush()
            in_aside = True
            trace("aside (ends list)", stripped)
            continue
        if describing and _DESCRIPTION_RE.match(stripped):
            groups.descriptions[describing] = stripped[1:-1].strip()
            describing = None
            trace("batch description", stripped)
            continue
        describing = None
        group_name = book.section_label(stripped)
        if not group_name and heading and is_component_label(lines, i, book.parse_ingredient_line):
            group_name = label_title(heading)
        if group_name:
            flush()
            current = group_name
            groups.setdefault(current, [])
            groups.kinds[current] = group_kind(group_name, book)
            if groups.kinds[current] == "batch":
                describing = current
            in_ingredients = True
            trace("group label", stripped)
            continue
        if book.SKIP_RE and book.SKIP_RE.match(stripped):
            flush()
            trace("skipped", stripped)
            continue
        if book.STEP_RE.match(stripped):
            flush()
            in_ingredients = False
            trace("step (ends list)", stripped)
            continue
        if not in_ingredients:
            trace("after list ended", stripped)
            continue

        if pending is not None and _is_wrapped_continuation(pending, stripped):
            pending = f"{pending} {stripped}"
            trace("joined to line above", stripped)
        else:
            flush()
            pending = stripped
    flush()

    for name in [name for name, ings in groups.items() if not ings]:
        del groups[name]
    return groups


def pick_default_batch(groups):
    """When a scaling request doesn't specify which batch size to start
    from, decide a reasonable default: prefer a batch named "Full Batch"
    or "Regular Batch" (Book on Pie's names for "the normal amount"), fall
    back to the only group if there's just one, otherwise return None to
    signal that this is genuinely ambiguous and needs to be asked about.
    """
    if len(groups) == 1:
        return next(iter(groups))
    for name in groups:
        if name.lower() in ("full batch", "regular batch"):
            return name
    return None
