"""
What the local tests need, and decorators that skip a test when it's
missing, so the suite runs anywhere and only tests what it can.

    needs_pdfs      the cookbook PDFs in COOKBOOKS_DIR
    needs_index     the recipe index (RECIPE_INDEX_PATH), built by ingest
    needs_database  the Chroma database (CHROMA_PATH) and the index
    needs_model     Ollama running with CHAT_MODEL pulled
    needs_search    the database, and Ollama with EMBED_MODEL pulled, for
                    vector search

The repository is public, so these tests hold only titles, counts and
numbers, never book text, and print nothing from the books.
"""

import os
import unittest

from common.config import BOOK_FILES, CHAT_MODEL, CHROMA_PATH, EMBED_MODEL, RECIPE_INDEX_PATH, book_pdf_path

# MODEL_REPEAT=5 asks every model case 5 times (each must pass), to see
# how reliable an answer is rather than whether it came out right once.
MODEL_REPEAT = max(1, int(os.environ.get("MODEL_REPEAT", "1")))


def books_found():
    return [b for b in BOOK_FILES if os.path.isfile(book_pdf_path(b))]


def _ollama_models():
    """Model names Ollama has pulled, or None if it isn't reachable."""
    try:
        import ollama
        client = ollama.Client(timeout=3)
        try:
            listing = client.list()
        finally:
            client._client.close()
    except Exception:
        return None
    models = listing.get("models", []) if isinstance(listing, dict) else listing.models
    names = set()
    for m in models:
        name = m.get("model") or m.get("name") if isinstance(m, dict) else m.model
        names.add(name)
        names.add(name.removesuffix(":latest"))
    return names


_MODELS = _ollama_models()


def _has_model(name):
    return _MODELS is not None and name in _MODELS


needs_pdfs = unittest.skipUnless(books_found(), "no cookbook PDFs in COOKBOOKS_DIR")
needs_index = unittest.skipUnless(os.path.isfile(RECIPE_INDEX_PATH), "no recipe index (run ingest.py)")
needs_database = unittest.skipUnless(os.path.isdir(CHROMA_PATH) and os.path.isfile(RECIPE_INDEX_PATH),
                                     "no database or recipe index (run ingest.py)")
needs_model = unittest.skipUnless(_has_model(CHAT_MODEL), f"Ollama isn't running with {CHAT_MODEL}")
needs_search = unittest.skipUnless(os.path.isdir(CHROMA_PATH) and _has_model(EMBED_MODEL),
                                   f"no database, or Ollama isn't running with {EMBED_MODEL}")
