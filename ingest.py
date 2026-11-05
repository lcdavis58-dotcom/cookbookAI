"""
Ingest cookbook PDFs into a local Chroma vector database.

Run:
    python3 ingest.py

Ingests every book listed in INGEST_BOOKS below, reading the PDFs from
COOKBOOKS_DIR (common/config.py; the Pi's folder unless the COOKBOOKS_DIR
environment variable says otherwise).

Stages:
    extract    ingest_utils/extract.py: PDF -> lines with layout, saved to
               EXTRACT_DIR and reused until the PDF changes
    structure  ingest_utils/structure.py: lines -> chunks (chunking.py,
               shared by all books, plus each book's module in books/)
    embed      here: only chunks whose text isn't already stored are
               embedded; the book's old chunks are replaced by the new set
    index      the recipe index, rebuilt at the end

Where things live:
    ingest_utils/pdf_text.py   saved extraction -> pages and line stream
    books/<book>.py     each book's own recipe-boundary detection
    match_utils/recipe_index.py  the recipe index, rebuilt at the end of
                               every run (tools/build_recipe_index.py
                               rebuilds it alone, without re-ingesting)

Requires:
    pip install pymupdf chromadb ollama
    ollama pull nomic-embed-text
"""

import os

import chromadb

from books import strategy_for
from common.config import CHROMA_PATH, COLLECTION_NAME, EMBED_MODEL, book_pdf_path
from common.embeddings import embed_document
from ingest_utils.structure import structure_book
from match_utils.recipe_index import build_index, save_index, summarize

# The books to ingest, by their title in common/config.BOOK_FILES. Only
# books with a recipe-aware profile in books/ are listed; the rest would
# fall back to generic page chunking. To ingest just one book, comment
# out the others. Keeping titles here, rather than typed on the command
# line each run, means a typo can't silently drop a book onto generic
# chunking.
INGEST_BOOKS = [
    "The Book On Pie",
    "Dessert Person",
    "BraveTart",
    "The Fearless Baker",
    "What's For Dessert",
    "The Cookie Book",
    "Savory Baking",
    "Momofuku Milk Bar",
    "Genius Desserts",
    "Genius Recipes",
]


def stored_embeddings(collection, book_title):
    """({chunk text: embedding}, stored ids) for the book's chunks
    already in the database. Only embeddings made with the current model
    are offered for reuse, so unchanged chunks are never embedded twice.
    Chunks stored before embed_model was recorded were all made with
    nomic-embed-text."""
    existing = collection.get(where={"book": book_title}, include=["documents", "embeddings", "metadatas"])
    return {doc: list(emb)
            for doc, emb, meta in zip(existing["documents"], existing["embeddings"], existing["metadatas"])
            if meta.get("embed_model", "nomic-embed-text") == EMBED_MODEL}, existing["ids"]


def ingest_pdf(pdf_path, book_title):
    """Extract (or load the saved extraction), structure, then embed only
    the chunks whose text isn't already stored, and replace the book's
    old chunks with the new set."""
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(COLLECTION_NAME)

    strategy = strategy_for(book_title)
    if strategy:
        print(f"Using recipe-aware chunking for '{book_title}' (strategy: {strategy})")
    else:
        print(f"No recipe-aware profile for '{book_title}', using generic "
              f"page-based chunking. Add a module to books/ and an entry to "
              f"RECIPE_AWARE_BOOKS there if this book has consistent recipe headers.")
    chunk_records, total_count, unconfirmed_count = structure_book(pdf_path, book_title)
    cached, old_ids = stored_embeddings(collection, book_title)

    ids, embeddings, documents, metadatas = [], [], [], []
    recipe_chunk_count = 0
    recipe_ids = set()
    short_recipe_chunks = []
    reused_count = 0

    for i, (chunk, content_type, page_num, confirmed, extra) in enumerate(chunk_records):
        # Chroma metadata can't store None, so use 0 as a sentinel for
        # "no confirmed page number." query.py checks page_confirmed
        # before ever showing this to you or the model.
        stored_page = page_num if confirmed else 0
        chunk_id = f"{book_title}-c{i}"
        ids.append(chunk_id)
        if chunk in cached:
            embeddings.append(cached[chunk])
            reused_count += 1
        else:
            embeddings.append(embed_document(chunk))
        documents.append(chunk)
        metadatas.append({
            "book": book_title,
            "page": stored_page,
            "page_confirmed": confirmed,
            "content_type": content_type,
            "embed_model": EMBED_MODEL,
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
        if chunk not in cached:
            print(f"  embedded chunk {i} [{content_type}{part_note}], {len(chunk)} chars{flag}")

    if ids:
        # Replace the book's chunks rather than upserting over them. Ids
        # are positions ("<book>-c<N>"), so a run with fewer chunks would
        # leave the old tail behind, and an upsert can keep metadata keys
        # (recipe_id) on a chunk that's no longer a recipe. Everything is
        # embedded before this point, so nothing slow sits between the
        # delete and the add.
        stale = set(old_ids) - set(ids)
        if old_ids:
            collection.delete(ids=old_ids)
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        print(f"Ingested {len(ids)} chunks from '{book_title}' "
              f"({len(recipe_ids)} recipes, stored as {recipe_chunk_count} recipe-tagged chunks); "
              f"embedded {len(ids) - reused_count}, reused {reused_count} unchanged, "
              f"removed {len(stale)} old")
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
    for book_title in INGEST_BOOKS:
        pdf_path = book_pdf_path(book_title)
        print(f"\n=== {book_title} ===")
        if not os.path.isfile(pdf_path):
            print(f"Skipping, PDF not found at {pdf_path} (check COOKBOOKS_DIR)")
            continue
        ingest_pdf(pdf_path, book_title)

    # Rebuilt from the whole database, not just the books ingested this
    # run, so ingesting one book at a time still leaves a complete index.
    print("\n=== Recipe index ===")
    entries = build_index()
    save_index(entries)
    print("\n".join(summarize(entries)))
