"""
Debug helper: show exactly what ingest's title detection sees for a
book, without embedding or writing anything to Chroma.

Run from app/ (either form works):
    python3 testing/one_off/dump_pages.py "Dessert Person"          # summary only
    python3 testing/one_off/dump_pages.py "Dessert Person" 40 42    # plus raw lines of PDF pages 40-42
    python3 -m testing.one_off.dump_pages "Dessert Person"

Page numbers are PDF page indexes (0-based, as pymupdf counts them), not
the printed page numbers in the book.
"""

import os
import sys

# Lets this run as a plain file path, not only with -m: put app/ on the
# import path so ingest and the shared modules can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pymupdf as fitz  # noqa: E402  (imports below need the path above)

from books import profile_for, strategy_for  # noqa: E402
from ingest import BOOKS  # noqa: E402
from ingest_utils.pdf_text import build_line_stream, extract_ordered_text  # noqa: E402


def summarize(book_title, pdf_path):
    strategy = strategy_for(book_title)
    print(f"Book: {book_title!r}  ->  strategy: {strategy}")
    print(f"PDF:  {pdf_path}")

    lines, page_starts = build_line_stream(pdf_path)
    print(f"{len(page_starts)} non-empty pages, {len(lines)} lines total")

    starts, _ = profile_for(strategy).find_recipe_starts(lines)
    print(f"Recipe starts detected: {len(starts)}")
    for idx in starts[:10]:
        print(f"  line {idx}: {lines[idx].strip()!r}")

    # Any line mentioning "season" at all, however it's formatted. If the
    # detector found nothing but these exist, their exact repr shows why
    # (casing, a stray leading character, "Season" split from its colon).
    season_lines = [(i, l) for i, l in enumerate(lines) if "season" in l.lower()]
    print(f"\nLines containing 'season' (any case): {len(season_lines)}")
    for i, l in season_lines[:10]:
        prev = lines[i - 1] if i > 0 else ""
        print(f"  line {i}: {l!r}")
        print(f"      previous line: {prev!r}")


def dump_pages(pdf_path, first, last):
    doc = fitz.open(pdf_path)
    for page_index in range(first, min(last, len(doc) - 1) + 1):
        print(f"\n===== PDF page index {page_index} =====")
        for n, line in enumerate(extract_ordered_text(doc[page_index]).splitlines()):
            print(f"{n:3d}: {line!r}")
    doc.close()


if __name__ == "__main__":
    if len(sys.argv) not in (2, 4):
        print('Usage: python3 testing/one_off/dump_pages.py "Book Title" [first_page last_page]')
        print(f"Known books: {', '.join(BOOKS)}")
        sys.exit(1)

    title = sys.argv[1]
    if title not in BOOKS:
        print(f"{title!r} isn't in ingest.BOOKS. Known books: {', '.join(BOOKS)}")
        sys.exit(1)

    if not os.path.isfile(BOOKS[title]):
        print(f"PDF not found at {BOOKS[title]}, fix COOKBOOKS_DIR or the filename in ingest.BOOKS.")
        sys.exit(1)

    summarize(title, BOOKS[title])
    if len(sys.argv) == 4:
        dump_pages(BOOKS[title], int(sys.argv[2]), int(sys.argv[3]))
