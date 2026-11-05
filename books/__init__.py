"""
Per-cookbook format rules. Each book with a consistent, detectable layout
gets a module here, mostly settings: the shared engine (books/engine.py)
does the work, and a module only adds code for what's truly its own.

Settings (see books/engine.py for all of them):

    TITLE_MIN_SIZE      ingest: smallest type size of its recipe titles
    YIELD_RE            ingest: the line between every title and the next
                        heading ("Makes ...", "YIELD:", "Season:")
    INGREDIENT_STYLE    scale: how amounts are printed, a style from
                        books/line_styles.py ("metric_slash", ...)
    HEADER_FIELD_RE, INGREDIENTS_AFTER_RE, INGREDIENTS_RIGHT_AFTER
                        scale: where the ingredient list starts
    STEP_RE             scale: an instruction step (ends the list);
                        numbered steps ("1. ...") by default
    BATCH_LABEL_RE      scale: labels that are alternative batch sizes
                        (scale ONE of them), or None
    SKIP_RE             scale: lines to ignore in the list, or None
    ASIDE_RE            scale: the book's own asides that end the list

Functions a module can define in place of the engine's:

    find_recipe_starts(lines, layout)
                        ingest: (recipe start lines, title lines)
    find_section_starts(lines, layout, consumed)
                        ingest: where non-recipe sections begin
    extract_title(text, include_subtitle=True)
                        query/scale: a recipe chunk's title
    parse_ingredient_line(line)
                        scale: one ingredient line -> dict
    ingredient_start(lines), ingredient_end(lines, start)
                        scale: where the ingredient list begins and ends
    section_label(line) scale: group name for a label shape of the book's
                        own, or None (ALL-CAPS component labels are found
                        by the shared engine)
    is_continuation(pending, last_line, line)
                        scale: more ways a line can be the wrap of the
                        ingredient line before it

Adding a book: find its title size and yield line with
tools/diagnostics/book_report.py (--anchor), write a module with the
settings, then add it to both tables below.
"""

from books import (book_on_pie, bravetart, cookie_book, cooking_for_two, dessert_person, fearless_baker,
                   genius_desserts, genius_recipes, htcev, milk_bar, savory_baking,
                   whats_for_dessert)
from books.engine import Profile

# Lowercased, stripped book title -> strategy name. The title is the one
# in common/config.BOOK_FILES and stored on every chunk. A book missing from here
# gets generic page-based chunking at ingest, and its chunks are tagged
# content_type="unknown", so query-time recipe matching never looks at
# them anyway.
RECIPE_AWARE_BOOKS = {
    "the book on pie": "book_on_pie",
    "dessert person": "dessert_person",
    "bravetart": "bravetart",
    "the fearless baker": "fearless_baker",
    "what's for dessert": "whats_for_dessert",
    "the cookie book": "cookie_book",
    "savory baking": "savory_baking",
    "momofuku milk bar": "milk_bar",
    "genius desserts": "genius_desserts",
    "genius recipes": "genius_recipes",
    "the complete cooking for two cookbook": "cooking_for_two",
    "how to cook everything vegetarian": "htcev",
}

# Strategy name -> that book's rules: its module, with the shared
# engine's defaults (books/engine.py) for whatever the module leaves out.
PROFILES = {
    "book_on_pie": Profile(book_on_pie),
    "dessert_person": Profile(dessert_person),
    "bravetart": Profile(bravetart),
    "fearless_baker": Profile(fearless_baker),
    "whats_for_dessert": Profile(whats_for_dessert),
    "cookie_book": Profile(cookie_book),
    "savory_baking": Profile(savory_baking),
    "milk_bar": Profile(milk_bar),
    "genius_desserts": Profile(genius_desserts),
    "genius_recipes": Profile(genius_recipes),
    "cooking_for_two": Profile(cooking_for_two),
    "htcev": Profile(htcev),
}


def strategy_for(book_title):
    """Return the strategy name for a book title, or None if it has no
    recipe-aware profile. Normalizes the same way ingest always has, so
    "Dessert Person" and " dessert person " resolve identically."""
    return RECIPE_AWARE_BOOKS.get((book_title or "").strip().lower())


def profile_for(strategy):
    """The rules for a strategy. Falls back to Book on Pie's, the
    original format, for anything unlisted."""
    return PROFILES.get(strategy, PROFILES["book_on_pie"])


def profile_for_book(book_title):
    return profile_for(strategy_for(book_title))
