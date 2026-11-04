"""
Debug helper: show exactly what ingest's title detection sees for a
book, without embedding or writing anything to Chroma.

Run from app/ (either form works):
    python3 tools/diagnostics/dump_pages.py "Dessert Person"          # summary only
    python3 tools/diagnostics/dump_pages.py "Dessert Person" 40 42    # plus raw lines of PDF pages 40-42
    python3 -m tools.diagnostics.dump_pages "Dessert Person"

Page numbers are PDF page indexes (0-based, as pymupdf counts them), not
the printed page numbers in the book. Pages without text are skipped.
"""

import os
import sys

# Lets this run as a plain file path, not only with -m: put app/ on the
# import path so the shared modules can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from books import profile_for, strategy_for  # noqa: E402  (imports need the path above)
from common.config import BOOK_FILES, book_pdf_path  # noqa: E402
from ingest_utils.extract import load_extraction  # noqa: E402
from ingest_utils.pdf_text import build_layout_stream  # noqa: E402


def summarize(book_title, pdf_path):
    strategy = strategy_for(book_title)
    print(f"Book: {book_title!r}  ->  strategy: {strategy}")
    print(f"PDF:  {pdf_path}")

    layout, page_starts = build_layout_stream(pdf_path)
    lines = [r["text"] for r in layout]
    print(f"{len(page_starts)} non-empty pages, {len(lines)} lines total")

    starts, _ = profile_for(strategy).find_recipe_starts(lines, layout)
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
    for page in load_extraction(pdf_path):
        if first <= page["index"] <= last:
            print(f"\n===== PDF page index {page['index']} =====")
            for n, line in enumerate(page["lines"]):
                print(f"{n:3d}: {line['text']!r}")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 4):
        print('Usage: python3 tools/diagnostics/dump_pages.py "Book Title" [first_page last_page]')
        print(f"Known books: {', '.join(BOOK_FILES)}")
        sys.exit(1)

    title = sys.argv[1]
    if title not in BOOK_FILES:
        print(f"{title!r} isn't in common/config.BOOK_FILES. Known books: {', '.join(BOOK_FILES)}")
        sys.exit(1)

    pdf_path = book_pdf_path(title)
    if not os.path.isfile(pdf_path):
        print(f"PDF not found at {pdf_path}, set COOKBOOKS_DIR or fix the filename in common/config.BOOK_FILES.")
        sys.exit(1)

    summarize(title, pdf_path)
    if len(sys.argv) == 4:
        dump_pages(pdf_path, int(sys.argv[2]), int(sys.argv[3]))
