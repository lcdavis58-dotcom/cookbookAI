"""
Shared ingredient-block engine: finds a recipe's ingredient list and
splits it into groups, using the book's own format rules from
books/.

Every book's ingredient list has the same overall shape: some header
material, then ingredient lines (optionally split into labeled groups),
then instruction steps, then maybe notes/variations. What differs per
book is only how to recognize each of those (ingredient_start, STEP_RE,
section_label, SKIP_RE, parse_ingredient_line on the book's module), so
this engine, including line-wrap joining, is shared by every book.
"""

from books import profile_for

# Labels that can appear inside a recipe but never introduce ingredients
# that belong in the scaled list. A variation's ingredients are an
# alternative, not an addition, so they're excluded too.
NON_INGREDIENT_LABELS = {"DO AHEAD", "NOTE", "NOTES", "TIP", "TIPS", "VARIATION", "VARIATIONS"}


def _is_wrapped_continuation(pending, line):
    """Whether `line` is the PDF's line-wrap of the ingredient line before
    it rather than a new line of its own. Two signals, either is enough:
      - the previous line left a parenthesis open, e.g. "coarsely chopped
        (2.1 oz /" followed by "60g)". This one wins even when the next
        line starts with a digit.
      - the line starts lowercase ("to liquefy", "bananas", "temperature").
        Ingredient lines start with an amount, and the few that don't
        ("Neutral oil for the pan", "Flaky salt, for sprinkling") start
        with a capital, so a lowercase start can only be a continuation.
    """
    return pending.count("(") > pending.count(")") or line[:1].islower()


def extract_ingredient_groups(chunk_text, strategy):
    """Split a recipe's ingredient block into named groups using the
    book's format rules. Wrapped ingredient lines are joined back into one
    line before parsing, so the name and the metric amount aren't lost
    when the PDF breaks a long ingredient across two lines.

    Returns {group_name: [ingredients]}, "default" for ingredients before
    any group label. Empty groups are dropped (a label with nothing parsed
    under it isn't a real choice to offer, or a heading worth printing).
    Whether the groups are alternatives or parts of one recipe is the
    book module's GROUPS_ARE.
    """
    book = profile_for(strategy)
    groups = {"default": []}
    current = "default"
    in_ingredients = True
    pending = None

    def flush():
        nonlocal pending
        if pending is not None:
            parsed = book.parse_ingredient_line(pending)
            if parsed:
                groups[current].append(parsed)
            pending = None

    lines = chunk_text.splitlines()
    for line in lines[book.ingredient_start(lines):]:
        stripped = line.strip()
        if not stripped:
            flush()
            continue
        if stripped.upper() in NON_INGREDIENT_LABELS:
            flush()
            in_ingredients = False
            continue
        group_name = book.section_label(stripped)
        if group_name:
            flush()
            current = group_name
            groups.setdefault(current, [])
            in_ingredients = True
            continue
        if book.SKIP_RE and book.SKIP_RE.match(stripped):
            flush()
            continue
        if book.STEP_RE.match(stripped):
            flush()
            in_ingredients = False
            continue
        if not in_ingredients:
            continue

        if pending is not None and _is_wrapped_continuation(pending, stripped):
            pending = f"{pending} {stripped}"
        else:
            flush()
            pending = stripped
    flush()

    return {name: ings for name, ings in groups.items() if ings}


def pick_default_batch(groups):
    """When a scaling request doesn't specify which batch size to start
    from, decide a reasonable default: prefer a batch literally named
    "Full Batch" (Book on Pie's convention for "the normal amount"), fall
    back to the only group if there's just one, otherwise return None to
    signal that this is genuinely ambiguous and needs to be asked about.
    """
    if len(groups) == 1:
        return next(iter(groups))
    for name in groups:
        if name.lower() == "full batch":
            return name
    return None
