"""
Ingest cookbook PDFs into a local Chroma vector database.

Run:
    python3 ingest.py

Ingests every book listed in BOOKS below. To add a cookbook, add an
entry there; to ingest just one book, comment out the others.

Where things live:
    ingest_utils/pdf_text.py   PDF -> ordered text and line stream
    ingest_utils/chunking.py   line stream -> chunks (shared by all books)
    books/<book>.py     each book's own recipe-boundary detection

Requires:
    pip install pymupdf chromadb ollama
    ollama pull nomic-embed-text
"""

import os

import chromadb

from books import strategy_for, profile_for
from common.config import CHROMA_PATH, COLLECTION_NAME
from common.embeddings import embed_document
from ingest_utils.chunking import chunk_recipe_aware, chunk_text
from ingest_utils.pdf_text import build_line_stream, extract_pages

COOKBOOKS_DIR = "/home/pi/CookbookAI/cookbooks"

# Book title -> PDF path. The title is what gets stored on every chunk and
# shown in citations, and it's also the key books uses to pick a
# chunking strategy, so it must match an entry in RECIPE_AWARE_BOOKS
# there (case-insensitive) for recipe-aware chunking to kick in. Keeping
# titles here, rather than typed on the command line each run, means a
# typo can't silently drop a book onto generic chunking.
BOOKS = {
    "The Book On Pie": os.path.join(COOKBOOKS_DIR, "TheBookOnPie.pdf"),
    "Dessert Person": os.path.join(COOKBOOKS_DIR, "DessertPerson.pdf"),
}


def ingest_pdf(pdf_path, book_title):
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(COLLECTION_NAME)

    strategy = strategy_for(book_title)

    if strategy:
        print(f"Using recipe-aware chunking for '{book_title}' (strategy: {strategy})")
        lines, page_starts = build_line_stream(pdf_path)
        chunk_records = chunk_recipe_aware(lines, page_starts, book_title, profile_for(strategy))
        unconfirmed_count = sum(1 for _, p, c in page_starts if not c)
        total_count = len(page_starts)
    else:
        print(f"No recipe-aware profile for '{book_title}', using generic "
              f"page-based chunking. Add a module to books/ and an entry to "
              f"RECIPE_AWARE_BOOKS there if this book has consistent recipe headers.")
        chunk_records = []
        unconfirmed_count = 0
        total_count = 0
        for page_num, confirmed, page_text in extract_pages(pdf_path):
            total_count += 1
            if not confirmed:
                unconfirmed_count += 1
            for chunk in chunk_text(page_text):
                chunk_records.append((chunk, "unknown", page_num, confirmed, {}))

    ids, embeddings, documents, metadatas = [], [], [], []
    recipe_chunk_count = 0
    recipe_ids = set()
    short_recipe_chunks = []

    for i, (chunk, content_type, page_num, confirmed, extra) in enumerate(chunk_records):
        # Chroma metadata can't store None, so use 0 as a sentinel for
        # "no confirmed page number." query.py checks page_confirmed
        # before ever showing this to you or the model.
        stored_page = page_num if confirmed else 0
        chunk_id = f"{book_title}-c{i}"
        ids.append(chunk_id)
        embeddings.append(embed_document(chunk))
        documents.append(chunk)
        metadatas.append({
            "book": book_title,
            "page": stored_page,
            "page_confirmed": confirmed,
            "content_type": content_type,
            **extra,
        })
        if content_type == "recipe":
            recipe_chunk_count += 1
            recipe_ids.add(extra.get("recipe_id"))
            # A real recipe (title + yield + intro + ingredients +
            # instructions) is essentially never this short. If one comes
            # out under ~180 chars, it's a strong signal the chunk got cut
            # off right after the title/yield line, the same failure mode
            # the wrapped-DIFFICULTY bug caused. Flag it for a spot check
            # rather than silently shipping a truncated recipe. Only
            # applies to single-part recipes, the last part of a split
            # recipe is legitimately allowed to be short.
            if extra.get("part_count", 1) == 1 and len(chunk) < 180:
                short_recipe_chunks.append((i, chunk.splitlines()[0] if chunk else ""))
        flag = "" if confirmed else "  (no printed page number found)"
        part_note = (f", part {extra['part'] + 1}/{extra['part_count']}"
                     if extra.get("part_count", 1) > 1 else "")
        print(f"  embedded chunk {i} [{content_type}{part_note}], {len(chunk)} chars{flag}")

    if ids:
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        print(f"Ingested {len(ids)} chunks from '{book_title}' "
              f"({len(recipe_ids)} recipes, stored as {recipe_chunk_count} recipe-tagged chunks)")
        if short_recipe_chunks:
            print(f"\nWarning: {len(short_recipe_chunks)} recipe-tagged chunk(s) "
                  f"came out under 180 characters, likely truncated before the "
                  f"actual ingredients/instructions. Worth spot-checking:")
            for idx, first_line in short_recipe_chunks:
                print(f"  chunk {idx}: \"{first_line}\"")
        if unconfirmed_count == total_count:
            print(f"No printed page numbers were found anywhere in this book. "
                  f"Citations for '{book_title}' will reference the book title "
                  f"only, not a page number.")
        elif unconfirmed_count:
            print(f"Note: {unconfirmed_count} of {total_count} page(s) had no "
                  f"detectable printed page number. Those chunks will be cited "
                  f"by book title only.")
    else:
        print(f"No text found in {pdf_path}. Is it a scanned/image-only PDF? "
              f"If so, it needs OCR (e.g. ocrmypdf) before this will work.")


if __name__ == "__main__":
    for book_title, pdf_path in BOOKS.items():
        print(f"\n=== {book_title} ===")
        if not os.path.isfile(pdf_path):
            print(f"Skipping, PDF not found at {pdf_path}")
            continue
        ingest_pdf(pdf_path, book_title)
