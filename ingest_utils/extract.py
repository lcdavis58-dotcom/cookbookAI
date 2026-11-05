"""
The extract stage: PDF -> every text line with its page and layout (font
size, font, bold/italic, position, gap above), saved to EXTRACT_DIR so
later stages and diagnostics never reopen the PDF. Book-independent.

The text is exactly what ingest has always read (pymupdf's text blocks,
sorted top to bottom, stripped, ligatures expanded), so switching to
this changed no chunk. The layout is extra, for title and group
detection that needs more than the words.

A saved extraction quotes the whole book, so EXTRACT_DIR must stay out
of the repository (the default is next to chroma_db). It's rebuilt
automatically when the PDF changes or EXTRACT_VERSION goes up.

Saved shape:
    {"version", "source": {"file", "size", "mtime"},
     "pages": [{"index"  PDF page index (0-based),
                "printed", "confirmed"  printed page number, see
                                        guess_printed_page_number,
                "width", "height",
                "lines": [line, ...]}]}
    line: {"text", "size"  font size of the line's main span,
           "font", "bold", "italic", "bbox": [x0, y0, x1, y1],
           "block"  block number within the page (lines of one block
                    were set together),
           "gap"    space between this line's top and the previous
                    line's bottom, None on a page's first line,
           "spans"  [[text, size, font, bold, italic], ...], only when
                    the line mixes sizes or weights ("Note:" in bold,
                    then prose)}
Only pages with text are kept.
"""

import json
import os
import re

from common.config import EXTRACT_DIR

# Bump when the saved shape or the text rules change, so old saved
# extractions get rebuilt instead of read.
EXTRACT_VERSION = 2

# Typographic ligatures some PDFs store as a single character (Dessert
# Person stores "Difficulty" as "Difﬁculty" and "flour" as
# "ﬂour"). Left alone, regexes looking for "Difficulty"
# silently never match, and "flour" in a question or a rules file never
# matches "ﬂour" in a chunk. Only ligatures are expanded on purpose,
# NOT full unicodedata NFKC normalization, which would also turn "½"
# into "1⁄2" and "①" into "1", breaking the unicode-fraction
# ingredient parser and the footnote-marker stripping.
#
# The Cookie Book's ebook conversion maps its ligature glyphs to IPA
# letters instead ("ɻour", "ɹrm", "coʃee", "puɽer", "truʀes"). No book
# uses those letters as themselves, so they're expanded the same way.
LIGATURES = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
    "ʃ": "ff", "ɹ": "fi", "ɻ": "fl", "ɽ": "ffi", "ʀ": "ffl",
})

_BOLD_FONT_RE = re.compile(r"bold|black|heavy|semibold|demi", re.IGNORECASE)
_ITALIC_FONT_RE = re.compile(r"italic|oblique", re.IGNORECASE)


def _span_style(span):
    """(size, font, bold, italic) of one pymupdf span. Bold and italic
    come from the font flags or, since many book PDFs embed "Garamond-
    Bold" without setting the flag, the font name."""
    font = span["font"]
    bold = bool(span["flags"] & 16) or bool(_BOLD_FONT_RE.search(font))
    italic = bool(span["flags"] & 2) or bool(_ITALIC_FONT_RE.search(font))
    return round(span["size"], 1), font, bold, italic


def _line_record(text, spans, bbox, block_no):
    styled = [(s["text"].translate(LIGATURES), *_span_style(s)) for s in spans if s["text"]]
    # The line's style is its span with the most visible characters, so a
    # trailing space in another font doesn't decide it.
    main = max(styled, key=lambda s: len(s[0].strip()), default=("", 0, "", False, False))
    record = {"text": text, "size": main[1], "font": main[2], "bold": main[3],
              "italic": main[4], "bbox": [round(v, 1) for v in bbox], "block": block_no}
    # Only size and weight count as a change of style; digits set in
    # another font of the same size are still one style.
    if len({(s[1], s[3], s[4]) for s in styled if s[0].strip()}) > 1:
        record["spans"] = [list(s) for s in styled]
    return record


