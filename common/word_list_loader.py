"""
Shared loader for word/phrase list config files.

Same pattern established by scaling_rules.py: load fresh on every call
(not cached at import) so edits to a JSON file take effect on the very
next run, and fail gracefully to a caller-supplied default rather than
crash if a file is missing or malformed, a missing word list should
degrade one feature, not take down the whole script.

Two kinds of lists this supports:
  - universal: book-independent (how people phrase "double this recipe",
    regardless of which cookbook it's from). Shared across every book.
  - book-specific: tied to one book's own formatting quirks (e.g. this
    book's "HALF BATCH" / "VARIATION" subsection labels, another book
    might use different labels, or none at all). Looked up by book title,
    so a missing file just means "this book has no special case for this
    concern," not an error.
"""

import json
import os
import re

from common.config import PROJECT_ROOT

WORD_LISTS_DIR = os.path.join(PROJECT_ROOT, "word_lists")
UNIVERSAL_DIR = os.path.join(WORD_LISTS_DIR, "universal")
BOOKS_DIR = os.path.join(WORD_LISTS_DIR, "books")


def slugify(title):
    """Turn a human-readable book title into a filesystem-safe folder
    name: lowercase, anything that isn't a letter or digit collapsed to
    a single underscore. "The Book On Pie" -> "the_book_on_pie".

    Used so book-specific word lists and the chunking-profile lookup
    (RECIPE_AWARE_BOOKS in books/__init__.py) can both derive their key from the same
    book title, rather than maintaining two separate naming schemes that
    could quietly drift out of sync with each other.
    """
    slug = title.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        print(f"Warning: couldn't parse {path} ({e}), using default instead.")
        return default


def load_universal(filename, default):
    """Load a universal (book-independent) word list JSON file."""
    return _load_json(os.path.join(UNIVERSAL_DIR, filename), default)


def load_book_specific(book_title, filename, default):
    """Load a word list scoped to one specific book. A missing file is
    the normal, expected case for any book with no special formatting
    for this particular concern, not a warning-worthy one, so it's
    silent, unlike a malformed file (which still warns).
    """
    path = os.path.join(BOOKS_DIR, slugify(book_title), filename)
    if not os.path.exists(path):
        return default
    return _load_json(path, default)
