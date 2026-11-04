"""
A cookbook's text page by page and as one continuous line stream, read
from its saved extraction (ingest_utils/extract.py, which makes it from
the PDF the first time). Book-independent.
"""

from ingest_utils.extract import load_extraction


def extract_pages(pdf_path):
    """Yield (page_number_or_None, confirmed, text) for every non-empty page."""
    for page in load_extraction(pdf_path):
        yield page["printed"], page["confirmed"], "\n".join(l["text"] for l in page["lines"])


def build_layout_stream(pdf_path):
    """Every line of the book as its extracted record (text plus layout,
    see ingest_utils/extract.py), with each record's PDF page "index"
    added, and page_starts as in build_line_stream."""
    records = []
    page_starts = []  # (line_index_where_this_page_begins, page_num, confirmed)
    for page in load_extraction(pdf_path):
        page_starts.append((len(records), page["printed"], page["confirmed"]))
        records.extend(dict(line, page=page["index"]) for line in page["lines"])
    return records, page_starts


def build_line_stream(pdf_path):
    """Concatenate every page's text into one flat list of lines, while
    separately tracking which line index each page started at. Recipes
    (and their headers) can span a page break, so boundary detection needs
    to operate on the whole book as one stream, not page by page. We keep
    page_starts as a side table so we can still recover "which page did
    this chunk begin on" afterward, without embedding markers into the
    text itself (which would otherwise get embedded into the vectors).
    """
    records, page_starts = build_layout_stream(pdf_path)
    return [r["text"] for r in records], page_starts


def page_for_line(line_idx, page_starts):
    """Look up which page a given line index falls on."""
    page_num, confirmed = None, False
    for start_idx, p, c in page_starts:
        if start_idx <= line_idx:
            page_num, confirmed = p, c
        else:
            break
    return page_num, confirmed