def extract_page_lines(page):
    """A page's lines in reading order: text blocks sorted top to bottom
    (left to right as a tiebreaker), each block stripped of the space
    around it. Reading the blocks in the PDF's stored order isn't safe,
    it doesn't always match the visual order even on a simple page.

    Assumes single-column pages, as every book so far is. A PDF with real
    columns would need a left-half/right-half split, sorting by y alone
    interleaves the two columns line by line.
    """
    import pymupdf  # only the extract stage needs it

    # The same text flags pymupdf's "blocks" output uses, which is what
    # ingest read before layout was kept; the default "dict" flags group
    # text into blocks differently.
    data = page.get_text("dict", flags=pymupdf.TEXTFLAGS_BLOCKS)
    blocks = []
    for block in data["blocks"]:
        if block["type"] != 0:
            continue
        lines = []
        for line in block["lines"]:
            # Some PDFs end a span with its own newline; it's never a line.
            text = "".join(s["text"] for s in line["spans"]).rstrip("\n")
            if text:
                lines.append([text, line["spans"], line["bbox"]])
        # Strip the block as a whole: drop blank lines at either end, trim
        # the outer edges of the first and last line.
        while lines and not lines[0][0].strip():
            lines.pop(0)
        while lines and not lines[-1][0].strip():
            lines.pop()
        if not lines:
            continue
        lines[0][0] = lines[0][0].lstrip()
        lines[-1][0] = lines[-1][0].rstrip()
        blocks.append((block["bbox"][1], block["bbox"][0], lines))
    blocks.sort(key=lambda b: (b[0], b[1]))

    records = []
    prev_bottom = None
    for block_no, (_, _, lines) in enumerate(blocks):
        for text, spans, bbox in lines:
            text = text.translate(LIGATURES)
            # Matches how ingest always split a page's text into lines:
            # str.splitlines, which also breaks on \r, \x0c,   and a
            # few more, so one PDF line can become several.
            for piece in (text + "\n").splitlines():
                record = _line_record(piece, spans, bbox, block_no)
                record["gap"] = None if prev_bottom is None else round(bbox[1] - prev_bottom, 1)
                records.append(record)
            prev_bottom = bbox[3]
    return records


def guess_printed_page_number(texts):
    """Try to find the actual printed page number from the page's own
    lines. Returns (page_number_or_None, confirmed). If no printed number
    is found anywhere in the book, callers should stop showing a page
    number at all rather than substituting the PDF's internal index,
    which for reflowed or multi-column PDFs often has no relationship to
    the printed numbering.
    """
    lines = [t.strip() for t in texts if t.strip()]
    candidates = [int(t) for t in lines[:3] + lines[-3:] if re.fullmatch(r"\d{1,4}", t)]
    if candidates:
        return candidates[-1], True
    return None, False


def extract_book(pdf_path):
    """Extract every page of a PDF (the slow part, a few seconds a book)."""
    import pymupdf

    pages = []
    doc = pymupdf.open(pdf_path)
    for page_index in range(len(doc)):
        page = doc[page_index]
        lines = extract_page_lines(page)
        if not lines:
            continue
        printed, confirmed = guess_printed_page_number([l["text"] for l in lines])
        pages.append({"index": page_index, "printed": printed, "confirmed": confirmed,
                      "width": round(page.rect.width, 1), "height": round(page.rect.height, 1),
                      "lines": lines})
    doc.close()
    return pages


def _source_info(pdf_path):
    stat = os.stat(pdf_path)
    return {"file": os.path.basename(pdf_path), "size": stat.st_size, "mtime": int(stat.st_mtime)}


def extraction_path(pdf_path):
    return os.path.join(EXTRACT_DIR, os.path.splitext(os.path.basename(pdf_path))[0] + ".json")


def load_extraction(pdf_path, rebuild=False):
    """The book's pages (see the module docstring), from EXTRACT_DIR when
    a current one is saved there, otherwise extracted now and saved."""
    path = extraction_path(pdf_path)
    source = _source_info(pdf_path)
    if not rebuild and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            saved = json.load(f)
        if saved.get("version") == EXTRACT_VERSION and saved.get("source") == source:
            return saved["pages"]

    pages = extract_book(pdf_path)
    os.makedirs(EXTRACT_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": EXTRACT_VERSION, "source": source, "pages": pages},
                  f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return pages
