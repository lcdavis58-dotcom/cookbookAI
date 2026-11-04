"""
The structure stage: a book's saved extraction -> its chunk records
(recipes, technique sections, everything else). Takes seconds and needs
neither the model nor the database, so diagnostics can run it on any
machine with the PDFs (tools/diagnostics/structure_baseline.py does).
"""

from books import profile_for, strategy_for
from ingest_utils.chunking import chunk_recipe_aware, chunk_text
from ingest_utils.pdf_text import build_layout_stream, extract_pages


def structure_book(pdf_path, book_title):
    """(chunk_records, page_count, unconfirmed_page_count). A record is
    (text, content_type, page_num, confirmed, extra_metadata), see
    chunking.chunk_recipe_aware. A book with no profile in books/ gets
    generic page-based chunks tagged content_type="unknown"."""
    strategy = strategy_for(book_title)
    if strategy:
        layout, page_starts = build_layout_stream(pdf_path)
        lines = [r["text"] for r in layout]
        records = chunk_recipe_aware(lines, page_starts, book_title, profile_for(strategy),
                                     layout=layout)
        unconfirmed = sum(1 for _, _, confirmed in page_starts if not confirmed)
        return records, len(page_starts), unconfirmed

    records = []
    page_count = unconfirmed = 0
    for page_num, confirmed, page_text in extract_pages(pdf_path):
        page_count += 1
        if not confirmed:
            unconfirmed += 1
        for chunk in chunk_text(page_text):
            records.append((chunk, "unknown", page_num, confirmed, {}))
    return records, page_count, unconfirmed
