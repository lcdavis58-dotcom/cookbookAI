"""
Debug helper: show the PDF text blocks on every page containing some
text, with each block's vertical position and the gap above it. Ingest
joins blocks with a single newline (ingest_utils/pdf_text.py), so a
visual gap in the printed book, like the space between a recipe's
optional ingredients and the rest, is only visible here.

Needs the PDF, so run it on the Pi, from app/ (either form works):
    python3 tools/diagnostics/dump_blocks.py "The Book On Pie" "PHYLLO DOUGH CRUST"
    python3 -m tools.diagnostics.dump_blocks "The Book On Pie" "OPTIONAL FLAVORINGS"
"""

import os
import sys

# Lets this run as a plain file path, not only with -m: put app/ on the
# import path so ingest and the shared modules can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pymupdf as fitz  # noqa: E402  (imports below need the path above)

from ingest import BOOKS  # noqa: E402
from ingest_utils.pdf_text import LIGATURES  # noqa: E402


def dump_blocks(pdf_path, needle):
    doc = fitz.open(pdf_path)
    found = 0
    for page_index in range(len(doc)):
        page = doc[page_index]
        if needle.lower() not in page.get_text().translate(LIGATURES).lower():
            continue
        found += 1
        blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
        blocks.sort(key=lambda b: (b[1], b[0]))
        print(f"===== PDF page {page_index} ({len(blocks)} text blocks) =====")
        prev_bottom = None
        for x0, y0, x1, y1, text, _, _ in blocks:
            gap = "" if prev_bottom is None else f"gap {y0 - prev_bottom:5.1f}"
            print(f"--- y {y0:6.1f}-{y1:6.1f}  x {x0:5.1f}  {gap}")
            for line in text.translate(LIGATURES).strip().splitlines():
                print(f"    {line}")
            prev_bottom = y1
        print()
    doc.close()
    print(f"{found} page(s) contain {needle!r}.")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in BOOKS:
        sys.exit(f"usage: dump_blocks.py BOOK_TITLE TEXT   (books: {', '.join(BOOKS)})")
    dump_blocks(BOOKS[sys.argv[1]], sys.argv[2])
