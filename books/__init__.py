"""
Per-cookbook format rules. Each book with a consistent, detectable layout
gets one module here holding everything specific to that book's format,
used by all three main scripts:

    find_recipe_starts(lines)        ingest: where each recipe begins
    extract_title(text, include_subtitle=True)
                                     query/scale: a recipe chunk's title
    parse_ingredient_line(line)      scale: one ingredient line -> dict
    ingredient_start(lines)          scale: where the ingredient list begins
    STEP_RE                          scale: an instruction step (ends the list)
    section_label(line)              scale: group name for a label shape of the
                                     book's own, or None (ALL-CAPS component
                                     labels are found by the shared engine)
    BATCH_LABEL_RE                   scale: labels that are alternative batch
                                     sizes (scale ONE of them), or None
    SKIP_RE                          scale: lines to ignore in the list, or None

find_recipe_starts gets layout too: the extracted line records parallel
to lines (font size, bold, position, see ingest_utils/extract.py), for a
book whose titles are told by type size. Optional:

    find_section_starts(lines, layout, consumed)
                                     ingest: where non-recipe sections
                                     begin, instead of the shared ALL-CAPS
                                     rule in ingest_utils/chunking.py
    ingredient_end(lines, start)     scale: where the ingredient list ends,
                                     for a book whose STEP_RE can't tell
    is_continuation(pending, last_line, line)
                                     scale: more ways a line can be the wrap
                                     of the ingredient line before it
                                     (pending, joined so far; last_line, its
                                     last line as printed)

Adding a book: write a module with those names, then add it to both
tables below.
"""

from books import book_on_pie, bravetart, dessert_person

# Lowercased, stripped book title -> strategy name. The title is the one
# in common/config.BOOK_FILES and stored on every chunk. A book missing from here
# gets generic page-based chunking at ingest, and its chunks are tagged
# content_type="unknown", so query-time recipe matching never looks at
# them anyway.
RECIPE_AWARE_BOOKS = {
    "the book on pie": "book_on_pie",
    "dessert person": "dessert_person",
    "bravetart": "bravetart",
}

# Strategy name -> the module holding that format's rules.
PROFILES = {
    "book_on_pie": book_on_pie,
    "dessert_person": dessert_person,
    "bravetart": bravetart,
}


def strategy_for(book_title):
    """Return the strategy name for a book title, or None if it has no
    recipe-aware profile. Normalizes the same way ingest always has, so
    "Dessert Person" and " dessert person " resolve identically."""
    return RECIPE_AWARE_BOOKS.get((book_title or "").strip().lower())


def profile_for(strategy):
    """The rules module for a strategy. Falls back to Book on Pie's, the
    original format, for anything unlisted."""
    return PROFILES.get(strategy, book_on_pie)


def profile_for_book(book_title):
    return profile_for(strategy_for(book_title))
