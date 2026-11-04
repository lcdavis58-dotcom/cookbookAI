"""
Debug helper: show the layout of every page containing some text, line
by line: block number, position, font size, bold/italic, and the gap
above. Ingest joins lines with a single newline, so a visual gap in the
printed book (the space between a recipe's optional ingredients and the
rest) or a title's larger type is only visible here.

Reads the saved extraction (ingest_utils/extract.py), so it needs the
PDF only the first time. Run from app/ (either form works):
    python3 tools/diagnostics/dump_blocks.py "The Book On Pie" "PHYLLO DOUGH CRUST"
    python3 -m tools.diagnostics.dump_blocks "The Book On Pie" "OPTIONAL FLAVORINGS"
"""

import os
import sys

# Lets this run as a plain file path, not only with -m: put app/ on the
# import path so the shared modules can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from common.config import BOOK_FILES, book_pdf_path  # noqa: E402  (imports need the path above)
from ingest_utils.extract import load_extraction  # noqa: E402


def style(line):
    marks = ("B" if line["bold"] else "") + ("I" if line["italic"] else "")
    return f"{line['size']:4.1f}{marks:<2}"


def dump_blocks(pdf_path, needle):
    found = 0
    for page in load_extraction(pdf_path):
        if needle.lower() not in "\n".join(l["text"] for l in page["lines"]).lower():
            continue
        found += 1
        print(f"===== PDF page {page['index']} (printed {page['printed']}, "
              f"{page['lines'][-1]['block'] + 1} blocks) =====")
        print(" blk      y      x  size     gap  text")
        prev_block = None
        for line in page["lines"]:
            if prev_block is not None and line["block"] != prev_block:
                print()
            prev_block = line["block"]
            gap = "" if line["gap"] is None else f"{line['gap']:6.1f}"
            x0, y0 = line["bbox"][:2]
            print(f"{line['block']:4d} {y0:6.1f} {x0:6.1f}  {style(line)} {gap:>6}  {line['text']}")
            for text, size, _font, bold, italic in line.get("spans", []):
                if text.strip():
                    print(f"{'':20}  {style({'size': size, 'bold': bold, 'italic': italic})}"
                          f"{'':7}    | {text}")
        print()
    print(f"{found} page(s) contain {needle!r}.")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in BOOK_FILES:
        sys.exit(f"usage: dump_blocks.py BOOK_TITLE TEXT   (books: {', '.join(BOOK_FILES)})")
    dump_blocks(book_pdf_path(sys.argv[1]), sys.argv[2])
