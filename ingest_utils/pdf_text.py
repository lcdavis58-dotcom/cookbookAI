"""
Getting clean, ordered text out of a cookbook PDF, page by page and as
one continuous line stream. Book-independent.
"""

import re

import pymupdf as fitz

# Typographic ligatures some PDFs store as a single character (Dessert
# Person stores "Difficulty" as "Difﬁculty" and "flour" as
# "ﬂour"). Left alone, regexes looking for "Difficulty"
# silently never match, and "flour" in a question or a rules file never
# matches "ﬂour" in a chunk. Only ligatures are expanded on purpose,
# NOT full unicodedata NFKC normalization, which would also turn "½"
# into "1⁄2" and "①" into "1", breaking the unicode-fraction
# ingredient parser and the footnote-marker stripping.
LIGATURES = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
})


def extract_ordered_text(page):
    """Extract text in a reliable top-to-bottom reading order.

    Plain page.get_text() reads blocks in whatever order they're stored in
    the PDF's internal content stream, which isn't guaranteed to match
    visual reading order, blocks can come back out of sequence even on a
    simple single-column page. Explicitly sorting by vertical position (and
    horizontal as a tiebreaker) is a safe default for a single-column layout
    like this PDF.

    Note: this assumes single-column pages. If you ever ingest a PDF where
    the columns exist in the PDF itself (not just the printed book), a
    left-half/right-half split would be needed instead, sorting by y0 alone
    would incorrectly interleave the two columns line by line.
    """
    blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, block_type)
    text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]  # drop images
    if not text_blocks:
        return ""

    ordered = sorted(text_blocks, key=lambda b: (b[1], b[0]))  # y0, then x0
    return "\n".join(b[4].strip() for b in ordered).translate(LIGATURES)


def guess_printed_page_number(text, pdf_page_index):
    """Try to find the actual printed page number from the page's own text.
    Returns (page_number_or_None, confirmed). If no printed number is found
    anywhere in the book, callers should stop showing a page number at all
    rather than substituting the PDF's internal index, which for reflowed
    or multi-column PDFs often has no relationship to the printed numbering.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates = []
    for line in lines[:3] + lines[-3:]:
        if re.fullmatch(r"\d{1,4}", line):
            candidates.append(int(line))

    if candidates:
        return candidates[-1], True

    return None, False


def extract_pages(pdf_path):
    """Yield (page_number_or_None, confirmed, text) for every non-empty page."""
    doc = fitz.open(pdf_path)
    for page_index in range(len(doc)):
        page = doc[page_index]
        text = extract_ordered_text(page)
        if text:
            page_num, confirmed = guess_printed_page_number(text, page_index)
            yield page_num, confirmed, text
    doc.close()


def build_line_stream(pdf_path):
    """Concatenate every page's text into one flat list of lines, while
    separately tracking which line index each page started at. Recipes
    (and their headers) can span a page break, so boundary detection needs
    to operate on the whole book as one stream, not page by page. We keep
    page_starts as a side table so we can still recover "which page did
    this chunk begin on" afterward, without embedding markers into the
    text itself (which would otherwise get embedded into the vectors).
    """
    lines = []
    page_starts = []  # (line_index_where_this_page_begins, page_num, confirmed)
    for page_num, confirmed, page_text in extract_pages(pdf_path):
        page_starts.append((len(lines), page_num, confirmed))
        lines.extend(page_text.splitlines())
    return lines, page_starts


def page_for_line(line_idx, page_starts):
    """Look up which page a given line index falls on."""
    page_num, confirmed = None, False
    for start_idx, p, c in page_starts:
        if start_idx <= line_idx:
            page_num, confirmed = p, c
        else:
            break
    return page_num, confirmed
